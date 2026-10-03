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
  REMOTE_FILES_ROOT    folder exposed to the file manager
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
PC_NAME = socket.gethostname()

ALLOW_REMOTE_CAMERA = os.environ.get("ALLOW_REMOTE_CAMERA", "1") == "1"
ALLOW_REMOTE_INPUT = os.environ.get("ALLOW_REMOTE_INPUT", "1") == "1"
ALLOW_REMOTE_CMD = os.environ.get("ALLOW_REMOTE_CMD", "0") == "1"

# Only this directory is exposed to the server file manager.
REMOTE_FILES_ROOT = Path(
    os.environ.get("REMOTE_FILES_ROOT", str(Path.home() / "RemoteNeonShare"))
).expanduser().resolve()
REMOTE_FILES_ROOT.mkdir(parents=True, exist_ok=True)

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


def safe_rel(rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    target = (REMOTE_FILES_ROOT / rel).resolve()
    try:
        target.relative_to(REMOTE_FILES_ROOT)
    except ValueError:
        raise ValueError("Path traversal blocked")
    return target


def rel_for(path: Path) -> str:
    return path.resolve().relative_to(REMOTE_FILES_ROOT).as_posix()


def file_list(rel: str) -> dict[str, Any]:
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
    return {"ok": True, "path": rel_for(base), "items": items}


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
    if path == REMOTE_FILES_ROOT:
        return {"ok": False, "error": "cannot delete shared root"}
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
        dest.relative_to(REMOTE_FILES_ROOT)
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


def client_loop():
    global STREAMING_SCREEN, STREAMING_CAMERA, STOP

    while not STOP:
        try:
            caps = ["screen", "files"]
            if ALLOW_REMOTE_CAMERA and CV2_AVAILABLE:
                caps.append("camera")
            if ALLOW_REMOTE_INPUT and PYAUTOGUI_AVAILABLE:
                caps.append("input")
            if ALLOW_REMOTE_CMD:
                caps.append("commands")

            res = post_json(
                "/api/heartbeat",
                {
                    "client_id": CLIENT_ID,
                    "name": PC_NAME,
                    "caps": caps,
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
    print("Shared files root:", REMOTE_FILES_ROOT)
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

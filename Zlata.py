# -*- coding: utf-8 -*-
"""
Zlata z16 Unified Server — multi-PC dashboard (fixed)

Merged z15/z15.7.3 UI + z16 client protocol + filesystem sync.
Single server build for z16_keyboard_fs_sync.py.

- z16 heartbeat/job protocol remains compatible.
- Multiple simultaneously connected z16 clients are supported.
- z15 visual language and compatible page/endpoint aliases are retained.
- Web UI requires password authentication.
- Old local-only disruptive prank/keylogger/process-control features are not
  exposed through the z16 protocol.

Flask server for z16.py using the visual style/layout of z15.7.3.py.
The remote client protocol remains compatible with z16.py:
  POST /api/heartbeat
  POST /api/upload_frame/<cid>
  POST /api/upload_camera/<cid>
  POST /api/job_result/<cid>/<job_id>

Run:
  pip install flask
  set REMOTE_PASS=your-password
  set REMOTE_CLIENT_TOKEN=shared-token
  python Zlata_z15_sync.py
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
    abort,
    flash,
    get_flashed_messages,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)


# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
APPDATA = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
DATA_DIR = Path(os.environ.get("REMOTE_DATA_DIR", os.path.join(APPDATA, "RemoteNeon")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
CHAT_FILE = DATA_DIR / "chat.json"
NOTIFS_FILE = DATA_DIR / "notifications.json"
MESSAGES_FILE = DATA_DIR / "messages.json"

ADMIN_USERNAME = os.environ.get("REMOTE_USER", "pro")
ADMIN_PASSWORD = os.environ.get("REMOTE_PASS", "change-me-now")
CLIENT_TOKEN = os.environ.get("REMOTE_CLIENT_TOKEN", "change-me-client-token")
SECRET_FILE = DATA_DIR / "flask_secret.txt"
def _load_or_create_secret() -> str:
    configured = os.environ.get("FLASK_SECRET", "").strip()
    if configured:
        return configured
    try:
        if SECRET_FILE.exists():
            value = SECRET_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = base64.urlsafe_b64encode(os.urandom(48)).decode("ascii")
        SECRET_FILE.write_text(value, encoding="utf-8")
        return value
    except Exception:
        return base64.urlsafe_b64encode(os.urandom(48)).decode("ascii")

SECRET_KEY = _load_or_create_secret()
HOST = os.environ.get("REMOTE_HOST", "0.0.0.0")
PORT = int(os.environ.get("REMOTE_PORT", "5000"))
JOB_TTL = 300
MAX_RESULT_B64 = 14 * 1024 * 1024
ONLINE_TTL = 15

THEMES = {
    "green": {"neon": "#00ffd0", "muted": "#4fbdb1"},
    "blue": {"neon": "#00c8ff", "muted": "#4fa6bd"},
    "red": {"neon": "#ff4d4d", "muted": "#bd4f4f"},
    "purple": {"neon": "#b84dff", "muted": "#9b4fbd"},
    "yellow": {"neon": "#ffe44d", "muted": "#bdb44f"},
    "pink": {"neon": "#ff4d9d", "muted": "#bd4f87"},
    "cyan": {"neon": "#00ffd6", "muted": "#4fbdb1"},
    "orange": {"neon": "#ff9f4d", "muted": "#bd8a4f"},
    "mint": {"neon": "#4dffb8", "muted": "#6fbda1"},
}
DEFAULT_THEME = "green"

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

clients: dict[str, dict[str, Any]] = {}
clients_lock = threading.RLock()
data_lock = threading.RLock()


# -----------------------------------------------------------------------------
# SMALL STORAGE HELPERS
# -----------------------------------------------------------------------------
def now_ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_json(path: Path, default: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: Any):
    with data_lock:
        ensure_json(path, default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default


def save_json(path: Path, value: Any) -> None:
    with data_lock:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def hash_password(password: str) -> str:
    """PBKDF2 password storage; older plaintext users remain compatible."""
    salt = os.urandom(16)
    rounds = 210_000
    digest = __import__("hashlib").pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, rounds
    )
    return (
        f"pbkdf2_sha256${rounds}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """Return (valid, should_upgrade_plaintext)."""
    stored = str(stored or "")
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds_s, salt_b64, digest_b64 = stored.split("$", 3)
            rounds = int(rounds_s)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(digest_b64)
            actual = __import__("hashlib").pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, rounds
            )
            return __import__("hmac").compare_digest(actual, expected), False
        except Exception:
            return False, False
    return __import__("hmac").compare_digest(password, stored), bool(stored)


def load_users() -> dict[str, Any]:
    users = load_json(USERS_FILE, {})
    if not isinstance(users, dict):
        users = {}
    if ADMIN_USERNAME not in users:
        users[ADMIN_USERNAME] = {
            "password": hash_password(ADMIN_PASSWORD),
            "permissions": ["admin", "screen", "files", "commands", "camera", "remote", "chat"],
            "notify_on": [],
        }
        save_json(USERS_FILE, users)
    return users


def save_users(users: dict[str, Any]) -> None:
    save_json(USERS_FILE, users)


def add_notification(targets: str | list[str], title: str, message: str) -> None:
    if isinstance(targets, str):
        targets = [targets]
    notifs = load_json(NOTIFS_FILE, {})
    if not isinstance(notifs, dict):
        notifs = {}
    for username in targets:
        items = notifs.setdefault(username, [])
        items.insert(0, {"ts": now_ts(), "title": title, "message": message})
        notifs[username] = items[:200]
    save_json(NOTIFS_FILE, notifs)


def chat_load() -> list[dict[str, str]]:
    data = load_json(CHAT_FILE, [])
    return data if isinstance(data, list) else []


def chat_post(username: str, message: str) -> None:
    message = str(message or "").strip()
    if not message:
        return
    items = chat_load()
    items.append({"user": username, "msg": message, "ts": now_ts()})
    save_json(CHAT_FILE, items[-5000:])


def messages_load() -> dict[str, list[dict[str, str]]]:
    data = load_json(MESSAGES_FILE, {})
    return data if isinstance(data, dict) else {}


def messages_add(to_user: str, from_user: str, message: str) -> None:
    data = messages_load()
    data.setdefault(to_user, []).append({"from": from_user, "msg": message, "ts": now_ts()})
    save_json(MESSAGES_FILE, data)


def theme_colors() -> tuple[str, str]:
    theme = session.get("theme", DEFAULT_THEME)
    if theme not in THEMES:
        theme = DEFAULT_THEME
    return THEMES[theme]["neon"], THEMES[theme]["muted"]


# -----------------------------------------------------------------------------
# AUTH / PERMISSIONS
# -----------------------------------------------------------------------------
def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("logged_in") is not True:
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def has_perm(permission: str) -> bool:
    username = session.get("username")
    if username == ADMIN_USERNAME:
        return True
    user = load_users().get(username, {})
    return permission in user.get("permissions", [])


def require_perm(permission: str):
    if not has_perm(permission):
        flash(f"No access to {permission}")
        return redirect(url_for("index"))
    return None


# -----------------------------------------------------------------------------
# CLIENT STATE / JOB QUEUE
# -----------------------------------------------------------------------------
def client_token_ok() -> bool:
    return request.headers.get("X-Client-Token", "") == CLIENT_TOKEN


def get_client(cid: str) -> dict[str, Any] | None:
    with clients_lock:
        return clients.get(cid)


def is_online(c: dict[str, Any]) -> bool:
    return (time.time() - c.get("last_seen", 0)) < ONLINE_TTL


def select_client(cid: str | None) -> bool:
    if not cid:
        return False
    c = get_client(cid)
    if not c or not is_online(c):
        return False
    session["selected_client"] = cid
    return True


def get_selected_client() -> tuple[str | None, dict[str, Any] | None]:
    cid = session.get("selected_client")
    c = get_client(cid) if cid else None
    if c and is_online(c):
        return cid, c
    with clients_lock:
        online = [(k, v) for k, v in clients.items() if is_online(v)]
    if online:
        cid, c = sorted(online, key=lambda kv: kv[1].get("name", "").lower())[0]
        session["selected_client"] = cid
        return cid, c
    return None, None


def cleanup_jobs_locked(c: dict[str, Any]) -> None:
    cutoff = time.time() - JOB_TTL
    c["jobs"] = [j for j in c.get("jobs", []) if j.get("created", time.time()) >= cutoff]
    c["results"] = {
        jid: value
        for jid, value in c.get("results", {}).items()
        if value.get("_ts", time.time()) >= cutoff
    }


def queue_job(cid: str, action: str, **payload: Any) -> str:
    with clients_lock:
        c = clients.get(cid)
        if not c or not is_online(c):
            raise KeyError(cid)
        cleanup_jobs_locked(c)
        job_id = uuid.uuid4().hex
        c["jobs"].append({"id": job_id, "action": action, "payload": payload, "created": time.time()})
        return job_id


def set_job_result(cid: str, job_id: str, result: dict[str, Any]) -> None:
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return
        value = dict(result)
        value["_ts"] = time.time()
        c["results"][job_id] = value
        cleanup_jobs_locked(c)


def get_job_result(cid: str, job_id: str):
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return None
        cleanup_jobs_locked(c)
        return c["results"].get(job_id)


def require_selected_client() -> tuple[str, dict[str, Any]]:
    cid, c = get_selected_client()
    if not cid or not c:
        abort(409, description="No online z16 client selected")
    return cid, c


# -----------------------------------------------------------------------------
# PROTOCOL: THIS MATCHES z16.py
# -----------------------------------------------------------------------------
@app.post("/api/heartbeat")
def api_heartbeat():
    if not client_token_ok():
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    cid = str(data.get("client_id", "")).strip()
    if not cid:
        return jsonify(error="client_id required"), 400

    with clients_lock:
        if cid not in clients:
            clients[cid] = {
                "name": data.get("name") or "Unknown PC",
                "ip": request.remote_addr or "?",
                "last_seen": 0.0,
                "caps": [],
                "screen_frame": None,
                "camera_frame": None,
                "screen_viewed": 0.0,
                "camera_viewed": 0.0,
                "jobs": [],
                "results": {},
                "cpu": None,
                "ram": None,
            }
        c = clients[cid]
        c["name"] = data.get("name", c["name"])
        c["ip"] = request.remote_addr or c["ip"]
        c["caps"] = list(data.get("caps") or [])
        c["last_seen"] = time.time()
        if data.get("cpu") is not None:
            c["cpu"] = data.get("cpu")
        if data.get("ram") is not None:
            c["ram"] = data.get("ram")
        c["stream_screen"] = (time.time() - c.get("screen_viewed", 0)) < 3
        c["stream_camera"] = (time.time() - c.get("camera_viewed", 0)) < 3
        jobs = list(c.get("jobs", []))
        c["jobs"] = []
        cleanup_jobs_locked(c)

    return jsonify(
        stream_screen=bool(c.get("stream_screen")),
        stream_camera=bool(c.get("stream_camera")),
        commands=jobs,
        server_ts=now_ts(),
    )


@app.post("/api/upload_frame/<cid>")
def api_upload_frame(cid: str):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_data()
    if len(data) > 4 * 1024 * 1024:
        return "frame too large", 413
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return "unknown client", 404
        c["screen_frame"] = data
        c["last_seen"] = time.time()
    return "OK"


@app.post("/api/upload_camera/<cid>")
def api_upload_camera(cid: str):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_data()
    if len(data) > 4 * 1024 * 1024:
        return "frame too large", 413
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return "unknown client", 404
        c["camera_frame"] = data
        c["last_seen"] = time.time()
    return "OK"


@app.post("/api/job_result/<cid>/<job_id>")
def api_job_result(cid: str, job_id: str):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_json(silent=True) or {}
    if isinstance(data.get("data_b64"), str) and len(data["data_b64"]) > MAX_RESULT_B64:
        return "result too large", 413
    set_job_result(cid, job_id, data)
    return "OK"


def mjpeg_stream(cid: str, camera: bool = False):
    key = "camera_frame" if camera else "screen_frame"
    viewed_key = "camera_viewed" if camera else "screen_viewed"
    while True:
        with clients_lock:
            c = clients.get(cid)
            if not c:
                return
            c[viewed_key] = time.time()
            frame = c.get(key)
            online = is_online(c)
        if not online:
            time.sleep(0.25)
            continue
        if frame:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.05)


@app.get("/screen_feed")
@login_required
def screen_feed():
    cid, _ = require_selected_client()
    return Response(mjpeg_stream(cid, camera=False), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/camera_feed")
@login_required
def camera_feed():
    cid, _ = require_selected_client()
    return Response(mjpeg_stream(cid, camera=True), mimetype="multipart/x-mixed-replace; boundary=frame")


# -----------------------------------------------------------------------------
# PAGE ROUTES / ACTIONS
# -----------------------------------------------------------------------------
@app.get("/api/clients")
@login_required
def api_clients():
    """Machine-readable multi-device status for the dashboard."""
    with clients_lock:
        items = []
        for cid, c in clients.items():
            items.append({
                "id": cid,
                "name": c.get("name", "Unknown PC"),
                "online": is_online(c),
                "ip": c.get("ip", "?"),
                "last_seen": c.get("last_seen", 0),
                "caps": sorted(c.get("caps", [])),
                "cpu": c.get("cpu"),
                "ram": c.get("ram"),
            })
    items.sort(key=lambda x: (not x["online"], x["name"].lower(), x["id"]))
    return jsonify(ok=True, selected=session.get("selected_client"), clients=items)


@app.route("/", methods=["GET"])
@login_required
def index():
    cid, selected = get_selected_client()
    neon, muted = theme_colors()
    users = load_users()
    username = session.get("username")
    perms = users.get(username, {}).get("permissions", [])
    flash_messages = get_flashed_messages()
    cmd_output = session.pop("last_cmd_output", None)

    with clients_lock:
        pc_list = []
        for client_id, c in clients.items():
            pc_list.append({
                "id": client_id,
                "name": c.get("name", "Unknown PC"),
                "online": is_online(c),
                "ip": c.get("ip", "?"),
                "last_seen": dt.datetime.fromtimestamp(c["last_seen"]).strftime("%Y-%m-%d %H:%M:%S") if c.get("last_seen") else "never",
                "caps": sorted(c.get("caps", [])),
                "cpu": c.get("cpu"),
                "ram": c.get("ram"),
            })
    pc_list.sort(key=lambda x: (not x["online"], x["name"].lower()))

    # The z15-compatible template expects these values explicitly.
    # Keeping them in the render context prevents Jinja UndefinedError
    # when the main dashboard is opened after login.
    selected_cpu = float(selected.get("cpu") or 0.0) if selected else 0.0
    selected_ram = float(selected.get("ram") or 0.0) if selected else 0.0

    return render_template_string(
        MAIN_TEMPLATE,
        username=username,
        permissions=perms,
        neon=neon,
        muted=muted,
        themes_list=sorted(THEMES),
        pc_list=pc_list,
        selected=selected,
        selected_cid=cid,
        cmd_output=cmd_output,
        flashes=flash_messages,
        admin_username=ADMIN_USERNAME,
        theme=session.get("theme", DEFAULT_THEME),
        cpu=max(0.0, min(100.0, selected_cpu)),
        ram=max(0.0, min(100.0, selected_ram)),
        TROLLS=TROLLS,
    )


@app.post("/select_client")
@login_required
def select_client_route():
    cid = request.form.get("cid", "").strip()
    if not select_client(cid):
        flash("Client is offline or not found")
    return redirect(request.form.get("next") or url_for("index"))


@app.post("/set_theme")
@login_required
def set_theme():
    data = request.get_json(silent=True) or {}
    theme = data.get("theme") or request.form.get("theme")
    if theme not in THEMES:
        return jsonify(error="unknown theme"), 400
    session["theme"] = theme
    neon, muted = theme_colors()
    if request.is_json:
        return jsonify(ok=True, theme=theme, neon=neon, muted=muted)
    return redirect(request.referrer or url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_users()
    msg = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = users.get(username)
        valid, upgrade = verify_password(
            password, user.get("password", "") if isinstance(user, dict) else ""
        )
        if not user or not valid:
            add_notification(ADMIN_USERNAME, "Failed login", f"Invalid login for {username or '<empty>'}")
            msg = "Невірні облікові дані"
        else:
            if upgrade:
                user["password"] = hash_password(password)
                users[username] = user
                save_users(users)
            session.clear()
            session["logged_in"] = True
            session["username"] = username
            add_notification(username, "Login", f"{username} logged in at {now_ts()}")
            return redirect(request.args.get("next") or url_for("index"))
    return render_template_string(LOGIN_TEMPLATE, msg=msg, admin=ADMIN_USERNAME)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -----------------------------------------------------------------------------
# REMOTE COMMAND / INPUT / CAMERA / FILES
# -----------------------------------------------------------------------------
def post_job_and_mark(action: str, **payload: Any) -> dict[str, Any]:
    cid, _ = require_selected_client()
    try:
        jid = queue_job(cid, action, **payload)
        return {"ok": True, "job_id": jid, "cid": cid}
    except KeyError:
        return {"ok": False, "error": "client is offline"}


@app.post("/api/input/click")
@login_required
def api_input_click():
    denial = require_perm("remote")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    data = request.get_json(silent=True) or {}
    return jsonify(post_job_and_mark("input_click", x=data.get("x"), y=data.get("y"), type=data.get("type", "click")))


@app.post("/api/input/type")
@login_required
def api_input_type():
    denial = require_perm("remote")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    data = request.get_json(silent=True) or {}
    return jsonify(post_job_and_mark("input_type", text=str(data.get("text", ""))[:4000]))


@app.post("/api/input/key")
@login_required
def api_input_key():
    denial = require_perm("remote")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    data = request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip()
    modifiers = data.get("modifiers") or []
    if not key:
        return jsonify(ok=False, error="key required"), 400
    if not isinstance(modifiers, list) or len(modifiers) > 4:
        return jsonify(ok=False, error="invalid modifiers"), 400
    return jsonify(post_job_and_mark("input_key", key=key, modifiers=[str(x) for x in modifiers]))


@app.post("/api/demo-prank")
@login_required
def api_demo_prank():
    denial = require_perm("remote")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    data = request.get_json(silent=True) or {}
    effect = str(data.get("effect", "")).lower()
    if effect != "beep":
        return jsonify(ok=False, error="Only harmless opt-in demo effect is available."), 400
    return jsonify(post_job_and_mark("demo_prank", effect=effect))


@app.post("/api/command")
@login_required
def api_command():
    denial = require_perm("commands")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    data = request.get_json(silent=True) or {}
    command = str(data.get("command", "")).strip()
    if not command:
        return jsonify(ok=False, error="empty command"), 400
    return jsonify(post_job_and_mark("command", command=command))


@app.get("/job/<job_id>")
@login_required
def job_status(job_id: str):
    cid, _ = require_selected_client()
    result = get_job_result(cid, job_id)
    if result is None:
        return jsonify(done=False)
    return jsonify(done=True, result=result)


@app.get("/camera")
@login_required
def camera_page():
    denial = require_perm("camera")
    if denial:
        return denial
    cid, c = require_selected_client()
    neon, muted = theme_colors()
    return render_template_string(
        CAMERA_TEMPLATE,
        cid=cid,
        pc_name=c.get("name", "Unknown PC"),
        neon=neon,
        muted=muted,
        themes_list=sorted(THEMES),
        username=session.get("username"),
    )


@app.post("/api/camera/photo")
@login_required
def api_camera_photo():
    denial = require_perm("camera")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    return jsonify(post_job_and_mark("camera_photo"))


@app.get("/remote")
@login_required
def remote_page():
    denial = require_perm("remote")
    if denial:
        return denial
    cid, c = require_selected_client()
    neon, muted = theme_colors()
    return render_template_string(
        REMOTE_TEMPLATE,
        cid=cid,
        pc_name=c.get("name", "Unknown PC"),
        neon=neon,
        muted=muted,
        themes_list=sorted(THEMES),
        username=session.get("username"),
    )


# ----- remote filesystem -----
def fs_job(action: str, **payload: Any):
    denial = require_perm("files")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    return jsonify(post_job_and_mark(action, **payload))


@app.get("/files")
@login_required
def files_page():
    denial = require_perm("files")
    if denial:
        return denial
    neon, muted = theme_colors()
    cid, c = require_selected_client()
    path = request.args.get("path", "")
    return render_template_string(
        FILES_TEMPLATE,
        cid=cid,
        pc_name=c.get("name", "Unknown PC"),
        current_path=path or ".",
        neon=neon,
        muted=muted,
        themes_list=sorted(THEMES),
        username=session.get("username"),
        selected_path=path,
        fs_parent=(str(Path(path).parent.as_posix()) if path and Path(path).parent.as_posix() not in (".", "") else ""),
    )


@app.get("/api/fs/list")
@login_required
def api_fs_list():
    return fs_job("fs_list", path=request.args.get("path", ""))


@app.get("/api/fs/view")
@login_required
def api_fs_view():
    return fs_job("fs_view", path=request.args.get("path", ""))


@app.get("/api/fs/download")
@login_required
def api_fs_download():
    denial = require_perm("files")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    result = post_job_and_mark("fs_download", path=request.args.get("path", ""))
    if not result.get("ok"):
        return jsonify(result)
    # The page JS polls this job and turns the returned base64 into a browser download.
    return jsonify(result)


@app.post("/api/fs/delete")
@login_required
def api_fs_delete():
    data = request.get_json(silent=True) or {}
    return fs_job("fs_delete", path=data.get("path", ""))


@app.post("/api/fs/upload")
@login_required
def api_fs_upload():
    data = request.get_json(silent=True) or {}
    return fs_job("fs_upload", path=data.get("path", ""), name=data.get("name", ""), data_b64=data.get("data_b64", ""))


# -----------------------------------------------------------------------------
# USER / NOTIFICATION / MESSAGE / CHAT PAGES
# -----------------------------------------------------------------------------
@app.route("/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
    if session.get("username") != ADMIN_USERNAME:
        flash("Тільки адмін може редагувати користувачів")
        return redirect(url_for("index"))
    users = load_users()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            perms = [x for x in request.form.get("permissions", "").split(",") if x]
            if username and password and username not in users:
                users[username] = {"password": hash_password(password), "permissions": perms, "notify_on": []}
                save_users(users)
                add_notification(ADMIN_USERNAME, "User created", username)
        elif action == "update":
            username = request.form.get("username_update", "").strip()
            if username in users:
                password = request.form.get("password_update", "")
                perms = [x for x in request.form.get("permissions_update", "").split(",") if x]
                if password:
                    users[username]["password"] = hash_password(password)
                users[username]["permissions"] = perms
                save_users(users)
        elif action == "delete":
            username = request.form.get("username_del", "").strip()
            if username and username != ADMIN_USERNAME:
                users.pop(username, None)
                save_users(users)
        return redirect(url_for("admin_users"))
    neon, muted = theme_colors()
    return render_template_string(
        ADMIN_USERS_TEMPLATE,
        users=users,
        neon=neon,
        muted=muted,
        themes_list=sorted(THEMES),
        username=session.get("username"),
        admin_username=ADMIN_USERNAME,
    )


@app.get("/notifications")
@login_required
def notifications_page():
    username = session.get("username")
    notifs = load_json(NOTIFS_FILE, {})
    neon, muted = theme_colors()
    return render_template_string(NOTIFS_TEMPLATE, notifs=notifs.get(username, []), username=username, neon=neon, muted=muted)


@app.route("/messages", methods=["GET", "POST"])
@login_required
def messages_page():
    username = session.get("username")
    users = load_users()
    data = messages_load()
    if request.method == "POST":
        to_user = request.form.get("to", "").strip()
        message = request.form.get("msg", "").strip()
        if to_user in users and message:
            messages_add(to_user, username, message)
            add_notification(to_user, "New message", f"From {username}: {message}")
        return redirect(url_for("messages_page"))
    neon, muted = theme_colors()
    return render_template_string(MESSAGES_TEMPLATE, messages=data.get(username, []), users=sorted(users), username=username, neon=neon, muted=muted)


@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat_page():
    username = session.get("username")
    if request.method == "POST":
        chat_post(username, request.form.get("msg", ""))
        return redirect(url_for("chat_page"))
    neon, muted = theme_colors()
    return render_template_string(CHAT_TEMPLATE, chat=chat_load(), username=username, neon=neon, muted=muted)


# -----------------------------------------------------------------------------
# FULLSCREEN PAGE
# -----------------------------------------------------------------------------
@app.get("/fullscreen")
@login_required
def fullscreen_page():
    denial = require_perm("screen")
    if denial:
        return denial
    cid, c = require_selected_client()
    neon, muted = theme_colors()
    return render_template_string(
        FULLSCREEN_TEMPLATE,
        cid=cid,
        pc_name=c.get("name", "Unknown PC"),
        neon=neon,
        muted=muted,
        themes_list=sorted(THEMES),
        username=session.get("username"),
    )


@app.post("/api/fullscreen/click")
@login_required
def fullscreen_click():
    denial = require_perm("remote")
    if denial:
        return jsonify(ok=False, error="no access"), 403
    data = request.get_json(silent=True) or {}
    return jsonify(post_job_and_mark("input_click", x=data.get("x"), y=data.get("y"), type=data.get("type", "click")))


# -----------------------------------------------------------------------------
# TEMPLATES — visual language is taken from z15.7.3.py
# -----------------------------------------------------------------------------
BASE_STYLE = r"""
<style>
:root{
  --neon: {{ neon }};
  --muted: {{ muted }};
  --bg:#05060d;
  --panel:rgba(0,0,0,.35);
  --border:rgba(255,255,255,.08);
}
html,body{height:100%;overflow-y:auto}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--neon);font-family:Inter,Segoe UI,Arial}
textarea{width:100%;background:#000;color:var(--neon);border:1px solid var(--border);border-radius:6px}
a{color:var(--neon);text-decoration:none}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.65);opacity:0;pointer-events:none;transition:.2s;z-index:90}
.overlay.show{opacity:1;pointer-events:auto}
.top-panel{position:fixed;top:0;left:0;width:100%;height:90px;background:rgba(0,0,0,.9);transform:translateY(-100%);transition:.25s;z-index:100;display:flex;align-items:center;justify-content:center;gap:14px}
.top-panel.open{transform:translateY(0)}
.sidebar{position:fixed;top:0;left:0;width:260px;height:100vh;background:rgba(0,0,0,.92);transform:translateX(-100%);transition:.25s;z-index:100;padding:16px}
.sidebar.open{transform:translateX(0)}
.nav a{display:block;padding:10px;margin-bottom:8px;border-radius:8px;border:1px solid var(--border);color:var(--neon);text-decoration:none}
.nav a:hover,.nav a.active{background:rgba(0,255,208,.08);border-color:var(--neon)}
.layout{display:grid;grid-template-columns:1fr 340px;min-height:100vh}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:14px}
.btn{border:1px solid var(--neon);background:transparent;color:var(--neon);padding:8px 14px;border-radius:8px;cursor:pointer}
.btn:hover{background:var(--neon);color:#000;box-shadow:0 0 14px rgba(0,255,208,.15)}
.btn.danger{border-color:#ef4444;color:#ff8b8b}
.theme-btn{border:1px solid var(--border);background:transparent;color:var(--neon);padding:6px 10px;border-radius:6px;margin:2px;cursor:pointer}
.main{padding:14px;overflow:auto}
.right{padding:14px;border-left:1px solid var(--border)}
img.screen{width:100%;border-radius:8px;background:#000;display:block;object-fit:contain;min-height:220px}
.stat-header{display:flex;justify-content:space-between;margin-bottom:6px;font-weight:600}
.bar{height:10px;background:#111;border-radius:6px;overflow:hidden;margin-bottom:6px}
.bar div{height:100%;width:0%;background:var(--neon);transition:width .15s linear}
.client-row{padding:9px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px}
.client-row.selected{border-color:var(--neon);box-shadow:0 0 10px rgba(0,255,208,.12)}
.badge{display:inline-flex;align-items:center;gap:7px;padding:4px 9px;border-radius:999px;font-size:12px;border:1px solid rgba(0,255,208,.2);color:var(--neon);background:rgba(0,255,208,.06)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--neon);box-shadow:0 0 9px var(--neon)}
.dot.off{background:#ef4444;box-shadow:0 0 9px #ef4444}
.small{color:#8aa;font-size:12px}
.muted{color:#94a3b8}
pre{white-space:pre-wrap;word-break:break-word;background:#020617;color:var(--neon);border:1px solid var(--border);padding:12px;border-radius:8px}
input,select{width:100%;padding:10px;background:#020617;color:var(--neon);border:1px solid var(--border);border-radius:6px;margin:5px 0}
.shell-switch{display:flex;gap:8px;margin-top:6px}.shell-switch button{flex:1;padding:6px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--neon)}.shell-switch button.active{background:var(--neon);color:#000}
.right-panel{overflow:visible;position:fixed;top:0;right:-260px;width:260px;height:100vh;background:#0f172a;border-left:1px solid #334155;padding:12px;transition:right .3s ease;z-index:9999;display:flex;flex-direction:column}
.right-panel:before{content:"";position:absolute;left:-20px;top:0;width:20px;height:100%}.right-panel:hover{right:0}.right-panel-content{overflow-y:auto;flex:1;display:flex;flex-direction:column;gap:10px}
@media(max-width:1000px){.layout{grid-template-columns:1fr}}@media(max-width:780px){.sidebar{position:static;width:auto;height:auto;transform:none;border-bottom:1px solid var(--border)}.layout{display:block}.right{border-left:0}}
</style>
"""


SIDEBAR = r"""
<div class="sidebar" id="sidebar">
  <div class="nav">
    <a href="{{ url_for('index') }}">🏠 Головна</a>
    <a href="{{ url_for('files_page') }}">📁 File System</a>
    <a href="{{ url_for('camera_page') }}">📷 Camera</a>
    <a href="{{ url_for('fullscreen_page') }}">🖥 Fullscreen</a>
    <a href="{{ url_for('remote_page') }}">🎮 Remote</a>
    <a href="{{ url_for('notifications_page') }}">🔔 Notifications</a>
    <a href="{{ url_for('messages_page') }}">✉ Messages</a>
    <a href="{{ url_for('chat_page') }}">💬 Chat</a>
    {% if username == admin_username %}
      <a href="{{ url_for('admin_users') }}">👥 Users</a>
    {% endif %}
  </div>
  <div class="card">
    {% for t in themes_list %}
      <button class="theme-btn" onclick="applyTheme('{{ t }}')">{{ t }}</button>
    {% endfor %}
  </div>
  <div class="card">
    <div><b>SESSION</b></div>
    <div class="small" style="margin-top:8px">{{ username }}</div>
    <a class="btn danger" style="display:inline-block;margin-top:8px" href="{{ url_for('logout') }}">🚪 Logout</a>
  </div>
</div>
"""


LOGIN_TEMPLATE = r"""
<!doctype html><html><head><meta charset="utf-8"><title>Login — Neon Remote</title>
<style>
body{background:#06060b;color:#0ff;font-family:Inter,Arial;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.box{background:#0b0b12;padding:30px;border-radius:12px;box-shadow:0 0 40px #00ffd0;width:420px}
input{display:block;margin:10px 0;padding:10px;border-radius:6px;border:1px solid #00ffd0;background:#071018;color:#0ff;width:100%;box-sizing:border-box}
button{padding:10px 16px;border-radius:6px;border:1px solid #00ffd0;background:#001a1a;color:#0ff;cursor:pointer;width:100%}
.small{color:#8ff;font-size:13px}.title{font-weight:700;margin-bottom:8px}.msg{color:#f88;margin-bottom:8px}
</style></head><body><div class="box"><div class="title">Neon Remote — Login</div><div class="small">Authenticated controller</div>{% if msg %}<div class="msg">{{msg}}</div>{% endif %}<form method="POST"><input name="username" placeholder="Username"><input name="password" type="password" placeholder="Password"><button>Увійти</button></form><div class="small" style="margin-top:8px">Admin: {{ admin }}</div></div></body></html>
"""


MAIN_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="overlay" id="overlay" onclick="closeAll()"></div>
<div class="top-panel" id="topPanel">
  <a class="btn" href="{{ url_for('index') }}">🏠 Головна</a>
  {% if selected_cid %}<a class="btn" href="{{ url_for('fullscreen_page') }}">🖥 Fullscreen</a>{% endif %}
  <a class="btn danger" href="{{ url_for('logout') }}">🚪 Logout</a>
</div>

<div class="layout">
  <div class="main">
    <div class="card" style="display:flex;justify-content:space-between;align-items:center;gap:12px">
      <div>
        <b>Neon Remote</b><div class="small">z15 visual mode • z16 protocol</div>
      </div>
      <button class="btn" onclick="toggleSidebar()">☰ Menu</button>
    </div>

    {% if flashes %}<div class="card">{% for f in flashes %}<div>{{ f }}</div>{% endfor %}</div>{% endif %}

    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
        <b>🖥 {{ selected.name if selected else 'No client connected' }}</b>
        {% if selected %}<span class="badge"><span class="dot"></span> Online</span>{% endif %}
      </div>
      {% if selected %}
        <div class="small" style="margin-top:5px">ID: {{ selected_cid }} · {{ selected.ip }}</div>
        <img src="{{ url_for('screen_feed') }}" class="screen" id="mainScreen" style="margin-top:10px" alt="screen">
      {% else %}
        <div class="muted" style="padding:30px 4px">Запусти z16.py і перевір REMOTE_CLIENT_TOKEN.</div>
      {% endif %}
    </div>

    {% if selected %}
    <div class="card">
      <b>Command</b>
      <textarea id="cmd" rows="6" placeholder="systeminfo / whoami / ..."></textarea>
      <div class="shell-switch"><button class="active" type="button">CMD</button><button type="button" onclick="flashInfo('z16 executes shell commands only when ALLOW_REMOTE_CMD=1')">PowerShell</button></div>
      <button class="btn" style="margin-top:8px" onclick="runCommand()">Run</button>
      <pre id="cmdOut">{{ cmd_output or '—' }}</pre>
    </div>

    <div class="card">
      <b>🔊 Гучність</b>
      <div style="display:flex;align-items:center;gap:12px;margin-top:10px"><input type="range" min="0" max="100" value="50" id="volumeSlider" style="flex:1;margin:0"><span id="volumeVal">50%</span></div>
      <div class="small" style="margin-top:8px">У поточному z16.py немає volume job, тому повзунок лишений у стилі z15 і не відправляє команду.</div>
    </div>
    {% endif %}
  </div>

  <div class="right">
    <div class="card">
      <div class="stat-header">CPU <span id="cpuVal">{{ selected.cpu if selected and selected.cpu is not none else '—' }}{% if selected and selected.cpu is not none %}%{% endif %}</span></div>
      <div class="bar"><div id="cpuBar" style="width:{{ selected.cpu if selected and selected.cpu is not none else 0 }}%"></div></div>
      <div class="small">Telemetry is optional; current z16.py does not send CPU/RAM by default.</div>
    </div>
    <div class="card">
      <div class="stat-header">RAM <span id="ramVal">{{ selected.ram if selected and selected.ram is not none else '—' }}{% if selected and selected.ram is not none %}%{% endif %}</span></div>
      <div class="bar"><div id="ramBar" style="width:{{ selected.ram if selected and selected.ram is not none else 0 }}%"></div></div>
    </div>

    <div class="card">
      <b>💻 Clients</b>
      <div style="margin-top:10px">
      {% for pc in pc_list %}
        <div class="client-row {{ 'selected' if pc.id == selected_cid else '' }}">
          <div style="display:flex;justify-content:space-between;gap:8px"><b>{{ pc.name }}</b><span class="badge"><span class="dot {{ '' if pc.online else 'off' }}"></span>{{ 'Online' if pc.online else 'Offline' }}</span></div>
          <div class="small">{{ pc.ip }} · {{ pc.id }}</div>
          <div class="small">Caps: {{ ', '.join(pc.caps) or '—' }}</div>
          {% if pc.online %}<form method="POST" action="{{ url_for('select_client_route') }}" style="margin-top:7px"><input type="hidden" name="cid" value="{{ pc.id }}"><input type="hidden" name="next" value="{{ url_for('index') }}"><button class="btn" type="submit">Select</button></form>{% endif %}
        </div>
      {% else %}
        <div class="small">No z16 clients online.</div>
      {% endfor %}
      </div>
    </div>
  </div>
</div>

<script>
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open')}
function closeAll(){document.getElementById('sidebar').classList.remove('open');document.getElementById('overlay').classList.remove('show')}
function flashInfo(s){document.getElementById('cmdOut').textContent=s}
async function applyTheme(theme){
  const r=await fetch('{{ url_for('set_theme') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme})});
  if(r.ok) location.reload();
}
const slider=document.getElementById('volumeSlider');
if(slider){slider.addEventListener('input',()=>document.getElementById('volumeVal').textContent=slider.value+'%')}
async function runCommand(){
  const out=document.getElementById('cmdOut'); const cmd=document.getElementById('cmd').value.trim(); if(!cmd)return;
  out.textContent='⏳ sending...';
  const r=await fetch('{{ url_for('api_command') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});
  const q=await r.json(); if(!q.ok){out.textContent=q.error||'error';return}
  for(let i=0;i<80;i++){
    const s=await fetch('{{ url_for('job_status', job_id='JOB') }}'.replace('JOB',q.job_id)); const d=await s.json();
    if(d.done){out.textContent=d.result.output||d.result.error||'—';return}
    await new Promise(x=>setTimeout(x,500));
  }
  out.textContent='job timeout';
}
</script>
"""


REMOTE_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main">
  <div class="card"><b>🎮 Remote — {{ pc_name }}</b><div class="small">{{ cid }}</div></div>
  <div class="card"><img id="screen" class="screen" src="{{ url_for('screen_feed') }}"><div class="small" style="margin-top:8px">Click coordinates are converted from the displayed image to the client screen.</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><button class="btn" onclick="sendClick('click')">Left Click</button><button class="btn" onclick="sendClick('double')">Double</button><button class="btn" onclick="sendClick('right')">Right</button><button class="btn" onclick="browserFullscreen()">Fullscreen</button></div>
    <div class="client-row" style="margin-top:12px"><b>Keyboard events</b><div class="small">Only when client ALLOW_REMOTE_INPUT=1.</div><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
      <button class="btn" onclick="sendKey('enter')">Enter</button><button class="btn" onclick="sendKey('esc')">Esc</button><button class="btn" onclick="sendKey('tab')">Tab</button><button class="btn" onclick="sendKey('backspace')">Backspace</button><button class="btn" onclick="sendKey('left')">←</button><button class="btn" onclick="sendKey('right')">→</button><button class="btn" onclick="sendKey('up')">↑</button><button class="btn" onclick="sendKey('down')">↓</button><button class="btn" onclick="sendKey('c',['ctrl'])">Ctrl+C</button><button class="btn" onclick="sendKey('v',['ctrl'])">Ctrl+V</button><button class="btn" onclick="sendKey('a',['ctrl'])">Ctrl+A</button>
    </div></div>
    <textarea id="typebox" rows="5" style="margin-top:10px" placeholder="Text to type on the client"></textarea><button class="btn" style="margin-top:8px" onclick="sendText()">Send Text</button><button class="btn" style="margin-top:8px" onclick="sendDemoBeep()">🔊 Demo beep</button><div id="status" class="small" style="margin-top:8px">Ready</div>
  </div>
</div><div class="right"><div class="card"><b>Actions</b><div class="small" style="margin-top:8px">Use z15 layout with z16 jobs.</div></div></div></div>
<script>
function browserFullscreen(){const el=document.getElementById('screen');if(el.requestFullscreen)el.requestFullscreen()}
async function sendClick(type){const img=document.getElementById('screen'),r=img.getBoundingClientRect();const sx=img.naturalWidth||r.width,sy=img.naturalHeight||r.height;const x=Math.max(0,Math.min(sx-1,Math.round((event.clientX-r.left)*(sx/r.width))));const y=Math.max(0,Math.min(sy-1,Math.round((event.clientY-r.top)*(sy/r.height))));document.getElementById('status').textContent='⏳ sending...';const q=await fetch('{{ url_for('api_input_click') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,type})});const d=await q.json();document.getElementById('status').textContent=d.ok?'✅ sent':(d.error||'error')}
async function sendText(){const text=document.getElementById('typebox').value;const r=await fetch('{{ url_for('api_input_type') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});const d=await r.json();document.getElementById('status').textContent=d.ok?'✅ sent':(d.error||'error')}
async function sendKey(key,modifiers=[]){const r=await fetch('{{ url_for('api_input_key') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,modifiers})});const d=await r.json();document.getElementById('status').textContent=d.ok?'⌨ sent':(d.error||'error')}
async function sendDemoBeep(){const r=await fetch('{{ url_for('api_demo_prank') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({effect:'beep'})});const d=await r.json();if(!d.ok){document.getElementById('status').textContent=d.error||'error';return}document.getElementById('status').textContent='🔊 demo queued'}
</script>
"""


CAMERA_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main"><div class="card"><b>📷 Camera — {{ pc_name }}</b><div class="small">{{ cid }}</div></div><div class="card"><img class="screen" src="{{ url_for('camera_feed') }}"><div style="margin-top:10px"><button class="btn" id="photo">📸 Take photo</button></div><div id="status" class="small" style="margin-top:8px">Ready</div><img id="photoOut" class="screen" style="display:none;margin-top:10px"><a id="download" class="btn" style="display:none;margin-top:8px" download>Download</a></div></div><div class="right"><div class="card"><b>Camera</b><div class="small" style="margin-top:8px">Stream is active while this page is open.</div></div></div></div>
<script>
async function waitJob(jobId){for(let i=0;i<80;i++){const r=await fetch('{{ url_for('job_status', job_id='JOB') }}'.replace('JOB',jobId));const d=await r.json();if(d.done)return d.result;await new Promise(x=>setTimeout(x,500))}return {ok:false,error:'job timeout'}}
document.getElementById('photo').onclick=async()=>{const st=document.getElementById('status');st.textContent='⏳ Capturing...';const r=await fetch('{{ url_for('api_camera_photo') }}',{method:'POST'});const q=await r.json();if(!q.ok){st.textContent=q.error||'error';return}const res=await waitJob(q.job_id);if(!res.ok){st.textContent=res.error||'error';return}const bytes=Uint8Array.from(atob(res.data_b64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));document.getElementById('photoOut').src=url;document.getElementById('photoOut').style.display='block';const dl=document.getElementById('download');dl.href=url;dl.style.display='inline-block';st.textContent='✅ Done'}
</script>
"""


FILES_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main"><div class="card"><b>📁 File System — {{ pc_name }}</b><div class="small">Path: {{ current_path }}</div><div class="small" style="margin-top:6px">Browse only explicitly configured roots on the client.</div></div><div class="card"><button class="btn" onclick="refreshFs()">Refresh</button> <input id="path" value="{{ selected_path }}" placeholder="root/path (example: home/Documents)"><div id="fs" style="margin-top:10px">Loading...</div></div></div><div class="right"><div class="card"><b>Filesystem roots</b><div class="small" style="margin-top:8px">The client advertises the roots it has explicitly configured.</div></div></div></div>
<script>
async function waitJob(jobId){for(let i=0;i<80;i++){const r=await fetch('{{ url_for('job_status', job_id='JOB') }}'.replace('JOB',jobId));const d=await r.json();if(d.done)return d.result;await new Promise(x=>setTimeout(x,250))}return {ok:false,error:'job timeout'}}
async function refreshFs(){const q=await fetch('{{ url_for('api_fs_list') }}?path='+encodeURIComponent(document.getElementById('path').value));const d=await q.json();if(!d.ok){document.getElementById('fs').textContent=d.error||'error';return}const res=await waitJob(d.job_id);if(!res.ok){document.getElementById('fs').textContent=res.error||'error';return}let html='';for(const f of res.items||[]){html+=`<div class="client-row"><b>${f.is_dir?'📂':'📄'} ${escapeHtml(f.name)}</b><div class="small">${f.size??''} ${f.mtime||''}</div></div>`}document.getElementById('fs').innerHTML=html||'<div class="small">Empty folder</div>'}
function escapeHtml(s){return String(s).replace(/[&<>\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[m]))}
refreshFs();
</script>
"""


ADMIN_USERS_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main"><div class="card"><b>👥 Users</b></div><div class="card"><div style="display:flex;gap:8px"><button class="btn" onclick="show('view')">View</button><button class="btn" onclick="show('create')">Create</button><button class="btn" onclick="show('update')">Update</button><button class="btn danger" onclick="show('delete')">Delete</button></div></div><div class="card" id="view"><h3>Selected user</h3><div id="viewName" class="small">—</div>{% for u,v in users.items() %}<div class="client-row" onclick="selectUser('{{ u }}')"><b>{{ u }}</b><div class="small">perms: {{ v.permissions }}</div></div>{% endfor %}</div><div class="card" id="create" style="display:none"><h3>Create user</h3><form method="POST"><input name="username" placeholder="Username"><input name="password" placeholder="Password"><input name="permissions" placeholder="screen,files,camera,remote,commands,chat"><button class="btn" name="action" value="create">Create</button></form></div><div class="card" id="update" style="display:none"><h3>Update user</h3><form method="POST"><input id="u_update" name="username_update" placeholder="Username"><input name="password_update" placeholder="New password"><input name="permissions_update" placeholder="screen,files,camera,remote,commands,chat"><button class="btn" name="action" value="update">Update</button></form></div><div class="card" id="delete" style="display:none"><h3>Delete user</h3><form method="POST"><input id="u_delete" name="username_del" placeholder="Username"><button class="btn danger" name="action" value="delete">Delete</button></form></div></div><div class="right"><div class="card"><b>Account</b><div class="small" style="margin-top:8px">{{ username }}</div></div></div></div>
<script>function show(id){for(const x of ['view','create','update','delete'])document.getElementById(x).style.display=x===id?'block':'none'}function selectUser(u){document.getElementById('viewName').textContent=u;document.getElementById('u_update').value=u;document.getElementById('u_delete').value=u}async function applyTheme(theme){const r=await fetch('{{ url_for('set_theme') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme})});if(r.ok)location.reload()}</script>
"""


NOTIFS_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main"><div class="card"><b>🔔 Notifications for {{ username }}</b></div>{% for n in notifs %}<div class="card"><b>{{ n.ts }}</b> — {{ n.title }}<div class="small" style="margin-top:6px">{{ n.message }}</div></div>{% else %}<div class="card">No notifications</div>{% endfor %}</div><div class="right"></div></div>
<script>async function applyTheme(theme){const r=await fetch('{{ url_for('set_theme') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme})});if(r.ok)location.reload()}</script>
"""


MESSAGES_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main"><div class="card"><b>✉ Messages</b></div><div class="card"><form method="POST"><select name="to">{% for u in users %}<option>{{u}}</option>{% endfor %}</select><textarea name="msg" rows="5" placeholder="Message"></textarea><button class="btn" type="submit">Send</button></form></div>{% for m in messages %}<div class="card"><b>{{ m.ts }}</b> · {{ m.from }}<div style="margin-top:6px">{{ m.msg }}</div></div>{% else %}<div class="card">No messages</div>{% endfor %}</div><div class="right"></div></div>
<script>async function applyTheme(theme){const r=await fetch('{{ url_for('set_theme') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme})});if(r.ok)location.reload()}</script>
"""


CHAT_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main"><div class="card"><b>💬 Chat</b></div><div class="card"><form method="POST"><textarea name="msg" rows="4" placeholder="Message"></textarea><button class="btn" type="submit">Send</button></form></div><div class="card">{% for m in chat %}<div style="padding:7px 0;border-bottom:1px dashed var(--border)"><b>{{ m.user }}</b> <span class="small">{{ m.ts }}</span><div style="margin-top:4px">{{ m.msg }}</div></div>{% else %}<div class="small">No messages</div>{% endfor %}</div></div><div class="right"></div></div>
<script>async function applyTheme(theme){const r=await fetch('{{ url_for('set_theme') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme})});if(r.ok)location.reload()}</script>
"""


FULLSCREEN_TEMPLATE = BASE_STYLE + r"""
<!doctype html><html><head><meta charset="utf-8"><title>Fullscreen — {{ pc_name }}</title></head><body>
<div style="padding:14px"><div class="card"><b>🖥 Fullscreen — {{ pc_name }}</b><span class="small">{{ cid }}</span><div style="margin-top:10px"><button class="btn" onclick="enterFs()">Enter browser fullscreen</button> <a class="btn" href="{{ url_for('index') }}">← Back</a></div></div>
<div class="card" style="padding:6px"><img id="screen" class="screen" src="{{ url_for('screen_feed') }}" alt="screen"></div><div id="status" class="small">Ready</div></div>
<script>
function enterFs(){const e=document.getElementById('screen');if(e.requestFullscreen)e.requestFullscreen()}
async function clickAt(ev,type){const img=document.getElementById('screen');const r=img.getBoundingClientRect();const sx=img.naturalWidth||r.width,sy=img.naturalHeight||r.height;const x=Math.round((ev.clientX-r.left)*sx/r.width),y=Math.round((ev.clientY-r.top)*sy/r.height);const q=await fetch('{{ url_for('fullscreen_click') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,type})});const d=await q.json();document.getElementById('status').textContent=d.ok?'✅ sent':(d.error||'error')}
document.getElementById('screen').addEventListener('click',e=>clickAt(e,'click'));document.getElementById('screen').addEventListener('dblclick',e=>clickAt(e,'double'));
</script></body></html>
"""



# =============================================================================
# z15 EXACT-STYLE COMPATIBILITY LAYER
# The templates below are taken from z15.7.3.py; only backend endpoint shims
# are added so the UI talks to the z16 remote client instead of the local host.
# =============================================================================

TROLLS = {
    "block": {"short": "Блок вводу", "long": "Повністю блокує мишку та клавіатуру на заданий час"},
    "mouse": {"short": "Миша хаос", "long": "Міняє місцями кнопки миші, ускладнюючи керування"},
    "disco": {"short": "Диско вікон", "long": "Вікна хаотично відкриваються, закриваються та рухаються"},
    "beep": {"short": "Системні біпи", "long": "Програє випадкові системні звукові сигнали"},
    "shake": {"short": "Тряска вікна", "long": "Активне вікно починає різко трястися"},
    "invert": {"short": "Інверсія", "long": "Інвертує кольори екрана, створюючи ефект зламаного дисплея"},
    "drift": {"short": "Знос миші", "long": "Курсор повільно самовільно відхиляється в різні сторони"},
    "minall": {"short": "Згорнути все", "long": "Миттєво згортає всі відкриті вікна"},
    "altab": {"short": "Alt+Tab", "long": "Хаотично перемикає активні вікна між програмами"},
    "notify": {"short": "Фейк повідомлення", "long": "Показує фальшиве системне повідомлення"},
    "scroll": {"short": "Реверс скролу", "long": "Інвертує напрямок прокрутки коліщатка миші"},
    "type": {"short": "Фейк друк", "long": "Система сама вводить випадковий текст"},
    "freeze": {"short": "Фріз", "long": "Імітує зависання вікон без реального краху"},
    "blink": {"short": "Блимання", "long": "Екран коротко блимає чорним кольором"},
    "volume": {"short": "Гучність хаос", "long": "Різко змінює рівень системної гучності"},
    "usb": {"short": "USB звук", "long": "Відтворює звук підключення та відключення USB"},
    "focus": {"short": "Крадіжка фокусу", "long": "Постійно перехоплює фокус активного вікна"},
    "task": {"short": "Панель задач", "long": "Ховає та показує панель задач Windows"},
    "cursor": {"short": "Курсор хаос", "long": "Різко змінює позицію курсора"},
    "almost": {"short": "Майже нічого", "long": "Створює відчуття, що щось зламалось… але ні 😈"},
}

# Exact z15 templates.
MAIN_TEMPLATE = '\n<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n<title>Neon Remote</title>\n\n<style>\n:root{\n  --neon: {{ neon }};\n  --muted: {{ muted }};\n  --bg:#05060d;\n  --panel:rgba(0,0,0,.35);\n  --border:rgba(255,255,255,.08);\n}\nhtml, body {\n  height: 100%;\n  overflow-y: auto;\n}\n/* права панель */\n.right-panel {\n  overflow: visible;\n  position: fixed;\n  top: 0;\n  right: -260px;              /* СХОВАНА */\n  width: 260px;\n  height: 100vh;\n  background: #0f172a;\n  border-left: 1px solid #334155;\n  padding: 12px;\n  transition: right 0.3s ease;\n  z-index: 9999;\n\n  display: flex;\n  flex-direction: column;\n}\n\n/* зона наведення */\n.right-panel::before {\n  content: "";\n  position: absolute;\n  left: -20px;\n  top: 0;\n  width: 20px;\n  height: 100%;\n}\n\n/* коли наводиш — виїжджає */\n.right-panel:hover {\n  right: 0;\n}\n\n/* скрол всередині */\n.right-panel-content {\n  overflow: visible;\n\n  overflow-y: auto;\n  flex: 1;\n  display: flex;\n  flex-direction: column;\n  gap: 10px;\n}\n\n*{box-sizing:border-box}\nbody{\n  margin:0;\n  background:var(--bg);\n  color:var(--neon);\n  font-family:Inter,Segoe UI,Arial;\n}\n\ntextarea{width:100%;background:#000;color:var(--neon);border:1px solid var(--border);border-radius:6px}\n\n/* ===== OVERLAY ===== */\n.overlay{\n  position:fixed;\n  inset:0;\n  background:rgba(0,0,0,.65);\n  opacity:0;\n  pointer-events:none;\n  transition:.2s;\n  z-index:90;\n}\n.overlay.show{opacity:1;pointer-events:auto}\n\n/* ===== TOP PANEL ===== */\n.top-panel{\n  position:fixed;\n  top:0;left:0;\n  width:100%;height:90px;\n  background:rgba(0,0,0,.9);\n  transform:translateY(-100%);\n  transition:.25s;\n  z-index:100;\n  display:flex;\n  align-items:center;\n  justify-content:center;\n  gap:14px;\n}\n.top-panel.open{transform:translateY(0)}\n.troll-btn {\n  padding: 10px 16px;\n  border-radius: 10px;\n  background: #1f2937;\n  color: #fff;\n  border: 1px solid #374151;\n  cursor: pointer;\n}\n.troll-btn.active {\n  background: #dc2626;\n}\n\n/* ===== SIDEBAR ===== */\n.sidebar{\n  position:fixed;\n  top:0;left:0;\n  width:260px;height:100vh;\n  background:rgba(0,0,0,.92);\n  transform:translateX(-100%);\n  transition:.25s;\n  z-index:100;\n  padding:16px;\n}\n.sidebar.open{transform:translateX(0)}\n\n.nav a{\n  display:block;\n  padding:10px;\n  margin-bottom:8px;\n  border-radius:8px;\n  border:1px solid var(--border);\n  color:var(--neon);\n  text-decoration:none;\n}\n.troll-btn.active {\n  background: linear-gradient(135deg, #dc2626, #ef4444);\n}\n\n/* ===== LAYOUT ===== */\n.layout{\n  display:grid;\n  grid-template-columns:1fr 340px;\n  height:100vh;\n}\n\n.card{\n  background:var(--panel);\n  border:1px solid var(--border);\n  border-radius:10px;\n  padding:12px;\n  margin-bottom:14px;\n}\n\n.btn{\n  border:1px solid var(--neon);\n  background:transparent;\n  color:var(--neon);\n  padding:8px 14px;\n  border-radius:8px;\n  cursor:pointer;\n}\n\n.theme-btn{\n  border:1px solid var(--border);\n  background:transparent;\n  color:var(--neon);\n  padding:6px 10px;\n  border-radius:6px;\n  margin:2px;\n}\n\n.main{padding:14px;overflow:auto}\n.right{padding:14px;border-left:1px solid var(--border)}\n\nimg.screen{width:100%;border-radius:8px}\n\n/* ===== STAT ===== */\n.stat-header{\n  display:flex;\n  justify-content:space-between;\n  margin-bottom:6px;\n  font-weight:600;\n}\n\n.bar{\n  height:10px;\n  background:#111;\n  border-radius:6px;\n  overflow:hidden;\n  margin-bottom:6px;\n}\n.bar div{\n  height:100%;\n  width:0%;\n  background:var(--neon);\n  transition:width .15s linear;\n}\n\ncanvas{\n  width:100%;\n  height:60px;\n}\n\n/* ===== SHELL ===== */\n.shell-switch{\n  display:flex;\n  gap:8px;\n  margin-top:6px;\n}\n.shell-switch button{\n  flex:1;\n  padding:6px;\n  border-radius:6px;\n  border:1px solid var(--border);\n  background:transparent;\n  color:var(--neon);\n}\n.shell-switch button.active{\n  background:var(--neon);\n  color:#000;\n}\n.troll-panel {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 10px;\n  margin-top: 10px;\n}\n\n.troll-btn {\n  background: linear-gradient(135deg, #2b2f3a, #1c1f27);\n  color: #fff;\n  border: 1px solid #3a3f4b;\n  padding: 10px 16px;\n  border-radius: 10px;\n  font-size: 14px;\n  cursor: pointer;\n  transition: all 0.2s ease;\n  box-shadow: 0 4px 12px rgba(0,0,0,0.3);\n}\n\n.troll-btn:hover {\n  transform: translateY(-2px);\n  box-shadow: 0 6px 18px rgba(0,0,0,0.5);\n  background: linear-gradient(135deg, #3b82f6, #2563eb);\n}\n\n.troll-btn:active {\n  transform: scale(0.97);\n}\n\n.troll-btn.danger {\n  background: linear-gradient(135deg, #7f1d1d, #991b1b);\n  border-color: #ef4444;\n}\n\n.troll-btn.danger:hover {\n  background: linear-gradient(135deg, #dc2626, #ef4444);\n}\n\n.troll-input {\n  background: #111827;\n  color: #fff;\n  border: 1px solid #374151;\n  border-radius: 8px;\n  padding: 8px;\n  width: 80px;\n}\n.troll-btn {\n  position: relative;\n}\n\n.troll-desc {\n  position: absolute;\n  top: 50%;\n  right: 100%;\n  transform: translateY(-50%) translateX(10px);\n\n  width: 220px;\n\n  background: #020617;\n  color: #e5e7eb;\n  border: 1px solid #334155;\n  border-radius: 8px;\n  padding: 10px;\n\n  font-size: 13px;\n  line-height: 1.4;\n\n  opacity: 0;\n  pointer-events: none;\n\n  transition: all 0.25s ease;\n  z-index: 10000;\n}\n\ninput[type=range] {\n  -webkit-appearance: none;\n  height: 6px;\n  background: #1f2937;\n  border-radius: 6px;\n  outline: none;\n}\n\ninput[type=range]::-webkit-slider-thumb {\n  -webkit-appearance: none;\n  width: 16px;\n  height: 16px;\n  border-radius: 50%;\n  background: var(--neon);\n  cursor: pointer;\n  box-shadow: 0 0 10px var(--neon);\n}\n\n</style>\n</head>\n\n<body>\n\n<div class="overlay" id="overlay" onclick="closeAll()"></div>\n\n<div class="top-panel" id="topPanel">\n  <form method="POST" action="{{ url_for(\'sys_action\') }}">\n\n    <button class="btn" name="action" value="shutdown">❌ Вимкнути</button>\n    <button class="btn" name="action" value="restart">🔄 Перезавантажити</button>\n    <button class="btn" name="action" value="sleep">💤 Сон</button>\n    <button class="btn" name="action" value="logout">🚪 Вийти</button>\n    <a href="{{ url_for(\'logout\') }}" class="btn">🚪 Logout</a>\n\n  </form>\n</div>\n\n<div class="sidebar" id="sidebar">\n  <div class="nav">\n    <a href="{{ url_for(\'files_navigate\', path=\'\') }}">📁 File System</a>\n    <a href="{{ url_for(\'camera_page\') }}">📷 Camera</a>\n    <a href="{{ url_for(\'fullscreen_page\') }}">🖥 Fullscreen</a>\n    <a href="{{ url_for(\'remote_page\') }}">🎮 Remote</a>\n    <a href="{{ url_for(\'notifications_page\') }}">🔔 Notifications</a>\n    <a href="{{ url_for(\'messages_page\') }}">✉ Messages</a>\n    <a href="{{ url_for(\'chat_page\') }}">💬 Chat</a>\n    <a href="/processes">⚙ Процеси</a>\n\n  </div>\n\n  <div class="card">\n    {% for t in themes_list %}\n      <button class="theme-btn" onclick="applyTheme(\'{{ t }}\')">{{ t }}</button>\n    {% endfor %}\n  </div>\n\n  {% if username == admin_username %}\n  <div class="card">\n    <b>Admin</b><br><br>\n    <a class="btn" href="{{ url_for(\'admin_users\') }}">👥 Users</a><br><br>\n    <a class="btn" href="{{ url_for(\'admin_export\') }}">📦 Export ZIP</a>\n  </div>\n  {% endif %}\n</div>\n\n<div class="layout">\n  <div class="main">\n    <div class="card">\n      <img src="{{ url_for(\'screen_feed\') }}" class="screen">\n    </div>\n\n    <div class="card">\n      <b>Command</b>\n      <form method="POST" action="{{ url_for(\'run_cmd_route\') }}">\n        <textarea name="cmd"></textarea>\n        <input type="hidden" name="shell" id="shellInput" value="cmd">\n\n        <div class="shell-switch">\n          <button type="button" onclick="setShell(\'cmd\',this)" class="active">CMD</button>\n          <button type="button" onclick="setShell(\'powershell\',this)">PowerShell</button>\n        </div>\n\n        <button class="btn" style="margin-top:8px">Run</button>\n      </form>\n      <pre>{{ cmd_output or "—" }}</pre>\n    </div>\n    <div class="card">\n  <b>🔊 Гучність</b>\n\n  <div style="display:flex; align-items:center; gap:12px; margin-top:10px;">\n    <input\n      type="range"\n      min="0"\n      max="100"\n      value="50"\n      id="volumeSlider"\n      style="flex:1;"\n    >\n    <span id="volumeVal">50%</span>\n  </div>\n</div>\n\n  </div>\n\n  <div class="right">\n    <div class="card">\n      <div class="stat-header">\n        CPU <span id="cpuVal">{{ cpu }}%</span>\n      </div>\n      <div class="bar"><div id="cpuBar"></div></div>\n      <canvas id="cpuChart" width="320" height="60"></canvas>\n    </div>\n\n    <div class="card">\n      <div class="stat-header">\n        RAM <span id="ramVal">{{ ram }}%</span>\n      </div>\n      <div class="bar"><div id="ramBar"></div></div>\n      <canvas id="ramChart" width="320" height="60"></canvas>\n      \n    \n  </div>\n  <div class="right-panel">\n  <h3 style="color:#e5e7eb; margin-bottom:10px;">\n    🎭 Пранки\n  </h3>\n\n  <div class="right-panel-content">\n    {% for key, t in TROLLS.items() %}\n  <button class="troll-btn"\n          data-label="{{ t.short }}"\n          data-desc="{{ t.long }}"\n          onclick="runTroll(\'{{ key }}\', this)">\n    {{ t.short }}\n    <div class="troll-desc"></div>\n  </button>\n{% endfor %}\n\n  </div>\n</div>\n\n</div>\n<script>\ndocument.addEventListener("DOMContentLoaded", () => {\n  document.querySelectorAll(".troll-btn").forEach(btn => {\n\n    const shortText = btn.dataset.label;\n    const longText  = btn.dataset.desc;\n\n    btn.addEventListener("mouseenter", () => {\n      if (!btn.classList.contains("active")) {\n        btn.textContent = longText;\n      }\n    });\n\n    btn.addEventListener("mouseleave", () => {\n      if (!btn.classList.contains("active")) {\n        btn.textContent = shortText;\n      }\n    });\n\n  });\n});\n</script>\n\n<script>\nconst volSlider = document.getElementById("volumeSlider");\nconst volVal = document.getElementById("volumeVal");\n\n// завантажити поточну гучність\nfetch("/api/volume")\n  .then(r => r.json())\n  .then(d => {\n    volSlider.value = d.value;\n    volVal.textContent = d.value + "%";\n  });\n\n// міняти гучність при русі\nvolSlider.addEventListener("input", () => {\n  const v = volSlider.value;\n  volVal.textContent = v + "%";\n\n  fetch("/api/volume", {\n    method: "POST",\n    headers: {"Content-Type":"application/json"},\n    body: JSON.stringify({value: v})\n  });\n});\n\nconst overlay=document.getElementById(\'overlay\');\nconst sidebar=document.getElementById(\'sidebar\');\nconst topPanel=document.getElementById(\'topPanel\');\n\ndocument.addEventListener(\'mousemove\', e => {\n\n  /* ==== ВІДКРИТТЯ ==== */\n  if (e.clientX <= 4) {\n    sidebar.classList.add(\'open\');\n    overlay.classList.add(\'show\');\n  }\n\n  if (e.clientY <= 4) {\n    topPanel.classList.add(\'open\');\n    overlay.classList.add(\'show\');\n  }\n\n  /* ==== ЗАКРИТТЯ ==== */\n\n  // sidebar: якщо мишка ПРАВІШЕ панелі\n  if (\n    sidebar.classList.contains(\'open\') &&\n    e.clientX > sidebar.offsetWidth + 20\n  ) {\n    sidebar.classList.remove(\'open\');\n    overlay.classList.remove(\'show\');\n  }\n\n  // top-panel: якщо мишка НИЖЧЕ панелі\n  if (\n    topPanel.classList.contains(\'open\') &&\n    e.clientY > topPanel.offsetHeight + 20\n  ) {\n    topPanel.classList.remove(\'open\');\n    overlay.classList.remove(\'show\');\n  }\n\n});\n\nfunction closeAll(){\n  sidebar.classList.remove(\'open\');\n  topPanel.classList.remove(\'open\');\n  overlay.classList.remove(\'show\');\n}\n\nfunction applyTheme(t){\n  fetch("{{ url_for(\'set_theme\') }}",{method:"POST",headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({theme:t})});\n  document.documentElement.style.setProperty(\'--neon\',t);\n}\n\nfunction setShell(v,b){\n  shellInput.value=v;\n  document.querySelectorAll(\'.shell-switch button\').forEach(x=>x.classList.remove(\'active\'));\n  b.classList.add(\'active\');\n}\n\nconst cpuCtx=document.getElementById("cpuChart").getContext("2d");\nconst ramCtx=document.getElementById("ramChart").getContext("2d");\nconst cpuBar=document.getElementById("cpuBar");\nconst ramBar=document.getElementById("ramBar");\n\nlet cpuData=new Array(40).fill(0);\nlet ramData=new Array(40).fill(0);\n\nfunction draw(ctx,data){\n  ctx.clearRect(0,0,320,60);\n  ctx.beginPath();\n  ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue(\'--neon\');\n  data.forEach((v,i)=>{\n    const x=i*8;\n    const y=60-(v*0.6);\n    i?ctx.lineTo(x,y):ctx.moveTo(x,y);\n  });\n  ctx.stroke();\n}\n\nasync function update(){\n  const r=await fetch("/api/system",{cache:"no-store"});\n  if(!r.ok)return;\n  const d=await r.json();\n\n  cpuBar.style.width=d.cpu+"%";\n  ramBar.style.width=d.ram+"%";\n\n  cpuVal.innerText=d.cpu.toFixed(0)+"%";\n  ramVal.innerText=d.ram.toFixed(0)+"%";\n\n  cpuData.push(d.cpu);cpuData.shift();\n  ramData.push(d.ram);ramData.shift();\n\n  draw(cpuCtx,cpuData);\n  draw(ramCtx,ramData);\n}\n\nsetInterval(update,500);\nfunction startDisco(){\n  const sec = document.getElementById("discoSec").value;\n  fetch("/prank/disco?sec=" + sec);\n}\n</script>\n<script>\nlet trollHoverTimer = null;\n\ndocument.addEventListener("DOMContentLoaded", () => {\n  document.querySelectorAll(".troll-btn").forEach(btn => {\n\n    const desc = btn.querySelector(".troll-desc");\n\n    btn.addEventListener("mouseenter", () => {\n      trollHoverTimer = setTimeout(() => {\n        desc.textContent = btn.dataset.desc;\n        desc.style.opacity = "1";\n        desc.style.transform = "translateY(-50%) translateX(0)";\n\n      }, 3000); // 3 секунди\n    });\n\n    btn.addEventListener("mouseleave", () => {\n      clearTimeout(trollHoverTimer);\n      trollHoverTimer = null;\n\n      desc.style.opacity = "0";\n      desc.style.transform = "translateY(-50%) translateX(10px)";\n\n    });\n\n  });\n});\n</script>\n\n<script>\nfunction runTroll(action, btn) {\n\n  // если кнопка активна → СТОП, БЕЗ PROMPT\n  if (btn.classList.contains("active")) {\n    fetch("/api/troll/toggle", {\n      method: "POST",\n      headers: {"Content-Type":"application/json"},\n      body: JSON.stringify({effect: action})\n    }).then(()=>{\n      btn.classList.remove("active");\n      btn.textContent = btn.dataset.label;\n    });\n    return;\n  }\n\n  // иначе — запуск\n  let seconds = prompt("Сколько секунд?", "5");\n  if (!seconds) return;\n  seconds = parseInt(seconds);\n\n  fetch("/api/troll/toggle", {\n    method: "POST",\n    headers: {"Content-Type":"application/json"},\n    body: JSON.stringify({effect: action, seconds})\n  })\n  .then(r=>r.json())\n  .then(d=>{\n    if (!d.active) return;\n\n    btn.classList.add("active");\n    let left = seconds;\n    btn.textContent = `⏹ ${left}s`;\n\n    const iv = setInterval(()=>{\n      if (!btn.classList.contains("active")) {\n        clearInterval(iv);\n        return;\n      }\n      left--;\n      if (left <= 0) {\n        clearInterval(iv);\n        btn.classList.remove("active");\n        btn.textContent = btn.dataset.label;\n      } else {\n        btn.textContent = `⏹ ${left}s`;\n      }\n    }, 1000);\n  });\n}\n</script>\n\n\n\n\n</body>\n</html>\n'

FILES_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main">
  <div class="card"><b>📁 File System — {{ pc_name }}</b><div class="small">Path: {{ current_path }}</div><div class="small" style="margin-top:6px">Only client-configured filesystem roots are exposed.</div></div>
  <div class="card">
    <button class="btn" onclick="refreshFs()">Refresh</button>
    <button class="btn" onclick="goParent()">⬅ Back</button>
    <input id="path" value="{{ current_path if current_path != '/' else '' }}" placeholder="root/path (example: home/Documents)">
    <div id="fs" style="margin-top:10px">Loading...</div>
  </div>
  <div class="card">
    <b>⬆ Upload</b>
    <form method="POST" enctype="multipart/form-data" action="{{ url_for('files_upload') }}" style="margin-top:10px">
      <input type="hidden" id="uploadPath" name="path" value="{{ selected_path }}">
      <input type="file" name="file">
      <button class="btn" style="margin-top:8px">Upload</button>
    </form>
  </div>
</div><div class="right">
  <div class="card"><b>Roots</b><div class="small" style="margin-top:8px">Configure roots with REMOTE_FS_ROOTS on the client.</div></div>
</div></div>
<script>
async function waitJob(jobId){for(let i=0;i<80;i++){const r=await fetch('{{ url_for('job_status', job_id='JOB') }}'.replace('JOB',jobId));const d=await r.json();if(d.done)return d.result;await new Promise(x=>setTimeout(x,250))}return {ok:false,error:'job timeout'}}
function esc(s){return String(s).replace(/[&<>\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[m]))}
function curPath(){return document.getElementById('path').value.trim().replace(/^\/+|\/+$/g,'')}
function goParent(){const p=curPath();if(!p){return}const parts=p.split('/');parts.pop();document.getElementById('path').value=parts.join('/');refreshFs()}
async function removeFile(path){if(!confirm('Delete '+path+'?'))return;const r=await fetch('{{ url_for('api_fs_delete') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});const q=await r.json();if(!q.ok){alert(q.error||'delete failed');return}const res=await waitJob(q.job_id);if(!res.ok)alert(res.error||'delete failed');refreshFs()}
async function openView(path){window.open('{{ url_for('files_view') }}?file='+encodeURIComponent(path),'_blank')}
function downloadFile(path){window.location.href='{{ url_for('files_download') }}?file='+encodeURIComponent(path)}
async function refreshFs(){const path=curPath();document.getElementById('uploadPath').value=path;const q=await fetch('{{ url_for('api_fs_list') }}?path='+encodeURIComponent(path));const d=await q.json();if(!d.ok){document.getElementById('fs').textContent=d.error||'error';return}const res=await waitJob(d.job_id);if(!res.ok){document.getElementById('fs').textContent=res.error||'error';return}let html='';for(const f of res.items||[]){if(f.is_dir){html+=`<div class="client-row"><b>📂 <a href="?path=${encodeURIComponent(f.rel)}">${esc(f.name)}</a></b><div class="small">${f.rel}</div></div>`}else{html+=`<div class="client-row"><div><b>📄 ${esc(f.name)}</b><div class="small">${f.size??''} bytes · ${f.mtime||''}</div></div><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:7px"><button class="btn" onclick="openView('${encodeURIComponent(f.rel)}')">👁 View</button><button class="btn" onclick="downloadFile('${encodeURIComponent(f.rel)}')">⬇ Download</button><button class="btn danger" onclick="removeFile('${f.rel.replace(/'/g,"&#039;")}')">🗑 Delete</button></div></div>`}}document.getElementById('fs').innerHTML=html||'<div class="small">Empty folder</div>'}
refreshFs();
</script>
"""


ADMIN_USERS_TEMPLATE = '\n<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n<title>Neon Admin • Users</title>\n\n<style>\n:root{\n  --neon: {{ neon }};\n  --bg:#05060d;\n  --panel:rgba(0,0,0,.35);\n  --border:rgba(255,255,255,.12);\n  --text:#e9f1ff;\n  --muted:#9fb0ff;\n}\n\n*{box-sizing:border-box}\n\nbody{\n  margin:0;\n  background:var(--bg);\n  color:var(--text);\n  font-family:Inter,Segoe UI,Arial;\n  overflow:hidden;\n}\n\na{color:var(--neon);text-decoration:none}\n\n/* ===== COMMON ===== */\n.btn{\n  border:1px solid var(--neon);\n  background:transparent;\n  color:var(--neon);\n  padding:6px 12px;\n  border-radius:8px;\n  cursor:pointer;\n  transition:.15s;\n}\n.btn:hover{\n  background:var(--neon);\n  color:#000;\n}\n\ninput{\n  width:100%;\n  padding:8px;\n  background:#02040f;\n  color:var(--text);\n  border:1px solid var(--border);\n  border-radius:8px;\n  margin-bottom:10px;\n}\n\nlabel{color:var(--muted)}\n.small{font-size:12px;color:var(--muted)}\n.hidden{display:none}\n\n/* ===== TOP BAR ===== */\n.top{\n  position:fixed;\n  top:0;left:0;\n  width:100%;\n  height:64px;\n  background:rgba(0,0,0,.9);\n  border-bottom:1px solid var(--border);\n  display:flex;\n  align-items:center;\n  justify-content:space-between;\n  padding:0 16px;\n  z-index:10;\n}\n\n.modes{\n  display:flex;\n  gap:10px;\n}\n.modes button.active{\n  background:var(--neon);\n  color:#000;\n}\n\n/* ===== LAYOUT ===== */\n.wrap{\n  display:grid;\n  grid-template-columns:280px 1fr;\n  height:100vh;\n  padding-top:64px;\n}\n\n/* ===== SIDEBAR ===== */\n.sidebar{\n  padding:16px;\n  border-right:1px solid var(--border);\n  background:rgba(0,0,0,.25);\n}\n\n.user{\n  padding:10px;\n  border:1px solid var(--border);\n  border-radius:10px;\n  margin-bottom:10px;\n  cursor:pointer;\n  transition:.15s;\n}\n.user:hover{\n  border-color:var(--neon);\n  box-shadow:0 0 12px var(--neon);\n}\n.user b{color:var(--neon)}\n\n/* ===== CONTENT ===== */\n.content{\n  padding:20px;\n  overflow:auto;\n}\n\n.card{\n  background:var(--panel);\n  border:1px solid var(--border);\n  border-radius:14px;\n  padding:18px;\n  max-width:540px;\n}\n\n/* ===== PERMISSIONS ===== */\n.perms{\n  display:flex;\n  flex-wrap:wrap;\n  gap:8px;\n  margin-bottom:14px;\n}\n\n.perm{\n  padding:6px 12px;\n  border-radius:999px;\n  border:1px solid var(--border);\n  cursor:pointer;\n  user-select:none;\n  font-size:13px;\n  color:var(--muted);\n  transition:.15s;\n}\n.perm input{display:none}\n.perm:hover{\n  border-color:var(--neon);\n  color:var(--neon);\n}\n.perm.active{\n  background:var(--neon);\n  color:#000;\n  border-color:var(--neon);\n}\n\n/* ===== DANGER ===== */\n.danger{\n  border-color:#ff6b6b;\n  color:#ff6b6b;\n}\n.danger:hover{\n  background:#ff6b6b;\n  color:#000;\n}\n</style>\n</head>\n\n<body>\n\n<!-- TOP -->\n<div class="top">\n  <a href="{{ url_for(\'index\') }}" class="btn">🏠 Головна</a>\n\n  <div class="modes">\n    <button class="btn active" onclick="setMode(\'view\',this)">👁 View</button>\n    <button class="btn" onclick="setMode(\'create\',this)">➕ Create</button>\n    <button class="btn" onclick="setMode(\'update\',this)">♻ Update</button>\n    <button class="btn danger" onclick="setMode(\'delete\',this)">🗑 Delete</button>\n  </div>\n</div>\n\n<div class="wrap">\n\n<!-- SIDEBAR -->\n<div class="sidebar">\n  <b>Users</b>\n  <div style="margin-top:12px">\n    {% for u,v in users.items() %}\n    <div class="user" onclick="selectUser(\'{{ u }}\')">\n      <b>{{ u }}</b><br>\n      <span class="small">\n        perms: {{ v.permissions }}<br>\n        2FA: {{ v.get("2fa_enabled") }}\n      </span>\n    </div>\n    {% endfor %}\n  </div>\n</div>\n\n<!-- CONTENT -->\n<div class="content">\n\n<div class="card" id="view">\n  <h3 style="color:var(--neon)">Selected user</h3>\n  <p id="viewName" class="small">—</p>\n</div>\n\n<div class="card hidden" id="create">\n  <h3 style="color:var(--neon)">Create user</h3>\n  <form method="POST">\n    <input name="username" placeholder="Username">\n    <input name="password" placeholder="Password">\n\n    <input type="hidden" name="permissions" id="permCreate">\n    <div class="perms" data-target="permCreate">\n      {% for p in [\'admin\',\'files\',\'camera\',\'remote\',\'notifications\',\'messages\',\'chat\'] %}\n      <label class="perm"><input type="checkbox" value="{{ p }}">{{ p }}</label>\n      {% endfor %}\n    </div>\n\n    <label><input type="checkbox" name="2fa"> Enable 2FA</label><br><br>\n    <button class="btn" name="action" value="create">Create</button>\n  </form>\n</div>\n\n<div class="card hidden" id="update">\n  <h3 style="color:var(--neon)">Update user</h3>\n  <form method="POST">\n    <input id="u_update" name="username_update" placeholder="Username">\n    <input name="password_update" placeholder="New password">\n\n    <input type="hidden" name="permissions_update" id="permUpdate">\n    <div class="perms" data-target="permUpdate">\n      {% for p in [\'admin\',\'files\',\'camera\',\'remote\',\'notifications\',\'messages\',\'chat\'] %}\n      <label class="perm"><input type="checkbox" value="{{ p }}">{{ p }}</label>\n      {% endfor %}\n    </div>\n\n    <button class="btn" name="action" value="update">Update</button>\n  </form>\n</div>\n\n<div class="card hidden" id="delete">\n  <h3 style="color:#ff6b6b">Delete user</h3>\n  <form method="POST">\n    <input id="u_delete" name="username_del" placeholder="Username">\n    <button class="btn danger" name="action" value="delete">Delete</button>\n  </form>\n</div>\n\n</div>\n</div>\n\n<script>\nfunction setMode(m,btn){\n  document.querySelectorAll(\'.card\').forEach(c=>c.classList.add(\'hidden\'));\n  document.getElementById(m).classList.remove(\'hidden\');\n  document.querySelectorAll(\'.modes button\').forEach(b=>b.classList.remove(\'active\'));\n  btn.classList.add(\'active\');\n}\n\nfunction selectUser(u){\n  viewName.innerText=u;\n  u_update.value=u;\n  u_delete.value=u;\n}\n\n/* permissions logic */\ndocument.querySelectorAll(\'.perms\').forEach(group=>{\n  const target=document.getElementById(group.dataset.target);\n  group.querySelectorAll(\'.perm\').forEach(tag=>{\n    tag.onclick=()=>{\n      const cb=tag.querySelector(\'input\');\n      cb.checked=!cb.checked;\n      tag.classList.toggle(\'active\',cb.checked);\n      target.value=[...group.querySelectorAll(\'input:checked\')].map(x=>x.value).join(\',\');\n    };\n  });\n});\n</script>\n\n</body>\n</html>\n'

NOTIFS_TEMPLATE = '\n<!doctype html><meta charset="utf-8"><title>Notifications</title><style>\n:root{--neon: {{ neon }}}\nbody{background:#02030a;color:var(--neon);font-family:Inter;padding:18px}\n.item{padding:6px;border-bottom:1px solid rgba(0,255,208,0.03)}\n</style>\n<body>\n  <h3>Notifications for {{username}}</h3>\n  <a href="{{ url_for(\'index\') }}">Home</a>\n  <hr>\n  {% for n in notifs %}\n    <div class="item"><b>{{n.ts}}</b> — <i>{{n.title}}</i> <div>{{n.message}}</div></div>\n  {% else %}\n    <div>No notifications</div>\n  {% endfor %}\n</body>\n'

MESSAGES_TEMPLATE = '\n<!doctype html><meta charset="utf-8"><title>Повідомлення</title>\n<style>\n:root{--neon: {{ neon }}}\nbody{background:#02030a;color:var(--neon);font-family:Inter;padding:18px}\n.msg{padding:6px;border-bottom:1px dashed rgba(0,255,208,0.2)}\n.small{font-size:12px;color:#8ff}\n.btn{border:1px solid var(--neon);padding:6px;border-radius:6px;color:var(--neon);background:transparent}\n</style>\n<body>\n  <h3>Повідомлення для {{username}}</h3>\n  <a href="{{ url_for(\'index\') }}" class="btn">🏠 На головну</a>\n  <hr>\n  {% for m in messages %}\n    <div class="msg"><b>{{m.from}}</b>: {{m.msg}} <span class="small">({{m.ts}})</span></div>\n  {% else %}\n    <div>Немає повідомлень</div>\n  {% endfor %}\n  <hr>\n  <form method="POST">\n    <select name="to">\n      {% for u in users %}\n        {% if u != username %}\n          <option value="{{u}}">{{u}}</option>\n        {% endif %}\n      {% endfor %}\n    </select><br><br>\n    <textarea name="msg" placeholder="Текст повідомлення"></textarea><br>\n    <button class="btn">Надіслати</button>\n  </form>\n</body>\n'

CHAT_TEMPLATE = '\n<!doctype html><meta charset="utf-8"><title>Глобальний чат</title>\n<style>\n:root{--neon: {{ neon }}}\nbody{background:#02030a;color:var(--neon);font-family:Inter;padding:18px}\n.item{padding:6px;border-bottom:1px dashed rgba(0,255,208,0.2)}\n.small{font-size:12px;color:#8ff}\n.btn{border:1px solid var(--neon);padding:6px;border-radius:6px;color:var(--neon);background:transparent}\n.form{margin-top:12px}\n</style>\n<body>\n  <h3>Глобальний чат</h3>\n  <a href="{{ url_for(\'index\') }}" class="btn">🏠 На головну</a>\n  <hr>\n  {% for m in chat %}\n    <div class="item"><b>{{m.user}}</b>: {{m.msg}} <span class="small">({{m.ts}})</span></div>\n  {% else %}\n    <div>Немає повідомлень у чаті</div>\n  {% endfor %}\n  <hr>\n  <form method="POST" class="form">\n    <textarea name="msg" placeholder="Написати у глобальний чат"></textarea><br>\n    <button class="btn">Опублікувати</button>\n  </form>\n</body>\n'

REMOTE_TEMPLATE = BASE_STYLE + SIDEBAR + r"""
<div class="layout"><div class="main">
  <div class="card"><b>🎮 Remote — {{ pc_name }}</b><div class="small">{{ cid }}</div></div>
  <div class="card">
    <img id="screen" class="screen" src="{{ url_for('screen_feed') }}">
    <div class="small" style="margin-top:8px">Click the screen to send mouse input. Keyboard actions require client-side ALLOW_REMOTE_INPUT=1.</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      <button class="btn" onclick="sendKeyClick('click')">Left Click</button>
      <button class="btn" onclick="sendKeyClick('double')">Double Click</button>
      <button class="btn" onclick="sendKeyClick('right')">Right Click</button>
      <button class="btn" onclick="browserFullscreen()">Fullscreen</button>
    </div>
    <div class="client-row" style="margin-top:12px">
      <b>⌨ Keyboard events</b>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
        <button class="btn" onclick="sendKey('enter')">Enter</button><button class="btn" onclick="sendKey('esc')">Esc</button><button class="btn" onclick="sendKey('tab')">Tab</button><button class="btn" onclick="sendKey('backspace')">Backspace</button><button class="btn" onclick="sendKey('left')">←</button><button class="btn" onclick="sendKey('right')">→</button><button class="btn" onclick="sendKey('up')">↑</button><button class="btn" onclick="sendKey('down')">↓</button><button class="btn" onclick="sendKey('c',['ctrl'])">Ctrl+C</button><button class="btn" onclick="sendKey('v',['ctrl'])">Ctrl+V</button><button class="btn" onclick="sendKey('a',['ctrl'])">Ctrl+A</button>
      </div>
    </div>
    <textarea id="typebox" rows="5" style="margin-top:10px" placeholder="Text to type on the client"></textarea>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button class="btn" onclick="sendText()">Send Text</button><button class="btn" onclick="sendDemoBeep()">🔊 Demo beep</button></div>
    <div id="status" class="small" style="margin-top:8px">Ready</div>
  </div>
</div><div class="right">
  <div class="card"><b>Keyboard</b><div class="small" style="margin-top:8px">Common special keys and modifier combinations are supported by the current client build.</div></div>
  <div class="card"><b>Demo effects</b><div class="small" style="margin-top:8px">Only a harmless opt-in beep is available; disruptive prank actions are intentionally excluded.</div></div>
</div></div>
<script>
let lastPoint={x:0,y:0};
function browserFullscreen(){const el=document.getElementById('screen');if(el.requestFullscreen)el.requestFullscreen()}
function pointFromEvent(e){const img=document.getElementById('screen'),r=img.getBoundingClientRect();const sx=img.naturalWidth||r.width,sy=img.naturalHeight||r.height;return {x:Math.max(0,Math.min(sx-1,Math.round((e.clientX-r.left)*(sx/r.width)))),y:Math.max(0,Math.min(sy-1,Math.round((e.clientY-r.top)*(sy/r.height)))}}
async function sendKeyClick(type){const s=document.getElementById('status');const q=await fetch('{{ url_for('api_input_click') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...lastPoint,type})});const d=await q.json();s.textContent=d.ok?'✅ sent':(d.error||'error')}
document.getElementById('screen').addEventListener('click',async e=>{lastPoint=pointFromEvent(e);await sendKeyClick('click')})
async function sendText(){const text=document.getElementById('typebox').value;const r=await fetch('{{ url_for('api_input_type') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});const d=await r.json();document.getElementById('status').textContent=d.ok?'✅ sent':(d.error||'error')}
async function sendKey(key,modifiers=[]){const r=await fetch('{{ url_for('api_input_key') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,modifiers})});const d=await r.json();document.getElementById('status').textContent=d.ok?'⌨ sent':(d.error||'error')}
async function sendDemoBeep(){const r=await fetch('{{ url_for('api_demo_prank') }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({effect:'beep'})});const d=await r.json();document.getElementById('status').textContent=d.ok?'🔊 demo queued':(d.error||'error')}
</script>
"""


FULLSCREEN_TEMPLATE = '\n<!doctype html>\n<html>\n<head><meta charset="utf-8"><title>Fullscreen Remote Control</title>\n<style>body{margin:0;background:#000;overflow:hidden}#screen{width:100vw;height:100vh;display:block;cursor:crosshair}</style>\n</head>\n<body>\n<img id="screen" src="{{ url_for(\'screen_feed\') }}">\n<script>\nconst img = document.getElementById("screen");\nfunction postJSON(u, data){ fetch(u, {method:"POST", headers:{\'Content-Type\':\'application/json\'}, body: JSON.stringify(data)}); }\nimg.addEventListener("click", function(e){\n    const scaleX = img.naturalWidth / img.clientWidth;\n    const scaleY = img.naturalHeight / img.clientHeight;\n    const x = Math.floor(e.offsetX * scaleX);\n    const y = Math.floor(e.offsetY * scaleY);\n    postJSON("{{ url_for(\'fs_action_click\') }}", {x:x,y:y,type:"click"});\n});\nimg.addEventListener("dblclick", function(e){\n    const scaleX = img.naturalWidth / img.clientWidth;\n    const scaleY = img.naturalHeight / img.clientHeight;\n    const x = Math.floor(e.offsetX * scaleX);\n    const y = Math.floor(e.offsetY * scaleY);\n    postJSON("{{ url_for(\'fs_action_click\') }}", {x:x,y:y,type:"double"});\n});\nlet dragging = false;\nimg.addEventListener("mousedown", () => dragging = true);\nimg.addEventListener("mouseup", () => dragging = false);\nimg.addEventListener("mousemove", function(e){\n    if(dragging){\n        const scaleX = img.naturalWidth / img.clientWidth;\n        const scaleY = img.naturalHeight / img.clientHeight;\n        const x = Math.floor(e.offsetX * scaleX);\n        const y = Math.floor(e.offsetY * scaleY);\n        postJSON("{{ url_for(\'fs_action_move\') }}", {x:x,y:y});\n    }\n});\n</script>\n</body>\n</html>\n'


# ---------------------------------------------------------------------------
# Synchronous job helper used by the original z15-style pages.
# z16 polls heartbeat every second, so a short server-side wait keeps the
# original z15 forms usable without changing their look.
# ---------------------------------------------------------------------------
def wait_client_job(cid: str, job_id: str, timeout: float = 12.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = get_job_result(cid, job_id)
        if result is not None:
            return result
        if not is_online(get_client(cid) or {}):
            return {"ok": False, "error": "client went offline"}
        time.sleep(0.2)
    return {"ok": False, "error": "job timeout"}

def remote_job_sync(action: str, timeout: float = 12.0, **payload: Any) -> dict[str, Any]:
    cid, _ = require_selected_client()
    try:
        jid = queue_job(cid, action, **payload)
    except KeyError:
        return {"ok": False, "error": "client is offline"}
    result = wait_client_job(cid, jid, timeout=timeout)
    return result if isinstance(result, dict) else {"ok": False, "error": "invalid client result"}

# ---------------------------------------------------------------------------
# z15 backend endpoint aliases
# ---------------------------------------------------------------------------
@app.post("/sys_action")
@login_required
def sys_action():
    action = request.form.get("action", "")
    if action == "logout":
        return redirect(url_for("logout"))
    flash(f"System action '{action}' is not implemented by the current z16.py client.")
    return redirect(url_for("index"))

@app.get("/api/system")
@login_required
def api_system():
    _, c = get_selected_client()
    if not c:
        return jsonify(cpu=0.0, ram=0.0)
    cpu = float(c.get("cpu") or 0.0)
    ram = float(c.get("ram") or 0.0)
    return jsonify(cpu=max(0.0, min(100.0, cpu)), ram=max(0.0, min(100.0, ram)))

@app.route("/api/volume", methods=["GET", "POST"])
@login_required
def api_volume():
    # Kept so the exact z15 UI continues to work. Current z16.py does not
    # implement a volume job, therefore the value is UI-only.
    if request.method == "POST":
        return jsonify(ok=False, error="volume job is not implemented by current z16.py"), 409
    return jsonify(value=50)

@app.post("/api/troll/toggle")
@login_required
def api_troll_toggle():
    data = request.get_json(silent=True) or {}
    effect = str(data.get("effect") or data.get("action") or "").strip().lower()
    if effect != "beep":
        return jsonify(active=False, disabled=True, error="Only the harmless demo beep is available."), 409
    return jsonify(post_job_and_mark("demo_prank", effect="beep"))

@app.post("/api/troll/stop")
@login_required
def api_troll_stop():
    return jsonify(ok=True, disabled=True)

@app.get("/prank/disco")
@login_required
def prank_disco():
    return jsonify(ok=False, disabled=True, error="Prank actions are disabled in the z16 remote build.")

# Remote aliases used by the exact z15 REMOTE_TEMPLATE.
@app.post("/remote/key")
@login_required
def remote_key():
    if not has_perm("remote"):
        return jsonify(error="no access"), 403
    data = request.get_json(silent=True) or {}
    if data.get("action") not in (None, "press"):
        return jsonify(error="unsupported key action"), 400
    key = str(data.get("key", "")).strip()
    modifiers = data.get("modifiers") or []
    if not key:
        return jsonify(error="key required"), 400
    return jsonify(remote_job_sync("input_key", key=key, modifiers=modifiers))


@app.post("/remote/type")
@login_required
def remote_type():
    if not has_perm("remote"):
        return jsonify(error="no access"), 403
    data = request.get_json(silent=True) or {}
    return jsonify(remote_job_sync("input_type", text=str(data.get("text", ""))[:4000]))

@app.post("/remote/click")
@login_required
def remote_click_route():
    if not has_perm("remote"):
        return jsonify(error="no access"), 403
    data = request.get_json(silent=True) or {}
    return jsonify(remote_job_sync(
        "input_click",
        x=data.get("x"),
        y=data.get("y"),
        type=data.get("type", "click"),
    ))

@app.post("/remote/move")
@login_required
def remote_move_route():
    return jsonify(ok=False, error="Mouse move is not implemented by current z16.py"), 409

@app.post("/fs_action_click")
@login_required
def fs_action_click():
    if not has_perm("remote"):
        return jsonify(error="no access"), 403
    data = request.get_json(silent=True) or {}
    return jsonify(remote_job_sync(
        "input_click",
        x=data.get("x"),
        y=data.get("y"),
        type=data.get("type", "click"),
    ))

@app.post("/fs_action_move")
@login_required
def fs_action_move():
    return jsonify(ok=False, error="Continuous mouse move is not implemented by current z16.py"), 409

# ---------------------------------------------------------------------------
# Exact z15-style filesystem pages, backed by the z16 shared folder.
# ---------------------------------------------------------------------------
@app.get("/files_navigate")
@login_required
def files_navigate():
    denial = require_perm("files")
    if denial:
        return denial
    cid, _ = require_selected_client()
    path = request.args.get("path", "")
    result = remote_job_sync("fs_list", path=path)
    if not result.get("ok"):
        flash(result.get("error", "filesystem error"))
        return redirect(url_for("index"))
    parent = ""
    if path:
        parent = str(Path(path).parent.as_posix())
        if parent == ".":
            parent = ""
    neon, muted = theme_colors()
    return render_template_string(
        FILES_TEMPLATE,
        current_path=path or "/",
        parent=parent,
        files=result.get("items", []),
        neon=neon,
        muted=muted,
        cid=cid,
        pc_name=(get_client(cid) or {}).get("name", "Unknown PC"),
        themes_list=sorted(THEMES),
        username=session.get("username"),
        admin_username=ADMIN_USERNAME,
        cv2=True,
    )

@app.post("/files_upload")
@login_required
def files_upload():
    denial = require_perm("files")
    if denial:
        return denial
    f = request.files.get("file")
    if not f or not f.filename:
        flash("No file selected")
        return redirect(url_for("files_navigate", path=request.form.get("path", "")))
    raw = f.read()
    if len(raw) > 8 * 1024 * 1024:
        flash("Upload limited to 8 MB")
        return redirect(url_for("files_navigate", path=request.form.get("path", "")))
    result = remote_job_sync(
        "fs_upload",
        path=request.form.get("path", ""),
        name=Path(f.filename).name,
        data_b64=base64.b64encode(raw).decode("ascii"),
    )
    if not result.get("ok"):
        flash(result.get("error", "upload failed"))
    return redirect(url_for("files_navigate", path=request.form.get("path", "")))

@app.post("/files_delete")
@login_required
def files_delete():
    denial = require_perm("files")
    if denial:
        return denial
    path = request.form.get("file", "")
    result = remote_job_sync("fs_delete", path=path)
    if not result.get("ok"):
        flash(result.get("error", "delete failed"))
    parent = str(Path(path).parent.as_posix()) if path else ""
    if parent == ".":
        parent = ""
    return redirect(url_for("files_navigate", path=parent))

@app.get("/files_download")
@login_required
def files_download():
    denial = require_perm("files")
    if denial:
        return denial
    result = remote_job_sync("fs_download", path=request.args.get("file", ""))
    if not result.get("ok"):
        return result.get("error", "download failed"), 400
    try:
        raw = base64.b64decode(result.get("data_b64", ""), validate=True)
    except Exception:
        return "invalid file payload", 500
    return send_file(
        io.BytesIO(raw),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=result.get("name") or Path(request.args.get("file", "download.bin")).name,
    )

@app.get("/files_view")
@login_required
def files_view():
    denial = require_perm("files")
    if denial:
        return denial
    path = request.args.get("file", "")
    result = remote_job_sync("fs_view", path=path)
    if not result.get("ok"):
        return result.get("error", "view failed"), 400
    return render_template_string(
        VIEW_TEXT_TEMPLATE,
        filename=Path(path).name or path,
        content=result.get("content", ""),
        neon=theme_colors()[0],
        muted=theme_colors()[1],
    )

# ---------------------------------------------------------------------------
# Camera compatibility + local gallery for captured z16 photos.
# ---------------------------------------------------------------------------
CAMERA_DIR = DATA_DIR / "camera"
CAMERA_DIR.mkdir(parents=True, exist_ok=True)

def _render_exact_camera():
    denial = require_perm("camera")
    if denial:
        return denial
    cid, c = require_selected_client()
    neon, muted = theme_colors()
    return render_template_string(
        CAMERA_TEMPLATE,
        cv2=True,
        neon=neon,
        muted=muted,
        cid=cid,
        pc_name=c.get("name", "Unknown PC"),
        themes_list=sorted(THEMES),
        username=session.get("username"),
        admin_username=ADMIN_USERNAME,
    )

app.view_functions["camera_page"] = _render_exact_camera

@app.post("/camera_photo_route")
@login_required
def camera_photo_route():
    denial = require_perm("camera")
    if denial:
        return denial
    result = remote_job_sync("camera_photo", timeout=20)
    if not result.get("ok"):
        flash(result.get("error", "camera capture failed"))
        return redirect(url_for("camera_page"))
    try:
        raw = base64.b64decode(result.get("data_b64", ""), validate=True)
    except Exception:
        flash("Invalid camera payload")
        return redirect(url_for("camera_page"))
    name = f"camera_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
    (CAMERA_DIR / name).write_bytes(raw)
    session["last_photo"] = name
    return redirect(url_for("camera_page"))

@app.get("/camera_preview")
@login_required
def camera_preview():
    name = Path(request.args.get("file", "")).name
    path = CAMERA_DIR / name
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg")

@app.get("/camera_download")
@login_required
def camera_download():
    name = Path(request.args.get("file", "")).name
    path = CAMERA_DIR / name
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=name)

@app.get("/camera_gallery")
@login_required
def camera_gallery():
    denial = require_perm("camera")
    if denial:
        return denial
    files = []
    for p in sorted(CAMERA_DIR.glob("*.jpg"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({"name": p.name, "time": dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
    neon, muted = theme_colors()
    return render_template_string(
        CAMERA_GALLERY_TEMPLATE,
        files=files,
        neon=neon,
        muted=muted,
        username=session.get("username"),
        admin_username=ADMIN_USERNAME,
    )

@app.post("/camera_delete")
@login_required
def camera_delete():
    name = Path(request.form.get("file", "")).name
    path = CAMERA_DIR / name
    if path.is_file():
        path.unlink()
    return redirect(url_for("camera_gallery"))

# ---------------------------------------------------------------------------
# Replace a few existing view handlers with their exact z15 templates.
# ---------------------------------------------------------------------------
def _render_exact_remote():
    denial = require_perm("remote")
    if denial:
        return denial
    cid, c = require_selected_client()
    neon, muted = theme_colors()
    return render_template_string(
        REMOTE_TEMPLATE,
        username=session.get("username"),
        neon=neon,
        muted=muted,
        cid=cid,
        pc_name=c.get("name", "Unknown PC"),
        themes_list=sorted(THEMES),
        admin_username=ADMIN_USERNAME,
    )
app.view_functions["remote_page"] = _render_exact_remote

def _render_exact_files_root():
    return redirect(url_for("files_navigate", path=""))
app.view_functions["files_page"] = _render_exact_files_root

def _render_exact_fullscreen():
    denial = require_perm("screen")
    if denial:
        return denial
    cid, c = require_selected_client()
    return render_template_string(
        FULLSCREEN_TEMPLATE,
        cid=cid,
        pc_name=c.get("name", "Unknown PC"),
        neon=theme_colors()[0],
        muted=theme_colors()[1],
        username=session.get("username"),
        admin_username=ADMIN_USERNAME,
    )
app.view_functions["fullscreen_page"] = _render_exact_fullscreen


# Remaining endpoint names referenced literally by the exact z15 main template.
@app.post("/run_cmd")
@login_required
def run_cmd_route():
    if not has_perm("commands"):
        flash("No access to commands")
        return redirect(url_for("index"))
    command = request.form.get("cmd", "").strip()
    if not command:
        flash("No command")
        return redirect(url_for("index"))
    result = remote_job_sync("command", timeout=35, command=command)
    if result.get("ok"):
        session["last_cmd_output"] = result.get("output", "") or "—"
        add_notification(ADMIN_USERNAME, "Command executed", f"{session.get('username')} executed a command on the selected z16 client.")
    else:
        session["last_cmd_output"] = result.get("error", "command failed")
    return redirect(url_for("index"))

@app.get("/admin/export")
@login_required
def admin_export():
    if session.get("username") != ADMIN_USERNAME:
        return redirect(url_for("index"))
    mem = io.BytesIO()
    with __import__("zipfile").ZipFile(mem, "w", __import__("zipfile").ZIP_DEFLATED) as z:
        for path in [USERS_FILE, CHAT_FILE, NOTIFS_FILE, MESSAGES_FILE]:
            if path.exists():
                z.write(path, arcname=path.name)
    mem.seek(0)
    return send_file(mem, download_name="remote_neon_export.zip", as_attachment=True)

@app.get("/processes")
@login_required
def processes_page_compat():
    return """<!doctype html><meta charset="utf-8"><title>Processes</title>
    <body style="background:#05060d;color:#00ffd0;font-family:Inter,Segoe UI,Arial;padding:20px">
    <a href="/" style="color:#00ffd0">🏠 Home</a><h3>⚙ Processes</h3>
    <p>Process control is not part of the z16 remote protocol.</p></body>"""

# Override the original screen_feed to render a harmless black placeholder until
# a z16 client is selected, while preserving the exact z15 <img> destination.
def _screen_feed_compat():
    cid, _ = get_selected_client()
    if not cid:
        # 1x1 JPEG placeholder.
        return Response(
            base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9k="),
            mimetype="image/jpeg",
        )
    return Response(mjpeg_stream(cid, camera=False), mimetype="multipart/x-mixed-replace; boundary=frame")
app.view_functions["screen_feed"] = _screen_feed_compat

@app.errorhandler(413)
def payload_too_large(_error):
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="request too large"), 413
    flash("Request is too large.")
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="not found"), 404
    return "Not found", 404


@app.errorhandler(500)
def internal_error(_error):
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="internal server error"), 500
    return "Internal server error", 500


if __name__ == "__main__":
    print("=== Zlata z15 Sync Server ===")
    print("Listen:", f"http://{HOST}:{PORT}")
    print("Admin:", ADMIN_USERNAME)
    print("Remote token set:", CLIENT_TOKEN != "change-me-client-token")
    if CLIENT_TOKEN == "change-me-client-token":
        print("[WARN] Set REMOTE_CLIENT_TOKEN to the same value in Zlata and z16.")
    if ADMIN_PASSWORD == "change-me-now":
        print("[WARN] Change REMOTE_PASS before exposing the server.")
    app.run(host=HOST, port=PORT, threaded=True, debug=False)

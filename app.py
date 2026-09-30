# remote_neon_server.py
# -*- coding: utf-8 -*-
"""
Neon Remote Control v2.0 — Multi-Computer Remote Management System
Features:
- Master Server & Client Agent Modes (Multi-PC control)
- Neon Theme UI with dynamic color switcher
- Password Authentication, Sessions & User Permissions
- Real-time System Monitoring, Process Manager, File System, Camera, Remote Desktop, Troll Panel
Zlata+Arkadii=Love
"""

import os
import sys
import io
import time
import json
import socket
import datetime
import threading
import subprocess
import argparse
import shlex
import zipfile
import hmac
import hashlib
import base64
from functools import wraps

from flask import (Flask, render_template_string, Response, request, redirect,
                   url_for, session, send_file, flash, jsonify, get_flashed_messages)

# --- App Initialization ---
app = Flask(__name__)

# Config & Environment
ADMIN_USERNAME = "pro"
ADMIN_PASSWORD = os.environ.get("REMOTE_PASS", "tttt")
PORT = int(os.environ.get("REMOTE_PORT", 4237))
SECRET_KEY = os.environ.get("FLASK_SECRET", "arkadiip_secret_key")
app.secret_key = SECRET_KEY
SCREEN_DELAY = float(os.environ.get("SCREEN_DELAY", 0.05))
BASE_DIR = os.getcwd()
ALLOW_REMOTE_CMD = True

# Storage paths
APPDATA = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
REMOTE_DATA_DIR = os.path.join(APPDATA, "RemoteNeon")
USERS_FILE = os.path.join(REMOTE_DATA_DIR, "users.json")
NOTIFS_FILE = os.path.join(REMOTE_DATA_DIR, "notifications.json")
MESSAGES_FILE = os.path.join(REMOTE_DATA_DIR, "messages.json")
CHAT_FILE = os.path.join(REMOTE_DATA_DIR, "chat.json")
CAMERA_DIR = os.path.join(BASE_DIR, "static", "camera")

os.makedirs(REMOTE_DATA_DIR, exist_ok=True)
os.makedirs(CAMERA_DIR, exist_ok=True)

# Optional Libraries
try:
    import psutil
    psutil.cpu_percent(None)
except ImportError:
    psutil = None

try:
    from PIL import Image, ImageGrab, ImageFile
    ImageFile.MAX_IMAGE_PIXELS = None
except ImportError:
    Image = ImageGrab = None

try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
    try:
        pyautogui.FAILSAFE = False
    except Exception:
        pass
except Exception:
    PYAUTOGUI_AVAILABLE = False

try:
    import mss
    MSS_AVAILABLE = True
except Exception:
    MSS_AVAILABLE = False

# Windows Specific Libraries
IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes, POINTER, cast
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        import win32gui
        import win32con
        import winsound
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        PYCAW_AVAILABLE = True
    except Exception:
        PYCAW_AVAILABLE = False
else:
    user32 = None
    kernel32 = None
    PYCAW_AVAILABLE = False

# Multi-PC Agent Registry
AGENTS_LOCK = threading.Lock()
CONNECTED_AGENTS = {}  # {agent_id: {hostname, ip, os, last_seen, cpu, ram, pending_task: None, last_result: None}}

# Theme Definitions
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

# Trolls / Pranks Definitions
TROLLS = {
    "block": {"short": "Блок вводу", "long": "Повністю блокує мишку та клавіатуру на заданий час"},
    "mouse": {"short": "Миша хаос", "long": "Міняє місцями кнопки миші"},
    "disco": {"short": "Диско вікон", "long": "Вікна хаотично відкриваються та рухаються"},
    "beep": {"short": "Системні біпи", "long": "Програє випадкові системні звукові сигнали"},
    "shake": {"short": "Тряска вікна", "long": "Активне вікно починає різко трястися"},
    "invert": {"short": "Інверсія", "long": "Інвертує кольори екрана"},
    "drift": {"short": "Знос миші", "long": "Курсор повільно самовільно відхиляється"},
    "minall": {"short": "Згорнути все", "long": "Миттєво згортає всі відкриті вікна"},
    "altab": {"short": "Alt+Tab", "long": "Хаотично перемикає активні вікна"},
    "notify": {"short": "Фейк повідомлення", "long": "Показує фальшиве системне повідомлення"},
    "scroll": {"short": "Реверс скролу", "long": "Інвертує напрямок прокрутки"},
    "type": {"short": "Фейк друк", "long": "Система сама вводить випадковий текст"},
    "freeze": {"short": "Фріз", "long": "Імітує зависання вікон"},
    "blink": {"short": "Блимання", "long": "Екран коротко блимає"},
    "volume": {"short": "Гучність хаос", "long": "Різко змінює рівень системної гучності"},
    "usb": {"short": "USB звук", "long": "Відтворює звук підключення USB"},
    "focus": {"short": "Крадіжка фокусу", "long": "Постійно перехоплює фокус активного вікна"},
    "task": {"short": "Панель задач", "long": "Ховає та показує панель задач Windows"},
    "cursor": {"short": "Курсор хаос", "long": "Різко змінює позицію курсора"},
    "almost": {"short": "Майже нічого", "long": "Створює відчуття зламу 😈"}
}

TROLL_STATE = {k: False for k in TROLLS}
TROLL_EVENTS = {k: threading.Event() for k in TROLLS}
PENDING_OTPS = {}

# --- Helper Functions ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

def load_users():
    if not os.path.exists(USERS_FILE):
        users = {
            ADMIN_USERNAME: {
                "password": ADMIN_PASSWORD,
                "permissions": ["admin", "screen", "files", "commands", "processes", "camera", "network", "remote"],
                "2fa_enabled": False,
                "2fa_secret": "",
                "notify_on": []
            }
        }
        save_users(users)
        return users
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def load_notifs():
    if not os.path.exists(NOTIFS_FILE):
        return {}
    try:
        with open(NOTIFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_notifs(notifs):
    with open(NOTIFS_FILE, "w", encoding="utf-8") as f:
        json.dump(notifs, f, indent=2, ensure_ascii=False)

def add_notification(target_usernames, title, message):
    if isinstance(target_usernames, str):
        target_usernames = [target_usernames]
    notifs = load_notifs()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for u in target_usernames:
        lst = notifs.get(u, [])
        lst.insert(0, {"ts": ts, "title": title, "message": message})
        notifs[u] = lst[:200]
    save_notifs(notifs)

def get_theme_colors(theme_name):
    theme = THEMES.get(theme_name, THEMES.get(DEFAULT_THEME))
    return theme["neon"], theme["muted"]

def current_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_system_info():
    cpu = psutil.cpu_percent(interval=None) if psutil else 0
    ram = psutil.virtual_memory().percent if psutil else 0
    return {"cpu_percent": cpu, "ram_percent": ram}

def show_ips():
    try:
        local = socket.gethostbyname(socket.gethostname())
    except Exception:
        local = "127.0.0.1"
    return {"local": local, "public": "LAN-Mode"}

# Audio Volume Control (Windows pycaw)
def set_volume(percent: int):
    if not IS_WINDOWS or not PYCAW_AVAILABLE:
        return
    try:
        percent = max(0, min(100, percent))
        comtypes.CoInitialize()
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, 23, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
    except Exception:
        pass

def get_volume():
    if not IS_WINDOWS or not PYCAW_AVAILABLE:
        return 50
    try:
        comtypes.CoInitialize()
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, 23, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        return int(volume.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return 50

# --- Screen Grabber ---
def capture_screen():
    if MSS_AVAILABLE:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = Image.frombytes("RGB", sct.grab(monitor).size, sct.grab(monitor).bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            return buf.getvalue()
    elif ImageGrab:
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=60)
        return buf.getvalue()
    return b""

def start_stream_generator():
    while True:
        try:
            frame = capture_screen()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        except Exception:
            pass
        time.sleep(SCREEN_DELAY)

# --- Routes ---

@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_users()
    msg = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        user = users.get(username)
        if user and user.get("password") == pw:
            session["logged_in"] = True
            session["username"] = username
            add_notification([ADMIN_USERNAME], "Вхід у систему", f"Користувач {username} увійшов о {current_ts()}")
            return redirect(url_for("index"))
        else:
            msg = "Невірний логін або пароль"
    return render_template_string(LOGIN_TEMPLATE, msg=msg)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    info = show_ips()
    sysinfo = get_system_info()
    username = session.get("username")
    users = load_users()
    user_perms = users.get(username, {}).get("permissions", [])
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    cmd_output = session.pop("last_cmd_output", None)

    with AGENTS_LOCK:
        agents_count = len(CONNECTED_AGENTS)

    return render_template_string(
        MAIN_TEMPLATE,
        cpu=sysinfo["cpu_percent"],
        ram=sysinfo["ram_percent"],
        local_ip=info["local"],
        username=username,
        permissions=user_perms,
        theme=theme,
        neon=neon,
        muted=muted,
        cmd_output=cmd_output,
        agents_count=agents_count,
        themes_list=sorted(THEMES.keys()),
        TROLLS=TROLLS
    )

@app.route("/screen_feed")
@login_required
def screen_feed():
    return Response(start_stream_generator(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/system")
def api_system():
    sysinfo = get_system_info()
    return jsonify(sysinfo)

@app.route("/api/volume", methods=["GET", "POST"])
@login_required
def api_volume():
    if request.method == "POST":
        data = request.get_json(force=True) or {}
        set_volume(int(data.get("value", 50)))
        return {"ok": True}
    return {"value": get_volume()}

@app.route("/run_cmd", methods=["POST"])
@login_required
def run_cmd():
    cmd = request.form.get("cmd", "")
    if not cmd:
        return redirect(url_for("index"))
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        out = (res.stdout or "") + (res.stderr or "")
    except Exception as e:
        out = str(e)
    session["last_cmd_output"] = out
    return redirect(url_for("index"))

# --- Multi-PC Management API & Page ---
@app.route("/agents")
@login_required
def agents_page():
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    with AGENTS_LOCK:
        agents = list(CONNECTED_AGENTS.values())
    return render_template_string(AGENTS_TEMPLATE, agents=agents, neon=neon, muted=muted)

@app.route("/api/agent/register", methods=["POST"])
def agent_register():
    data = request.get_json(force=True) or {}
    agent_id = data.get("agent_id")
    if not agent_id:
        return jsonify({"error": "missing agent_id"}), 400
    
    with AGENTS_LOCK:
        CONNECTED_AGENTS[agent_id] = {
            "id": agent_id,
            "hostname": data.get("hostname", "Unknown"),
            "ip": request.remote_addr,
            "os": data.get("os", "Unknown"),
            "cpu": data.get("cpu", 0),
            "ram": data.get("ram", 0),
            "last_seen": current_ts(),
            "pending_cmd": None,
            "last_result": None
        }
    return jsonify({"status": "registered"})

@app.route("/api/agent/heartbeat", methods=["POST"])
def agent_heartbeat():
    data = request.get_json(force=True) or {}
    agent_id = data.get("agent_id")
    if not agent_id:
        return jsonify({"error": "missing agent_id"}), 400

    with AGENTS_LOCK:
        if agent_id in CONNECTED_AGENTS:
            CONNECTED_AGENTS[agent_id]["last_seen"] = current_ts()
            CONNECTED_AGENTS[agent_id]["cpu"] = data.get("cpu", 0)
            CONNECTED_AGENTS[agent_id]["ram"] = data.get("ram", 0)
            
            cmd = CONNECTED_AGENTS[agent_id].get("pending_cmd")
            CONNECTED_AGENTS[agent_id]["pending_cmd"] = None
            return jsonify({"status": "ok", "cmd": cmd})
    return jsonify({"error": "not registered"}), 404

@app.route("/api/agent/send_cmd", methods=["POST"])
@login_required
def agent_send_cmd():
    data = request.get_json(force=True) or {}
    agent_id = data.get("agent_id")
    cmd = data.get("cmd")
    with AGENTS_LOCK:
        if agent_id in CONNECTED_AGENTS:
            CONNECTED_AGENTS[agent_id]["pending_cmd"] = cmd
            return jsonify({"ok": True})
    return jsonify({"error": "agent not found"}), 404

# --- Processes Routes ---
@app.route("/processes")
@login_required
def processes_page():
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    return render_template_string(PROCESSES_TEMPLATE, neon=neon, muted=muted)

@app.route("/api/processes")
@login_required
def api_processes():
    if not psutil:
        return jsonify({"processes": []})
    q = request.args.get("q", "").lower()
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            name = p.info["name"] or ""
            pid = p.info["pid"]
            if q and (q not in name.lower() and q != str(pid)):
                continue
            procs.append({
                "pid": pid,
                "name": name,
                "ram": round(p.info["memory_info"].rss / 1024 / 1024, 1)
            })
        except Exception:
            pass
    return jsonify({"processes": sorted(procs, key=lambda x: x["name"].lower())[:100]})

@app.route("/api/process/kill", methods=["POST"])
@login_required
def api_process_kill():
    pid = request.form.get("pid")
    if pid and psutil:
        try:
            psutil.Process(int(pid)).kill()
            return "ok"
        except Exception:
            pass
    return "fail", 400

# --- File System Routes ---
@app.route("/files")
@login_required
def files_root():
    return redirect(url_for("files_navigate", path=""))

@app.route("/files/navigate")
@login_required
def files_navigate():
    rel = request.args.get("path", "").lstrip("/\\")
    full_path = os.path.abspath(os.path.join(BASE_DIR, rel))
    
    if not os.path.exists(full_path):
        full_path = BASE_DIR
        rel = ""

    items = []
    try:
        with os.scandir(full_path) as it:
            for entry in it:
                items.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else "-",
                    "rel": os.path.join(rel, entry.name).replace("\\", "/")
                })
    except Exception:
        pass

    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    parent = os.path.dirname(rel) if rel else None
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)

    return render_template_string(
        FILES_TEMPLATE,
        files=items,
        current_path="/" + rel,
        parent=parent,
        neon=neon,
        muted=muted
    )

# --- Camera Page ---
@app.route("/camera")
@login_required
def camera_page():
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    return render_template_string(CAMERA_TEMPLATE, cv2=CV2_AVAILABLE, neon=neon, muted=muted)

# --- Remote Page ---
@app.route("/remote")
@login_required
def remote_page():
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    return render_template_string(REMOTE_TEMPLATE, neon=neon, muted=muted)

@app.route("/fullscreen")
@login_required
def fullscreen_page():
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    return render_template_string(FULLSCREEN_TEMPLATE, neon=neon, muted=muted)

# --- Theme Switcher ---
@app.route("/set_theme", methods=["POST"])
@login_required
def set_theme():
    data = request.get_json() or {}
    theme = data.get("theme")
    if theme in THEMES:
        session['theme'] = theme
        neon, muted = get_theme_colors(theme)
        return jsonify({"ok": True, "theme": theme, "neon": neon, "muted": muted})
    return jsonify({"error": "invalid theme"}), 400

# --- HTML Templates ---

LOGIN_TEMPLATE = r"""

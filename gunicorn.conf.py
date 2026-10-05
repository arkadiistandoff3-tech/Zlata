import os

# This app keeps REMOTE_CLIENTS/jobs in the Python process, so use one worker.
# gthread is supported by Flask-Sock and lets many WebSocket connections share
# the worker through threads.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "100"))

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
timeout = 0
graceful_timeout = int(os.environ.get("GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("KEEPALIVE", "10"))

# Render-friendly logs. Client code itself remains quiet/no print().
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Don't preload: keep startup/import side effects isolated to the worker.
preload_app = False

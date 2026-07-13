"""
Gunicorn configuration for production deployment
"""

import multiprocessing

# Server socket
bind = "127.0.0.1:8000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 300
keepalive = 2

# Logging
accesslog = "/var/log/partsbin/access.log"
errorlog = "/var/log/partsbin/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "partsbin"

# Server mechanics
daemon = False
pidfile = "/run/partsbin/partsbin.pid"
user = None
group = None
tmp_upload_dir = None

"""Gunicorn configuration — International Road Services – Libya.

Started by systemd (deploy/systemd/irs-road.service):
    /opt/irs-road/venv/bin/gunicorn -c /opt/irs-road/app/deploy/gunicorn.conf.py wsgi:app
"""
import multiprocessing
import os

# Dedicated Unix socket → no TCP port conflicts with other applications on the server
bind = os.environ.get("GUNICORN_BIND", "unix:/run/irs-road/gunicorn.sock")
umask = 0o007  # socket readable by group (www-data is added to the irsroad group)

workers = int(os.environ.get("GUNICORN_WORKERS", min(4, multiprocessing.cpu_count() * 2 + 1)))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 2))
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
preload_app = False

accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "/var/log/irs-road/gunicorn-access.log")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "/var/log/irs-road/gunicorn-error.log")
loglevel = "info"
access_log_format = '%({x-real-ip}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(L)ss "%(a)s"'
proc_name = "irs-road"
forwarded_allow_ips = "127.0.0.1"
limit_request_line = 8190

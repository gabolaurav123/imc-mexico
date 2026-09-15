"""Supervise the web and durable worker in one persistent-volume container.

Seenode volumes cannot be shared by services. A single replica intentionally owns
both child processes. A failed child terminates the container so the host restarts
it; jobs are recovered from PostgreSQL leases. No local computer is required.
"""
import os
import signal
import subprocess
import sys
import time

children=[]
stopping=False

def stop(signum=None,frame=None):
    global stopping
    stopping=True
    for child in children:
        if child.poll() is None:child.terminate()

def main():
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    # Exactly one migrator, guarded on the direct Postgres connection even if two
    # revisions overlap during deployment. Never reset a database on startup.
    subprocess.run([sys.executable,'deploy.py'],check=True)
    port=str(int(os.environ.get('PORT','8000')))
    commands=[
        [sys.executable,'-m','gunicorn','config.wsgi:application','--bind',f'0.0.0.0:{port}','--workers',os.environ.get('WEB_WORKERS','1'),'--threads',os.environ.get('WEB_THREADS','1'),'--timeout','240','--access-logfile','-','--error-logfile','-','--access-logformat','%(m)s %(s)s %(L)s'],
        [sys.executable,'manage.py','runworker'],
        [sys.executable,'manage.py','backup_private','--daemon'],
    ]
    for command in commands:children.append(subprocess.Popen(command))
    try:
        while not stopping:
            if any(child.poll() is not None for child in children):
                stop();return 1
            time.sleep(1)
    finally:
        stop()
        for child in children:
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:child.kill()
    return 0

if __name__=='__main__':sys.exit(main())

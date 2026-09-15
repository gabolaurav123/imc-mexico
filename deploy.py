"""Serialized, non-destructive schema upgrades using a direct Neon connection."""
import os
import subprocess
import sys
from pathlib import Path
import psycopg
from dotenv import load_dotenv

def main():
    load_dotenv()
    direct=os.environ.get('DIRECT_URL') or os.environ['DATABASE_URL']
    environment={**os.environ,'DATABASE_URL':direct}
    with psycopg.connect(direct,autocommit=True) as connection:
        connection.execute('SELECT pg_advisory_lock(731950215)')
        try:
            subprocess.run([sys.executable,'manage.py','migrate','--noinput'],env=environment,check=True)
            subprocess.run([sys.executable,'manage.py','seed'],env=environment,check=True)
        finally:connection.execute('SELECT pg_advisory_unlock(731950215)')
    media=Path(os.environ.get('MEDIA_ROOT','media'))
    media.mkdir(parents=True,exist_ok=True)

if __name__=='__main__':main()

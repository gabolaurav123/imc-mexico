#!/usr/bin/env bash
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core postgresql-client
python -m pip install --no-cache-dir -r requirements.txt
python manage.py collectstatic --noinput
python manage.py check --deploy --fail-level ERROR

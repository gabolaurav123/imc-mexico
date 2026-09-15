#!/usr/bin/env bash
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl ffmpeg fonts-dejavu-core
# Official PGDG repository, scoped signing key. The Neon server uses PostgreSQL 18;
# a distribution's older pg_dump cannot export a newer server.
. /etc/os-release
pg_codename="${VERSION_CODENAME:-}"
if [[ ! "$pg_codename" =~ ^[a-z]+$ ]]; then
    echo "The base image must provide a supported Debian/Ubuntu VERSION_CODENAME." >&2
    exit 1
fi
install -d -m 0755 /usr/share/postgresql-common/pgdg
curl --fail --show-error --silent --retry 3 --proto '=https' --tlsv1.2 \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    --output /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
chmod 0644 /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
pg_architecture="$(dpkg --print-architecture)"
cat > /etc/apt/sources.list.d/pgdg.sources <<EOF
Types: deb
URIs: https://apt.postgresql.org/pub/repos/apt
Suites: ${pg_codename}-pgdg
Architectures: ${pg_architecture}
Components: main
Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
EOF
apt-get update
apt-get install -y --no-install-recommends postgresql-client-18
pg_dump --version
python -m pip install --no-cache-dir -r requirements.txt
python manage.py collectstatic --noinput
python manage.py check --deploy --fail-level ERROR

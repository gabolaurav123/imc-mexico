"""Private PostgreSQL + referenced media backups; never restores destructively."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timedelta, timezone
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from portal.storage import PrivateStorage, option


def hash_stream(stream):
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def verify_backup(path):
    """Validate archive contents without extracting or trusting tar member paths."""
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise CommandError("La copia contiene entradas duplicadas.")
        for member in members:
            parts = PurePosixPath(member.name).parts
            if not member.isfile() or member.name.startswith("/") or ".." in parts or "\\" in member.name or ":" in member.name:
                raise CommandError("La copia contiene una ruta no permitida.")
        manifest_member = archive.getmember("manifest.json")
        if manifest_member.size > 20 * 1024 * 1024:
            raise CommandError("El manifiesto de respaldo supera el tamaño permitido.")
        manifest = json.load(archive.extractfile(manifest_member))
        if manifest.get("schema_version") != 1:
            raise CommandError("Versión de manifiesto no compatible.")
        entries = [manifest["database"], *manifest["media"]]
        if set(names) != {"manifest.json", *(entry["path"] for entry in entries)}:
            raise CommandError("El contenido no coincide con el manifiesto de respaldo.")
        for entry in entries:
            with archive.extractfile(entry["path"]) as stream:
                checksum, size = hash_stream(stream)
            if checksum != entry["sha256"] or size != entry["size"]:
                raise CommandError("La verificación de integridad del respaldo falló.")
        return manifest


def postgres_environment(connection_info, passfile):
    """Credentials stay in a chmod-600 pgpass file, never command arguments."""
    def escape(value):
        return str(value).replace("\\", "\\\\").replace(":", "\\:")
    host = connection_info.get("host", "localhost")
    port = connection_info.get("port", "5432")
    database = connection_info.get("dbname", "postgres")
    user = connection_info.get("user", "postgres")
    password = connection_info.get("password", "")
    passfile.write_text(":".join(escape(v) for v in [host, port, database, user, password]) + "\n", encoding="utf-8")
    passfile.chmod(0o600)
    # Do not inherit any libpq credential/target override from the invoking process.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    environment.update(PGHOST=str(host), PGPORT=str(port), PGDATABASE=str(database), PGUSER=str(user),
                       PGPASSFILE=str(passfile), PGCONNECT_TIMEOUT="20")
    for key, env_name in {"sslmode": "PGSSLMODE", "channel_binding": "PGCHANNELBINDING",
                          "sslrootcert": "PGSSLROOTCERT"}.items():
        if connection_info.get(key):
            environment[env_name] = str(connection_info[key])
    return environment


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def _external_copy(path, checksum):
    bucket = option("BACKUP_S3_BUCKET", "")
    if not bucket:
        return None
    import boto3
    from botocore.config import Config
    client = boto3.client("s3", endpoint_url=option("BACKUP_S3_ENDPOINT_URL") or None,
                          region_name=option("BACKUP_S3_REGION", "us-east-1") or "us-east-1",
                          aws_access_key_id=option("BACKUP_S3_ACCESS_KEY_ID") or None,
                          aws_secret_access_key=option("BACKUP_S3_SECRET_ACCESS_KEY") or None,
                          config=Config(connect_timeout=20, read_timeout=120,
                                        retries={"max_attempts": 3, "mode": "standard"}))
    prefix = str(option("BACKUP_S3_PREFIX", "imc-private-backups")).strip("/")
    key = f"{prefix}/{path.name}"
    extra = {"ContentType": "application/gzip", "CacheControl": "private, no-store",
             "Metadata": {"sha256": checksum}}
    encryption = option("BACKUP_S3_SSE", "AES256")
    if encryption:
        extra["ServerSideEncryption"] = encryption
    client.upload_file(str(path), bucket, key, ExtraArgs=extra)
    remote = client.head_object(Bucket=bucket, Key=key)
    if remote.get("ContentLength") != path.stat().st_size or remote.get("Metadata", {}).get("sha256") != checksum:
        raise CommandError("El destino externo no confirmó la integridad de la copia.")
    return {"bucket": bucket, "key": key, "size_confirmed": True}


def create_backup(directory, keep_days=7):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    direct = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not direct:
        raise CommandError("Configura DIRECT_URL de PostgreSQL para las copias de seguridad.")
    pg_dump = shutil.which(str(option("PG_DUMP_BINARY", "pg_dump")))
    if not pg_dump:
        raise CommandError("Falta pg_dump. Instala un cliente PostgreSQL compatible con la versión del servidor.")
    directory = Path(directory).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if directory == media_root or directory.is_relative_to(media_root):
        raise CommandError("BACKUP_DIR debe estar separado de MEDIA_ROOT.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    now = datetime.now(timezone.utc)
    name = f"imc-private-{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}.tar.gz"
    target = directory / name
    storage = PrivateStorage()
    with psycopg.connect(direct, autocommit=True, connect_timeout=20) as database:
        if not database.execute("SELECT pg_try_advisory_lock(731950216)").fetchone()[0]:
            raise CommandError("Otra copia de seguridad está en curso.")
        try:
            database.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot = database.execute("SELECT pg_export_snapshot()").fetchone()[0]
            rows = database.execute("SELECT original, preview FROM portal_asset").fetchall()
            names = sorted({str(name) for row in rows for name in row if name})
            tables = [row[0] for row in database.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
            table_counts = {table: database.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", table))).fetchone()[0]
                            for table in tables}
            sizes = {name: storage.size(name) for name in names}
            db_size = database.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            # Database.dump + archive coexist temporarily; do not consume the web's last disk space.
            required = sum(sizes.values()) + 2 * db_size + 200 * 1024 * 1024
            if shutil.disk_usage(directory).free < required:
                raise CommandError("No hay espacio suficiente para completar una copia segura.")
            with tempfile.TemporaryDirectory(prefix=".imc-backup-", dir=directory) as temporary:
                work = Path(temporary)
                work.chmod(0o700)
                dump = work / "database.dump"
                environment = postgres_environment(conninfo_to_dict(direct), work / ".pgpass")
                result = subprocess.run([pg_dump, "--format=custom", "--no-owner", "--no-acl", "--no-password",
                                         f"--snapshot={snapshot}", f"--file={dump}"],
                                        env=environment, capture_output=True, timeout=1800)
                if result.returncode:
                    raise CommandError("pg_dump no completó la copia. Comprueba conexión, permisos y versión del cliente; no se ha publicado un respaldo.")
                dump.chmod(0o600)
                with dump.open("rb") as stream:
                    if stream.read(5) != b"PGDMP":
                        raise CommandError("El archivo generado no es un respaldo PostgreSQL válido.")
                    stream.seek(0)
                    checksum, size = hash_stream(stream)
                manifest = {"schema_version": 1, "created_at": now.isoformat(),
                            "database": {"path": "database.dump", "sha256": checksum, "size": size},
                            "media": [], "storage": "s3" if storage.bucket else "local",
                            "table_counts": table_counts,
                            "release": os.environ.get("RELEASE_SHA", "not-recorded")}
                archive_path = work / "backup.tar.gz"
                with tarfile.open(archive_path, "w:gz", compresslevel=1) as archive:
                    archive.add(dump, arcname="database.dump", recursive=False)
                    for filename in names:
                        filename = storage.safe_name(filename)
                        member = tarfile.TarInfo("media/" + filename)
                        member.size, member.mode, member.mtime = sizes[filename], 0o600, int(now.timestamp())
                        with storage.open(filename, "rb") as stream:
                            reader = HashingReader(stream)
                            archive.addfile(member, reader)
                        manifest["media"].append({"path": member.name, "size": member.size,
                                                  "sha256": reader.digest.hexdigest()})
                    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                    info = tarfile.TarInfo("manifest.json")
                    info.size, info.mode, info.mtime = len(payload), 0o600, int(now.timestamp())
                    archive.addfile(info, io.BytesIO(payload))
                archive_path.chmod(0o600)
                verify_backup(archive_path)
                archive_path.replace(target)
            database.execute("COMMIT")
        finally:
            if database.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                database.execute("ROLLBACK")
            database.execute("SELECT pg_advisory_unlock(731950216)")
    with target.open("rb") as stream:
        checksum, size = hash_stream(stream)
    external = _external_copy(target, checksum)
    status = {"created_at": now.isoformat(), "filename": target.name, "sha256": checksum,
              "size": size, "media_files": len(names), "external_copy": external,
              "state": "external_verified" if external else "local_only"}
    status_path = directory / "last-success.json"
    temporary_status = directory / ".last-success.tmp"
    temporary_status.write_text(json.dumps(status, indent=2), encoding="utf-8")
    temporary_status.chmod(0o600)
    temporary_status.replace(status_path)
    cutoff = now - timedelta(days=max(1, keep_days))
    for old in directory.glob("imc-private-*.tar.gz"):
        # Flat, verified backup directory only. Never traverse media or follow links.
        if old != target and not old.is_symlink() and old.resolve().parent == directory:
            if datetime.fromtimestamp(old.stat().st_mtime, timezone.utc) < cutoff:
                old.unlink()
    return status


class Command(BaseCommand):
    help = "Copia privada verificada de PostgreSQL y archivos, con destino S3 externo opcional."

    def add_arguments(self, parser):
        parser.add_argument("--directory", default=str(option("BACKUP_DIR", "/data/backups")))
        parser.add_argument("--keep-days", type=int, default=int(option("BACKUP_RETENTION_DAYS", 7)))
        parser.add_argument("--daemon", action="store_true")
        parser.add_argument("--interval-hours", type=float, default=float(option("BACKUP_INTERVAL_HOURS", 24)))
        parser.add_argument("--verify", metavar="ARCHIVE", help="Verifica un respaldo sin restaurar ni extraer archivos.")

    def handle(self, *args, **options):
        if options["verify"]:
            try:
                manifest = verify_backup(options["verify"])
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError(f"No se pudo verificar la copia ({type(exc).__name__}).") from None
            self.stdout.write(self.style.SUCCESS(f"Integridad verificada: base de datos y {len(manifest['media'])} archivos privados."))
            return
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        if options["daemon"]:
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
        interval = max(3600, options["interval_hours"] * 3600)
        next_attempt = 0
        while not stopping:
            try:
                status_path = Path(options["directory"]) / "last-success.json"
                last = json.loads(status_path.read_text()) if status_path.exists() else {}
                due = not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds() >= interval
                if (not options["daemon"] or due) and time.monotonic() >= next_attempt:
                    status = create_backup(options["directory"], options["keep_days"])
                    self.stdout.write(self.style.SUCCESS(f"Respaldo verificado: {status['filename']} ({status['state']})."))
                    if not options["daemon"]:
                        return
            except Exception as exc:
                if not options["daemon"]:
                    if isinstance(exc, CommandError):
                        raise
                    raise CommandError(f"No se pudo completar el respaldo ({type(exc).__name__}).") from None
                # Provider errors/connection strings never enter logs.
                self.stderr.write(f"Backup: falló el respaldo ({type(exc).__name__}); se reintentará en una hora.")
                next_attempt = time.monotonic() + 3600
            time.sleep(30)

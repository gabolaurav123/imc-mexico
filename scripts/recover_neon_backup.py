#!/usr/bin/env python3
"""Restore one verified private archive into an empty PostgreSQL target.

This command is deliberately opt-in: it needs both RECOVERY_TARGET_URL and the
SHA-256 of the exact archive to use.  It never reads .env, deletes data, or
prints a connection string, archive paths, media names, or manifest contents.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

try:  # Works both as ``python scripts/...`` and ``python -m scripts...``.
    from .recovery_inventory import ARCHIVE_NAME, inspect_archive, regular_file, sha256_stream
except ImportError:  # pragma: no cover - exercised by the production invocation form.
    from recovery_inventory import ARCHIVE_NAME, inspect_archive, regular_file, sha256_stream


SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RECEIPT_PREFIX = "imc-recovery-receipt-"


class RecoveryError(RuntimeError):
    pass


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RecoveryError(f"Falta la variable requerida {name}.")
    return value


def backup_candidates(directory: Path, expected_sha256: str) -> list[Path]:
    """Select files only by a full-content SHA-256, never by a supplied path."""
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise RecoveryError("No se puede leer el directorio privado de respaldos.") from exc
    matches = []
    for entry in entries:
        if not ARCHIVE_NAME.fullmatch(entry.name) or regular_file(entry) is None:
            continue
        try:
            with entry.open("rb") as stream:
                actual, _ = sha256_stream(stream)
        except OSError:
            continue
        if actual == expected_sha256:
            matches.append(entry)
    return matches


def verified_manifest(archive: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    """Use the no-extraction verifier and return its already-validated manifest."""
    # inspect_archive performs the same full member/hash validation but purposefully
    # hides member names in its result.  Re-open only after it reports success.
    inspected = inspect_archive(archive)
    if inspected.get("integrity") != "verified" or (expected_sha256 and inspected.get("archive_sha256") != expected_sha256):
        raise RecoveryError("El respaldo seleccionado no supera la verificación de integridad.")
    import tarfile
    try:
        with tarfile.open(archive, "r:gz") as tar:
            stream = tar.extractfile("manifest.json")
            if stream is None:
                raise RecoveryError("El respaldo no contiene un manifiesto válido.")
            with stream:
                manifest = json.load(stream)
    except (OSError, json.JSONDecodeError, KeyError, tarfile.TarError) as exc:
        raise RecoveryError("No se puede leer el manifiesto validado.") from exc
    return manifest


def target_fingerprint(connection: dict[str, str]) -> str:
    """Persist a non-secret target identity for safe retry detection."""
    fields = [connection.get(key, "") for key in ("host", "port", "dbname", "user", "sslmode")]
    return hashlib.sha256("\0".join(fields).encode("utf-8")).hexdigest()


def private_pg_environment(connection: dict[str, str], passfile: Path) -> dict[str, str]:
    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace(":", "\\:")

    host = connection.get("host", "localhost")
    port = connection.get("port", "5432")
    database = connection.get("dbname", "postgres")
    user = connection.get("user", "postgres")
    password = connection.get("password", "")
    passfile.write_text(":".join(escape(value) for value in (host, port, database, user, password)) + "\n", encoding="utf-8")
    passfile.chmod(0o600)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update({"PGHOST": host, "PGPORT": port, "PGDATABASE": database, "PGUSER": user,
                        "PGPASSFILE": str(passfile), "PGCONNECT_TIMEOUT": "20"})
    for source, destination in (("sslmode", "PGSSLMODE"), ("channel_binding", "PGCHANNELBINDING"),
                                ("sslrootcert", "PGSSLROOTCERT")):
        if connection.get(source):
            environment[destination] = connection[source]
    return environment


def target_is_empty(target_url: str) -> bool:
    try:
        with psycopg.connect(target_url, connect_timeout=20, autocommit=True) as connection:
            row = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
    except psycopg.Error as exc:
        raise RecoveryError("No se pudo comprobar la base de destino.") from exc
    return bool(row and row[0] == 0)


@contextmanager
def recovery_lock(target_url: str):
    """Serialize recoveries that target the same PostgreSQL database."""
    try:
        with psycopg.connect(target_url, connect_timeout=20, autocommit=True) as connection:
            locked = connection.execute("SELECT pg_try_advisory_lock(731950217)").fetchone()
            if not locked or not locked[0]:
                raise RecoveryError("Otra recuperación ya está en curso para este destino.")
            try:
                yield
            finally:
                connection.execute("SELECT pg_advisory_unlock(731950217)")
    except RecoveryError:
        raise
    except psycopg.Error as exc:
        raise RecoveryError("No se pudo adquirir el bloqueo de recuperación.") from exc


def compare_table_counts(target_url: str, expected: dict[str, int]) -> bool:
    try:
        with psycopg.connect(target_url, connect_timeout=20, autocommit=True) as connection:
            actual_names = {row[0] for row in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()}
            if actual_names != set(expected):
                return False
            for table, count in expected.items():
                row = connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", table))).fetchone()
                if row is None or row[0] != count:
                    return False
    except psycopg.Error as exc:
        raise RecoveryError("No se pudieron comprobar los conteos restaurados.") from exc
    return True


def safe_media_destination(root: Path, archive_name: str) -> Path:
    """Map an already-validated media member without allowing a filesystem escape."""
    pure = PurePosixPath(archive_name)
    if (pure.parts[:1] != ("media",) or len(pure.parts) < 2 or ".." in pure.parts
            or archive_name.startswith("/") or "\\" in archive_name or ":" in archive_name):
        raise RecoveryError("El respaldo contiene una ruta de medio no permitida.")
    relative = Path(*pure.parts[1:])
    try:
        root_resolved = root.resolve(strict=True)
        destination = root_resolved.joinpath(relative)
        destination.relative_to(root_resolved)
    except (OSError, ValueError):
        raise RecoveryError("MEDIA_ROOT no es un directorio privado disponible.") from None
    current = root_resolved
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise RecoveryError("MEDIA_ROOT contiene un enlace no permitido.")
    if destination.is_symlink():
        raise RecoveryError("MEDIA_ROOT contiene un enlace no permitido.")
    return destination


def existing_matches(path: Path, expected_sha256: str, expected_size: int) -> bool:
    info = regular_file(path)
    if info is None or info.st_size != expected_size:
        return False
    try:
        with path.open("rb") as stream:
            actual, size = sha256_stream(stream)
    except OSError:
        return False
    return size == expected_size and actual == expected_sha256


def restore_missing_media(archive: Path, manifest: dict[str, Any], media_root: Path) -> tuple[int, int]:
    """Copy only absent members. Existing bytes must already match their hash."""
    if not media_root.exists():
        media_root.mkdir(parents=True, mode=0o700)
    if media_root.is_symlink() or not media_root.is_dir():
        raise RecoveryError("MEDIA_ROOT no es un directorio privado disponible.")
    media_root.chmod(0o700)
    planned: list[tuple[dict[str, Any], Path]] = []
    for entry in manifest["media"]:
        destination = safe_media_destination(media_root, entry["path"])
        if destination.exists():
            if not existing_matches(destination, entry["sha256"], entry["size"]):
                raise RecoveryError("Existe un medio diferente; la recuperación no sobrescribe archivos.")
        else:
            planned.append((entry, destination))
    restored = existing = 0
    import tarfile
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for entry, destination in planned:
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if destination.exists():
                    raise RecoveryError("El destino de medios cambió durante la recuperación.")
                stream = tar.extractfile(entry["path"])
                if stream is None:
                    raise RecoveryError("No se pudo leer un medio verificado.")
                temporary = destination.with_name("." + destination.name + ".recovery-tmp")
                if temporary.exists():
                    raise RecoveryError("Existe un archivo temporal de recuperación; requiere revisión manual.")
                digest = hashlib.sha256()
                size = 0
                try:
                    with stream, temporary.open("xb") as output:
                        temporary.chmod(0o600)
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            output.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                        temporary.unlink(missing_ok=True)
                        raise RecoveryError("Un medio no coincide con el manifiesto validado.")
                    temporary.replace(destination)
                    restored += 1
                except Exception:
                    if temporary.exists():
                        temporary.unlink(missing_ok=True)
                    raise
    except (OSError, tarfile.TarError) as exc:
        raise RecoveryError("No se pudieron restaurar los medios faltantes.") from exc
    existing = len(manifest["media"]) - restored
    return restored, existing


def receipt_path(backup_dir: Path, archive_sha256: str) -> Path:
    return backup_dir / f"{RECEIPT_PREFIX}{archive_sha256}.json"


def read_receipt(path: Path) -> dict[str, Any] | None:
    info = regular_file(path)
    if info is None or info.st_size > 8192:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    if path.exists() or temporary.exists():
        raise RecoveryError("Ya existe un recibo de recuperación; no se sobrescribe.")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, sort_keys=True))
        temporary.chmod(0o600)
        temporary.replace(path)
    except OSError as exc:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise RecoveryError("No se pudo guardar el recibo privado de recuperación.") from exc


def restore_database(archive: Path, connection: dict[str, str], backup_dir: Path) -> None:
    binary = shutil.which(os.environ.get("PG_RESTORE_BINARY", "pg_restore"))
    if not binary:
        raise RecoveryError("No se encontró pg_restore compatible.")
    import tarfile
    try:
        with tempfile.TemporaryDirectory(prefix=".imc-recovery-", dir=backup_dir) as temporary_dir:
            temporary = Path(temporary_dir)
            temporary.chmod(0o700)
            dump_path = temporary / "database.dump"
            with tarfile.open(archive, "r:gz") as tar:
                stream = tar.extractfile("database.dump")
                if stream is None:
                    raise RecoveryError("No se pudo leer la base validada.")
                with stream, dump_path.open("xb") as output:
                    shutil.copyfileobj(stream, output, length=1024 * 1024)
            dump_path.chmod(0o600)
            passfile = temporary / ".pgpass"
            result = subprocess.run([binary, "--no-owner", "--no-acl", "--exit-on-error", "--single-transaction",
                                     "--dbname", connection.get("dbname", "postgres"), str(dump_path)],
                                    env=private_pg_environment(connection, passfile), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        raise RecoveryError("pg_restore no pudo completar la restauración.") from exc
    if result.returncode != 0:
        raise RecoveryError("pg_restore no pudo completar la restauración.")


def run_recovery(backup_dir: Path, media_root: Path) -> dict[str, Any]:
    target_url = required_environment("RECOVERY_TARGET_URL")
    archive_sha256 = required_environment("RECOVERY_BACKUP_SHA256").lower()
    if not SHA256.fullmatch(archive_sha256):
        raise RecoveryError("RECOVERY_BACKUP_SHA256 debe tener 64 caracteres hexadecimales.")
    matches = backup_candidates(backup_dir, archive_sha256)
    if len(matches) != 1:
        raise RecoveryError("No se encontró exactamente un respaldo local con el SHA-256 indicado.")
    archive = matches[0]
    manifest = verified_manifest(archive, archive_sha256)
    try:
        connection = conninfo_to_dict(target_url)
    except Exception as exc:
        raise RecoveryError("RECOVERY_TARGET_URL no tiene un formato PostgreSQL válido.") from exc
    fingerprint = target_fingerprint(connection)
    expected_counts = manifest["table_counts"]
    with recovery_lock(target_url):
        receipt = read_receipt(receipt_path(backup_dir, archive_sha256))
        if receipt is not None:
            if receipt.get("backup_sha256") != archive_sha256 or receipt.get("target_fingerprint") != fingerprint:
                raise RecoveryError("El recibo existente corresponde a otro respaldo o destino.")
            if not compare_table_counts(target_url, expected_counts):
                raise RecoveryError("El recibo existe pero los conteos del destino no coinciden.")
            return {"state": "already_restored_verified", "archive_sha256": archive_sha256,
                    "table_count": len(expected_counts), "media_count": len(manifest["media"])}
        if not target_is_empty(target_url):
            raise RecoveryError("El destino no está vacío; la recuperación se cancela sin sobrescribir datos.")
        restored_media, existing_media = restore_missing_media(archive, manifest, media_root)
        restore_database(archive, connection, backup_dir)
        if not compare_table_counts(target_url, expected_counts):
            raise RecoveryError("Los conteos restaurados no coinciden; no se escribió recibo.")
        receipt = {"schema_version": 1, "backup_sha256": archive_sha256, "target_fingerprint": fingerprint,
                   "restored_at": datetime.now(timezone.utc).isoformat(), "table_count": len(expected_counts),
                   "media_count": len(manifest["media"]), "restored_media": restored_media,
                   "existing_media": existing_media}
        write_receipt(receipt_path(backup_dir, archive_sha256), receipt)
        return {"state": "restored_verified", "archive_sha256": archive_sha256,
                "table_count": len(expected_counts), "media_count": len(manifest["media"]),
                "restored_media": restored_media, "existing_media": existing_media}


def main() -> int:
    backup_dir = Path(os.environ.get("BACKUP_DIR", "/data/backups"))
    media_root = Path(os.environ.get("MEDIA_ROOT", "/data/media"))
    try:
        summary = run_recovery(backup_dir, media_root)
    except RecoveryError as exc:
        print(json.dumps({"state": "not_restored", "reason": str(exc)}, sort_keys=True))
        return 2
    except Exception:
        # Do not allow library exceptions to disclose a URL, filesystem path, or
        # provider response in SeeNode logs.
        print(json.dumps({"state": "not_restored", "reason": "fallo interno de recuperación"}, sort_keys=True))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

from contextlib import nullcontext
import hashlib
import io
import json
import subprocess
from pathlib import Path
import tarfile
from unittest.mock import patch

import pytest
from psycopg.conninfo import conninfo_to_dict

from scripts.recover_neon_backup import (
    RecoveryError,
    backup_candidates,
    receipt_path,
    restore_database,
    restore_missing_media,
    run_recovery,
    safe_media_destination,
    target_fingerprint,
    verified_manifest,
)


def make_archive(directory: Path) -> tuple[Path, str]:
    database = b"PGDMP-fixture"
    media = b"fixture-image"
    manifest = {
        "schema_version": 1,
        "created_at": "2026-09-15T23:32:05+00:00",
        "database": {"path": "database.dump", "size": len(database), "sha256": hashlib.sha256(database).hexdigest()},
        "media": [{"path": "media/machines/1/test.jpg", "size": len(media), "sha256": hashlib.sha256(media).hexdigest()}],
        "table_counts": {"portal_asset": 1},
    }
    archive = directory / "imc-private-20260915T233205Z-a80505.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload in [("database.dump", database), ("media/machines/1/test.jpg", media),
                              ("manifest.json", json.dumps(manifest).encode("utf-8"))]:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_exact_hash_selects_only_the_matching_private_archive(tmp_path):
    archive, checksum = make_archive(tmp_path)

    assert backup_candidates(tmp_path, checksum) == [archive]
    assert backup_candidates(tmp_path, "0" * 64) == []


def test_media_restore_writes_only_missing_verified_files(tmp_path):
    archive, _ = make_archive(tmp_path)
    manifest = verified_manifest(archive)
    media_root = tmp_path / "media"

    restored, existing = restore_missing_media(archive, manifest, media_root)
    assert (restored, existing) == (1, 0)
    restored, existing = restore_missing_media(archive, manifest, media_root)
    assert (restored, existing) == (0, 1)


def test_media_restore_refuses_to_overwrite_different_existing_bytes(tmp_path):
    archive, _ = make_archive(tmp_path)
    manifest = verified_manifest(archive)
    path = tmp_path / "media" / "machines" / "1" / "test.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"different")

    with pytest.raises(RecoveryError, match="no sobrescribe"):
        restore_missing_media(archive, manifest, tmp_path / "media")


def test_matching_private_receipt_retries_by_validation_without_restoring(tmp_path, monkeypatch):
    _, checksum = make_archive(tmp_path)
    target = "postgresql://recovery@example.invalid/recovery"
    fingerprint = target_fingerprint(conninfo_to_dict(target))
    receipt_path(tmp_path, checksum).write_text(json.dumps({
        "backup_sha256": checksum,
        "target_fingerprint": fingerprint,
    }), encoding="utf-8")
    monkeypatch.setenv("RECOVERY_TARGET_URL", target)
    monkeypatch.setenv("RECOVERY_BACKUP_SHA256", checksum)
    monkeypatch.setattr("scripts.recover_neon_backup.recovery_lock", lambda *_: nullcontext())
    monkeypatch.setattr("scripts.recover_neon_backup.compare_table_counts", lambda *_: True)
    monkeypatch.setattr("scripts.recover_neon_backup.target_is_empty", lambda *_: pytest.fail("must not re-check or restore"))
    monkeypatch.setattr("scripts.recover_neon_backup.restore_database", lambda *_: pytest.fail("must not restore"))

    result = run_recovery(tmp_path, tmp_path / "media")

    assert result["state"] == "already_restored_verified"


def test_nonempty_target_aborts_before_media_or_pg_restore(tmp_path, monkeypatch):
    _, checksum = make_archive(tmp_path)
    monkeypatch.setenv("RECOVERY_TARGET_URL", "postgresql://recovery@example.invalid/recovery")
    monkeypatch.setenv("RECOVERY_BACKUP_SHA256", checksum)
    monkeypatch.setattr("scripts.recover_neon_backup.recovery_lock", lambda *_: nullcontext())
    monkeypatch.setattr("scripts.recover_neon_backup.target_is_empty", lambda *_: False)
    monkeypatch.setattr("scripts.recover_neon_backup.restore_missing_media", lambda *_: pytest.fail("must not copy media"))
    monkeypatch.setattr("scripts.recover_neon_backup.restore_database", lambda *_: pytest.fail("must not run pg_restore"))

    with pytest.raises(RecoveryError, match="no está vacío"):
        run_recovery(tmp_path, tmp_path / "media")


def test_invalid_or_nonmatching_checksum_aborts_before_any_target_operation(tmp_path, monkeypatch):
    _, checksum = make_archive(tmp_path)
    monkeypatch.setenv("RECOVERY_TARGET_URL", "postgresql://recovery@example.invalid/recovery")
    monkeypatch.setattr("scripts.recover_neon_backup.recovery_lock", lambda *_: pytest.fail("must not contact target"))
    monkeypatch.setenv("RECOVERY_BACKUP_SHA256", "not-a-checksum")
    with pytest.raises(RecoveryError, match="64 caracteres"):
        run_recovery(tmp_path, tmp_path / "media")
    monkeypatch.setenv("RECOVERY_BACKUP_SHA256", "0" * 64)
    with pytest.raises(RecoveryError, match="exactamente un respaldo"):
        run_recovery(tmp_path, tmp_path / "media")
    assert checksum != "0" * 64


def test_pg_restore_uses_flags_and_private_pg_environment_without_url(tmp_path, monkeypatch):
    archive, _ = make_archive(tmp_path)
    target_url = "postgresql://recovery:placeholder@example.invalid:5432/recovery?sslmode=require"
    connection = conninfo_to_dict(target_url)
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("scripts.recover_neon_backup.shutil.which", lambda *_: "pg_restore")
    monkeypatch.setattr("scripts.recover_neon_backup.subprocess.run", fake_run)
    restore_database(archive, connection, tmp_path)

    assert {"--no-owner", "--no-acl", "--exit-on-error", "--single-transaction"}.issubset(seen["args"])
    assert target_url not in seen["args"]
    assert target_url not in seen["env"].values()
    assert "PGPASSFILE" in seen["env"]
    assert "PGPASSWORD" not in seen["env"]


def test_media_destination_rejects_traversal_and_dangling_symlinks(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    with pytest.raises(RecoveryError, match="ruta"):
        safe_media_destination(media_root, "media/../outside.jpg")
    # Windows developer-mode symlink creation is unavailable in this test host.
    # Model a dangling child explicitly: the guard must call is_symlink() even
    # when exists() would be false for that target.
    with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path.name == "machines"):
        with pytest.raises(RecoveryError, match="enlace"):
            safe_media_destination(media_root, "media/machines/test.jpg")

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

from scripts.recovery_inventory import inspect_archive, inspect_backups


def make_archive(directory: Path, *, altered: bool = False) -> Path:
    database = b"PGDMP-fixture"
    media = b"fixture-image"
    manifest = {
        "schema_version": 1,
        "created_at": "2026-09-15T23:32:05+00:00",
        "database": {"path": "database.dump", "size": len(database), "sha256": hashlib.sha256(database).hexdigest()},
        "media": [{"path": "media/test.jpg", "size": len(media), "sha256": hashlib.sha256(media).hexdigest()}],
        "table_counts": {"portal_asset": 1, "portal_machine": 2},
    }
    path = directory / "imc-private-20260915T233205Z-a80505.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in [("database.dump", database), ("media/test.jpg", b"altered" if altered else media),
                              ("manifest.json", json.dumps(manifest).encode("utf-8"))]:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return path


def test_archive_inventory_verifies_every_member_without_emitting_paths(tmp_path):
    result = inspect_archive(make_archive(tmp_path))

    assert result["integrity"] == "verified"
    assert result["media_count"] == 1
    assert result["table_counts"] == {"tables": 2, "rows_total": 3}
    assert "media/test.jpg" not in json.dumps(result)


def test_archive_with_wrong_member_hash_is_invalid(tmp_path):
    result = inspect_archive(make_archive(tmp_path, altered=True))

    assert result["integrity"] == "invalid"


def test_backup_directory_ignores_unrecognized_names(tmp_path):
    make_archive(tmp_path)
    (tmp_path / "sensitive-name.tar.gz").write_bytes(b"not a backup")

    result = inspect_backups(tmp_path)

    assert result["archive_count"] == 1
    assert "sensitive-name" not in json.dumps(result)


def test_only_latest_archive_gets_a_full_integrity_check(tmp_path):
    old = make_archive(tmp_path)
    old.rename(tmp_path / "imc-private-20260914T233205Z-a80505.tar.gz")
    old = tmp_path / "imc-private-20260914T233205Z-a80505.tar.gz"
    os.utime(old, (1, 1))
    latest = make_archive(tmp_path)

    result = inspect_backups(tmp_path)

    assert result["archives"][0]["name"] == latest.name
    assert result["archives"][0]["integrity"] == "verified"
    assert result["archives"][1]["integrity"] == "not_checked"

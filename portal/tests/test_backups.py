import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from django.core.management.base import CommandError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from portal.management.commands.backup_private import postgres_environment, verify_backup
from portal.models import Asset, Machine, User
from portal.backup_status import get_backup_status


class BackupStatusTests(SimpleTestCase):
    def test_only_summary_fields_are_returned_and_stale_copy_is_marked(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(BACKUP_DIR=folder):
            value = {"created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
                     "state": "local_only", "media_files": 10, "size": 757087,
                     "filename": "private-file", "external_copy": {"secret": "never-return"}}
            (Path(folder) / "last-success.json").write_text(json.dumps(value))
            status = get_backup_status()
            self.assertEqual(set(status), {"available", "stale", "created_at", "state", "media_files", "size"})
            self.assertTrue(status["available"])
            self.assertTrue(status["stale"])
            self.assertNotIn("private-file", str(status))
            self.assertNotIn("never-return", str(status))

    def test_missing_corrupt_or_invalid_status_is_never_success(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(BACKUP_DIR=folder):
            path = Path(folder) / "last-success.json"
            self.assertFalse(get_backup_status()["available"])
            for raw in ["not-json", "[]", "x" * 8193, json.dumps({"created_at": "2026-01-01", "state": "local_only", "media_files": 1, "size": 1}),
                        json.dumps({"created_at": datetime.now(timezone.utc).isoformat(), "state": "unknown", "media_files": 1, "size": 1})]:
                path.write_text(raw)
                self.assertFalse(get_backup_status()["available"])


class BackupTests(SimpleTestCase):
    def make_archive(self, folder, *, tampered=False, traversal=False):
        payloads = {"database.dump": b"PGDMP-test-fixture", "media/machines/test/photo.jpg": b"test-photo"}
        entries = [{"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                   for name, raw in payloads.items()]
        manifest = {"schema_version": 1, "database": entries[0], "media": entries[1:]}
        path = Path(folder) / "backup.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, raw in payloads.items():
                if tampered and name.startswith("media/"):
                    raw = b"corrupted!"
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            if traversal:
                info = tarfile.TarInfo("../../outside")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            raw = json.dumps(manifest).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
        return path

    def test_verified_manifest_matches_every_database_and_media_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = verify_backup(self.make_archive(folder))
        self.assertEqual(len(manifest["media"]), 1)

    def test_changed_media_is_not_reported_as_a_verified_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesMessage(CommandError, "integridad"):
                verify_backup(self.make_archive(folder, tampered=True))

    def test_traversal_member_is_rejected_without_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesMessage(CommandError, "ruta no permitida"):
                verify_backup(self.make_archive(folder, traversal=True))

    def test_credentials_use_private_passfile_and_no_libpq_target_inheritance(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PGPASSWORD": "wrong-password", "PGHOST": "wrong-host"}):
            path = Path(folder) / ".pgpass"
            environment = postgres_environment({"host": "db.example.invalid", "dbname": "app", "port": "5432",
                                                "user": "appuser", "password": "value:with\\slashes", "sslmode": "require"}, path)
            self.assertNotIn("PGPASSWORD", environment)
            self.assertEqual(environment["PGHOST"], "db.example.invalid")
            self.assertEqual(environment["PGSSLMODE"], "require")
            self.assertIn("value\\:with\\\\slashes", path.read_text())
            self.assertEqual(environment["PGPASSFILE"], str(path))


@override_settings(PRIVATE_S3_BUCKET="")
class TestMediaImportTests(TestCase):
    def test_import_only_existing_test_records_and_never_overwrites_different_bytes(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=str(Path(folder) / "media")):
            user = User.objects.create_user(email="synthetic-fixture@example.invalid", is_test=False)
            machine = Machine.objects.create(owner=user)
            key = f"machines/{machine.pk}/synthetic.jpg"
            raw = b"SYNTHETIC TEST FILE ONLY"
            asset = Asset.objects.create(machine=machine, original=key, kind="image", mime_type="image/jpeg",
                                         sha256=hashlib.sha256(raw).hexdigest(), size=len(raw), processing_status="ready")
            manifest = {"purpose": "imc-synthetic-test-media-v1", "files": [
                {"path": key, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]}
            archive_path = Path(folder) / "synthetic-test.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for name, payload in [(key, raw), ("manifest.json", json.dumps(manifest).encode())]:
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            with self.assertRaisesMessage(CommandError, "registro de ensayo"):
                call_command("import_test_media", str(archive_path), stdout=io.StringIO())
            self.assertFalse(asset.original.storage.exists(key))
            user.is_test = True
            user.save()
            call_command("import_test_media", str(archive_path), stdout=io.StringIO())
            with asset.original.open("rb") as stream:
                self.assertEqual(stream.read(), raw)
            call_command("import_test_media", str(archive_path), stdout=io.StringIO())
            Path(asset.original.path).write_bytes(b"different-existing-content")
            with self.assertRaisesMessage(CommandError, "No se reemplazó"):
                call_command("import_test_media", str(archive_path), stdout=io.StringIO())
            self.assertEqual(Path(asset.original.path).read_bytes(), b"different-existing-content")

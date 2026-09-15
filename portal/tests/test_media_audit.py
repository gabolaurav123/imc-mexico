import io
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from portal.models import Asset, Machine, MachineVersion, User


@override_settings(PRIVATE_S3_BUCKET="")
class MediaAuditTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="imc-audit-test-")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "private-media"
        self.root.mkdir()
        self.override = override_settings(MEDIA_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user(email="audit@example.invalid")
        self.machine = Machine.objects.create(owner=self.user)

    def file(self, name, old=True):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audit-test")
        if old:
            stamp = time.time() - 30 * 86400
            os.utime(path, (stamp, stamp))
        return path

    def command(self, *args):
        output = io.StringIO()
        call_command("audit_media", *args, stdout=output)
        return json.loads(output.getvalue())

    def test_report_then_apply_preserves_referenced_versions_and_recent_files(self):
        original = self.file("machines/retained/original.jpg")
        preview = self.file("machines/retained/preview.jpg")
        asset = Asset.objects.create(machine=self.machine, original=original.relative_to(self.root).as_posix(),
                                     preview=preview.relative_to(self.root).as_posix(), kind="image")
        MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.user,
                                      data={"asset_ids": [str(asset.pk)]})
        old = self.file("machines/deleted/old.jpg")
        recent = self.file("temporary/new-upload.jpg", old=False)
        report = self.command()
        self.assertEqual(report["eligible_old_files"], 1)
        self.assertTrue(old.exists())
        report = self.command("--apply", "--older-than", "7")
        self.assertEqual(report["deleted_files"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(original.exists())
        self.assertTrue(preview.exists())
        self.assertTrue(recent.exists())
        self.assertEqual(MachineVersion.objects.count(), 1)
        self.assertEqual(Asset.objects.count(), 1)

    def test_referenced_again_between_inventory_and_deletion_is_preserved(self):
        target = self.file("machines/reinstated/photo.jpg")
        from portal.management.commands import audit_media
        real_check = audit_media.safe_current_file

        def mark_referenced(path, root):
            Asset.objects.create(machine=self.machine, original=path.relative_to(root).as_posix(), kind="image")
            return real_check(path, root)

        with patch.object(audit_media, "safe_current_file", side_effect=mark_referenced):
            report = self.command("--apply")
        self.assertTrue(target.exists())
        self.assertEqual(report["deleted_files"], 0)
        self.assertEqual(report["changed_or_referenced_again"], 1)

    def test_traversal_root_and_short_retention_are_rejected(self):
        with self.assertRaises(CommandError):
            self.command("--apply", "--older-than", "6")
        with override_settings(MEDIA_ROOT=self.root / ".."), self.assertRaises(CommandError):
            self.command("--apply")

    def test_symlink_targets_and_link_itself_are_never_deleted(self):
        external = Path(self.folder.name) / "outside"
        external.mkdir()
        target = external / "keep.jpg"
        target.write_bytes(b"outside-test")
        stamp = time.time() - 30 * 86400
        os.utime(target, (stamp, stamp))
        link = self.root / "linked"
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            # Windows may deny creating symlinks; exercise the same scandir branch.
            with patch("portal.management.commands.audit_media.os.scandir") as scan:
                from unittest.mock import Mock
                linked = Mock()
                linked.is_symlink.return_value = True
                linked.stat.return_value.st_file_attributes = 1024
                scan.return_value = [linked]
                report = self.command("--apply")
            self.assertEqual(report["skipped_links"], 1)
        else:
            report = self.command("--apply")
            self.assertTrue(link.is_symlink())
            self.assertEqual(report["skipped_links"], 1)
        self.assertTrue(target.exists())
        self.assertEqual(report["deleted_files"], 0)

    def test_s3_inventory_is_read_only_and_purge_refused(self):
        from datetime import datetime, timezone
        Asset.objects.create(machine=self.machine, original="kept.jpg", kind="image")
        with override_settings(PRIVATE_S3_BUCKET="private-test-bucket"), patch("portal.storage.PrivateStorage.client") as client:
            client.return_value.get_paginator.return_value.paginate.return_value = [{"Contents": [
                {"Key": "kept.jpg", "Size": 20, "LastModified": datetime(2020, 1, 1, tzinfo=timezone.utc)},
                {"Key": "orphan.jpg", "Size": 10, "LastModified": datetime(2020, 1, 1, tzinfo=timezone.utc)}]}]
            report = self.command()
            self.assertEqual(report["eligible_old_files"], 1)
            self.assertEqual(report["missing_referenced_files"], 0)
            with self.assertRaisesMessage(CommandError, "no está implementada para S3"):
                self.command("--apply")
            client.return_value.delete_object.assert_not_called()

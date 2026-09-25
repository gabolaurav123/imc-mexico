from hashlib import sha256
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image

from portal.export_payload import build_export_payload
from portal.models import AnalysisJob, Asset, Machine, MachineVersion, User


@override_settings(STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
                             "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class ExportPayloadTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="imc-export-payload-")
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.owner = User.objects.create_user(email="export-owner@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner, title="draft private title", data={})
        self.version = MachineVersion.objects.create(machine=self.machine, number=7, created_by=self.owner, data={
            "title": "Excavadora aprobada", "category_name": "Excavadoras",
            "data": {"brand": "CAT", "model": "320", "serial": "SECRET-123", "notes": "private", "email": "private@example.invalid"},
            "public_asset_ids": [], "private_plate_asset_ids": [],
        })
        self.machine.approved_version = self.version
        self.machine.save(update_fields=["approved_version"])

    def asset(self, *, purpose="general", position=0, cover=False, raw=None, name="source.jpg", machine=None):
        raw = raw or self.png((20, 10))
        asset = Asset(machine=machine or self.machine, kind="image", purpose=purpose, position=position,
                      is_cover=cover, processing_status="ready", public_authorized=True,
                      mime_type="image/jpeg", size=1, sha256="0" * 64)
        asset.original.save(name, ContentFile(raw), save=False)
        asset.save()
        return asset

    @staticmethod
    def png(size):
        out = BytesIO()
        Image.new("RGB", size, "green").save(out, format="PNG")
        return out.getvalue()

    def approve_assets(self, *assets, plate_ids=()):
        data = dict(self.version.data)
        data["public_asset_ids"] = [str(asset.pk) for asset in assets]
        data["private_plate_asset_ids"] = [str(value) for value in plate_ids]
        # The helper receives this approved snapshot directly; keeping this
        # test-only adjustment in memory preserves model immutability.
        self.version.data = data

    def test_png_fallback_uses_emitted_bytes_mime_digest_and_dimensions(self):
        raw = self.png((20, 10))
        asset = self.asset(raw=raw, name="wrong.jpg")
        self.approve_assets(asset)
        payload, files = build_export_payload(self.machine, self.version)
        item = payload["assets"][0]
        self.assertEqual(item["path"], f"fotos_principales/01_{asset.pk}.png")
        self.assertEqual(item["mime_type"], "image/png")
        self.assertEqual(item["size"], len(raw))
        self.assertEqual(item["sha256"], sha256(raw).hexdigest())
        self.assertEqual((item["width"], item["height"], item["aspect_ratio"]), (20, 10, 2))
        self.assertEqual(files, [(item["path"], raw)])

    def test_foreign_asset_uuid_and_private_purposes_are_never_exported(self):
        other = Machine.objects.create(owner=self.owner)
        foreign = self.asset(machine=other)
        plate = self.asset(purpose="plate")
        document = self.asset(purpose="document")
        allowed = self.asset(purpose="detail")
        self.approve_assets(foreign, plate, document, allowed)
        payload, _ = build_export_payload(self.machine, self.version)
        self.assertEqual([item["id"] for item in payload["assets"]], [str(allowed.pk)])

    def test_current_plate_detection_revokes_an_otherwise_authorized_asset(self):
        plate = self.asset()
        allowed = self.asset(purpose="detail")
        self.approve_assets(plate, allowed)
        AnalysisJob.objects.create(
            machine=self.machine, revision=1, requested_by=self.owner,
            asset_ids=[str(plate.pk)], fingerprint=uuid4().hex * 2,
            status="completed", result={"plates": [{"asset_id": str(plate.pk)}]},
        )
        payload, _ = build_export_payload(self.machine, self.version)
        self.assertEqual([item["id"] for item in payload["assets"]], [str(allowed.pk)])

    def test_assets_have_stable_order_and_only_one_deterministic_cover(self):
        late = self.asset(position=3, cover=True)
        first = self.asset(position=1, cover=True)
        second = self.asset(position=1, cover=True)
        self.approve_assets(late, second, first)
        payload, _ = build_export_payload(self.machine, self.version)
        items = payload["assets"]
        self.assertEqual([(item["position"], item["id"]) for item in items],
                         sorted((item["position"], item["id"]) for item in items))
        self.assertEqual(sum(item["cover"] for item in items), 1)
        self.assertEqual(next(item["id"] for item in items if item["cover"]), items[0]["id"])

    def test_first_image_is_the_cover_when_no_asset_selects_one(self):
        later = self.asset(position=9)
        first = self.asset(position=2)
        self.approve_assets(later, first)
        payload, _ = build_export_payload(self.machine, self.version)
        self.assertEqual([item["cover"] for item in payload["assets"]], [True, False])

    def test_public_payload_excludes_private_fields_and_metadata_is_opt_in(self):
        payload, _ = build_export_payload(self.machine, self.version)
        encoded = str(payload)
        for private in ("SECRET-123", "private@example.invalid", "private", "original", "preview"):
            self.assertNotIn(private, encoded)
        self.assertNotIn("metadata", payload)
        self.assertNotIn("exported_at", payload)
        self.assertEqual(payload["title"], "Excavadora aprobada")
        with_metadata, _ = build_export_payload(self.machine, self.version, include_private_metadata=True)
        self.assertEqual(with_metadata["metadata"], {"private_return_url": f"/panel/maquinarias/{self.machine.pk}/"})

    def test_invalid_image_bytes_and_invalid_snapshot_uuid_fail_closed(self):
        corrupt = self.asset(raw=b"not an image", name="broken.jpg")
        self.approve_assets(corrupt)
        with self.assertRaises(ValidationError):
            build_export_payload(self.machine, self.version)
        self.version.data["public_asset_ids"] = ["not-a-uuid"]
        with self.assertRaises(ValidationError):
            build_export_payload(self.machine, self.version)

    def test_many_assets_cannot_exceed_total_export_bound(self):
        first = self.asset(raw=self.png((20, 10)))
        second = self.asset(raw=self.png((20, 10)))
        self.approve_assets(first, second)
        with patch("portal.export_payload.MAX_EXPORT_TOTAL_BYTES", 1):
            with self.assertRaises(ValidationError):
                build_export_payload(self.machine, self.version)

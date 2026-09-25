"""Late image classification also restricts already submitted/public snapshots."""
import uuid
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image
from pypdf import PdfReader

from portal.models import AnalysisJob, Asset, Machine, MachineVersion, Publication, User
from portal.services import record_local_duplicate_review, review_submission, submit_machine


@override_settings(SECURE_SSL_REDIRECT=False, PRIVATE_S3_BUCKET="",
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class LatePlatePrivacyTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="imc-late-plate-")
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.owner = User.objects.create_user(email="late-plate@example.invalid", is_test=True,
                                             advertiser_status="approved")
        self.machine = Machine.objects.create(owner=self.owner, title="Equipo de prueba",
                                              data={"description": "Equipo para pruebas de privacidad."})
        self.general = self.asset("general", "yellow", (120, 80))
        self.plate = self.asset("unknown-plate", "purple", (96, 64))

    def asset(self, name, color, size):
        stream = BytesIO()
        Image.new("RGB", size, color).save(stream, format="JPEG")
        raw = stream.getvalue()
        asset = Asset(machine=self.machine, kind="image", purpose="general", processing_status="ready",
                      public_authorized=True, mime_type="image/jpeg", sha256=uuid.uuid4().hex * 2,
                      size=len(raw))
        asset.original.save(name + ".jpg", ContentFile(raw), save=False)
        asset.preview.save(name + "-preview.jpg", ContentFile(raw), save=False)
        asset.save()
        return asset

    def identify_plate(self):
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint=uuid.uuid4().hex, status="completed",
            asset_ids=[str(self.plate.pk)],
            result={"image_observations": [{"asset_id": str(self.plate.pk), "kind": "plate"}], "plates": []})

    def historical_publication(self):
        # Historical snapshots predate classification metadata altogether.
        asset_ids = [str(self.general.pk), str(self.plate.pk)]
        version = MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.owner,
            data={"title": self.machine.title, "data": self.machine.data, "provenance": {},
                  "asset_ids": asset_ids, "public_asset_ids": asset_ids, "contact_authorized": False})
        self.machine.approved_version = version
        self.machine.save(update_fields=["approved_version"])
        publication = Publication.objects.create(machine=self.machine, version=version,
            destination="share", enabled=True, status="published")
        self.identify_plate()
        return publication

    def test_classification_after_submission_excludes_plate_at_approval(self):
        submission = submit_machine(self.machine, self.owner, True)
        self.assertIn(str(self.plate.pk), submission.version.data["public_asset_ids"])
        self.identify_plate()
        administrator = User.objects.create_superuser(email="late-plate-admin@example.invalid", is_test=True)
        record_local_duplicate_review(
            self.machine, submission, administrator, "no_match",
            "Se revisaron la placa privada, serie y archivos de esta versión.",
        )
        review_submission(submission, administrator, "approved")
        self.machine.refresh_from_db()
        approved = self.machine.approved_version.data
        self.assertEqual(approved["private_plate_asset_ids"], [str(self.plate.pk)])
        self.assertEqual(approved["public_asset_ids"], [str(self.general.pk)])
        self.plate.refresh_from_db()
        self.assertEqual(self.plate.purpose, "general")

    def test_historical_public_image_and_sheet_deny_newly_detected_plate(self):
        publication = self.historical_publication()
        root = f"/ficha/{publication.token}/"
        response = self.client.get(root + f"archivo/{self.plate.pk}/")
        self.assertEqual(response.status_code, 404)
        allowed = self.client.get(root + f"archivo/{self.general.pk}/")
        self.assertEqual(allowed.status_code, 200)
        allowed.close()
        response = self.client.get(root)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f"archivo/{self.plate.pk}/")
        self.assertContains(response, f"archivo/{self.general.pk}/")

    def test_historical_public_pdf_does_not_embed_newly_detected_plate(self):
        publication = self.historical_publication()
        response = self.client.get(f"/ficha/{publication.token}/pdf/")
        self.assertEqual(response.status_code, 403)

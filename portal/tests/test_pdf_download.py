"""Official PDFs are management-only exports; sheets remain viewable normally."""
from copy import deepcopy
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image
from pypdf import PdfReader

from portal.models import Asset, Machine, MachineVersion, Publication, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False, PRIVATE_S3_BUCKET="",
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PdfDownloadTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="imc-pdf-download-")
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.owner = User.objects.create_user(email="pdf-owner@example.invalid", advertiser_status="approved", is_test=True)
        self.other = User.objects.create_user(email="pdf-other@example.invalid", is_test=True)
        self.operator = User.objects.create_user(email="pdf-operator@example.invalid", is_staff=True, is_test=True)
        self.machine = Machine.objects.create(owner=self.owner, title="PRUEBA PDF aprobada", data={
            "brand": "CAT", "model": "14H", "serial": "PRIVATE-SERIAL-PDF", "notes": "PRIVATE-NOTE-PDF",
            "description": "Cabina cerrada y hoja niveladora visibles.", "contact_public": "PRIVATE-CONTACT-PDF"})
        self.photo = self.make_asset("general", "yellow", (120, 80))
        self.plate = self.make_asset("plate", "purple", (96, 64))
        self.version = MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.owner,
            data={"title": "PRUEBA PDF aprobada", "data": deepcopy(self.machine.data), "provenance": {},
                  "asset_ids": [str(self.photo.pk), str(self.plate.pk)],
                  # Deliberately include the plate to exercise the PDF's own
                  # second authorization filter on a historical snapshot.
                  "public_asset_ids": [str(self.photo.pk), str(self.plate.pk)],
                  "contact_authorized": False, "public_contact": {"email": "unapproved-contact@example.invalid"}})
        self.machine.approved_version = self.version
        self.machine.save()
        self.publication = Publication.objects.create(machine=self.machine, version=self.version,
                                                       destination="share", enabled=True, status="published")
        self.private_url = f"/panel/maquinarias/{self.machine.pk}/pdf/"
        self.public_url = f"/ficha/{self.publication.token}/pdf/"

    def make_asset(self, purpose, color, size):
        image = BytesIO()
        Image.new("RGB", size, color).save(image, format="JPEG")
        raw = image.getvalue()
        asset = Asset(machine=self.machine, kind="image", purpose=purpose, processing_status="ready",
                      public_authorized=True, mime_type="image/jpeg", sha256=("a" if purpose == "general" else "b") * 64,
                      size=len(raw), is_cover=purpose == "general")
        asset.original.save(f"{purpose}.jpg", ContentFile(raw), save=False)
        asset.preview.save(f"{purpose}-preview.jpg", ContentFile(raw), save=False)
        asset.save()
        return asset

    def assert_download_headers(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Disposition"], f'attachment; filename="{self.machine.folio}.pdf"')
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def verify_operator(self):
        self.client.force_login(self.operator)
        device = TOTPDevice.objects.create(user=self.operator, name="PDF QA", confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def test_owner_download_is_attachment_private_and_contains_internal_values(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.private_url).status_code, 403)
        self.operator.user_permissions.add(Permission.objects.get(content_type__app_label="portal", codename="publish_machine"))
        self.verify_operator()
        response = self.client.get(self.private_url)
        self.assert_download_headers(response)
        text = " ".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
        self.assertIn("PRIVATE-SERIAL-PDF", text)
        self.assertIn("PRIVATE-NOTE-PDF", text)

    def test_private_pdf_rejects_anonymous_and_other_owner_before_building(self):
        with patch("portal.pdf.build_pdf") as build:
            self.assertEqual(self.client.get(self.private_url).status_code, 403)
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(self.private_url).status_code, 403)
        build.assert_not_called()

    def test_long_multiline_technical_cell_continues_without_losing_content(self):
        prefix, suffix = "INICIO-CELDA\n", "\nFIN-CELDA"
        value = prefix + ("fila de prueba\n" * 100)[:998 - len(prefix) - len(suffix)] + suffix
        self.assertEqual(len(value), 998)
        self.machine.data["power"] = value
        self.machine.save(update_fields=["data"])
        self.operator.user_permissions.add(Permission.objects.get(content_type__app_label="portal", codename="publish_machine"))
        self.verify_operator()
        response = self.client.get(self.private_url)
        self.assert_download_headers(response)
        document = PdfReader(BytesIO(response.content))
        self.assertGreaterEqual(len(document.pages), 2)
        text = " ".join(page.extract_text() for page in document.pages)
        self.assertIn("INICIO-CELDA", text)
        self.assertIn("FIN-CELDA", text)

    def test_staff_requires_both_mfa_and_read_permission(self):
        self.operator.user_permissions.add(*Permission.objects.filter(content_type__app_label="portal",
                                                                       codename="operate_platform"))
        self.verify_operator()
        with patch("portal.pdf.build_pdf", return_value=b"%PDF-FAKE") as build:
            self.assertEqual(self.client.get(self.private_url).status_code, 403)
            build.assert_not_called()
            self.operator.user_permissions.add(Permission.objects.get(content_type__app_label="portal", codename="publish_machine"))
            response = self.client.get(self.private_url)
            self.assert_download_headers(response)
            self.client.logout()
            self.client.force_login(self.operator)
            self.assertEqual(self.client.get(self.private_url).status_code, 403)
            self.assertEqual(build.call_count, 1)

    def test_owner_cannot_request_a_version_from_another_machine(self):
        foreign = Machine.objects.create(owner=self.other)
        version = MachineVersion.objects.create(machine=foreign, number=1, data={}, created_by=self.other)
        self.client.force_login(self.owner)
        with patch("portal.pdf.build_pdf") as build:
            self.assertEqual(self.client.get(self.private_url, {"version": str(version.pk)}).status_code, 403)
        build.assert_not_called()

    def test_anonymous_public_pdf_uses_approved_snapshot_and_omits_private_data_and_plate(self):
        self.machine.title = "PRIVATE-UNREVIEWED-TITLE"
        self.machine.data["description"] = "PRIVATE-UNREVIEWED-DESCRIPTION"
        self.machine.save()
        self.assertEqual(self.client.get(self.public_url).status_code, 403)
        self.operator.user_permissions.add(Permission.objects.get(content_type__app_label="portal", codename="publish_machine"))
        self.verify_operator()
        response = self.client.get(self.public_url)
        self.assert_download_headers(response)
        document = PdfReader(BytesIO(response.content))
        text = " ".join(page.extract_text() for page in document.pages)
        self.assertIn("PRUEBA PDF aprobada", text)
        self.assertIn("Cabina cerrada", text)
        for private in ("PRIVATE-SERIAL", "PRIVATE-NOTE", "PRIVATE-CONTACT", "PRIVATE-UNREVIEWED",
                        "unapproved-contact@example.invalid", self.owner.email):
            self.assertNotIn(private, text)
        sizes = [item.image.size for page in document.pages for item in page.images]
        self.assertIn((120, 80), sizes)
        self.assertNotIn((96, 64), sizes)

    def test_public_pdf_stops_working_immediately_when_its_authorization_is_revoked(self):
        # Share tokens have no calendar TTL; they remain contingent on every
        # current authorization and on the exact approved version.
        cases = [(Publication, self.publication.pk, {"enabled": False}),
                 (Publication, self.publication.pk, {"status": "disabled"}),
                 (User, self.owner.pk, {"advertiser_status": "suspended"}),
                 (Machine, self.machine.pk, {"availability": "withdrawn"}),
                 (Machine, self.machine.pk, {"approved_version": None})]
        self.operator.user_permissions.add(Permission.objects.get(content_type__app_label="portal", codename="publish_machine"))
        self.verify_operator()
        with patch("portal.pdf.build_pdf") as build:
            for model, pk, changes in cases:
                with self.subTest(changes=changes):
                    original = model.objects.values(*changes).get(pk=pk)
                    model.objects.filter(pk=pk).update(**changes)
                    self.assertEqual(self.client.get(self.public_url).status_code, 404)
                    model.objects.filter(pk=pk).update(**original)
            self.publication.version = None
            self.publication.save()
            self.assertEqual(self.client.get(self.public_url).status_code, 404)
        build.assert_not_called()

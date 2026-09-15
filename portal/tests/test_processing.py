import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from unittest import skipUnless
import uuid

from django.core import mail
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from portal.models import AnalysisJob, AnalyticsEvent, Asset, Consent, Machine, MachineVersion, Notification, PlatformSettings, User
from portal.processing import (MachineAnalysis, _claim_job, enqueue_analysis, ingest_asset,
                               normalize_analysis, process_analysis, process_next_job,
                               process_notifications)
from portal.storage import PrivateStorage


def photo(name="photo.jpg", color="navy", fmt="JPEG"):
    output = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(output, format=fmt)
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/jpeg")


def analysis_result(asset_id, **overrides):
    result = {"title": "Excavadora", "description": "Equipo con información pendiente de confirmar.",
              "category": "Excavadoras", "fields": [], "plates": [], "warnings": [], "questions": []}
    result.update(overrides)
    return MachineAnalysis.model_validate(result)


@override_settings(OPENAI_API_KEY="test-not-a-real-key", OPENAI_MODEL="gpt-4.1-mini",
                   PRIVATE_S3_BUCKET="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ProcessingTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory(prefix="imc-test-media-")
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media.cleanup)
        self.user = User.objects.create_user(email="owner@example.com", password="tests-only-pass-4821")
        self.other = User.objects.create_user(email="other@example.com", password="tests-only-pass-9835")
        self.machine = Machine.objects.create(owner=self.user, title="Mi excavadora", data={"brand": "Marca declarada"})
        self.limits = PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=300000)
        Consent.objects.create(user=self.user, machine=self.machine, kind="ai", granted=True)

    def test_upload_validates_content_not_declared_mime_and_deduplicates(self):
        asset = ingest_asset(self.machine, self.user, photo())
        duplicate = ingest_asset(self.machine, self.user, photo())
        self.assertEqual(asset.pk, duplicate.pk)
        self.assertEqual(asset.processing_status, "ready")
        self.assertTrue(asset.is_cover)
        self.assertFalse(asset.public_authorized)
        self.assertEqual(self.machine.assets.count(), 1)
        with asset.preview.open("rb") as stream:
            decoded = Image.open(stream)
            self.assertEqual(decoded.format, "JPEG")
            self.assertFalse(decoded.getexif())
        with self.assertRaises(ValidationError):
            ingest_asset(self.machine, self.user, SimpleUploadedFile("fake.jpg", b"<script>alert(1)</script>"))
        with self.assertRaises(ValidationError):
            ingest_asset(self.machine, self.user, photo("blocked.svg"))

    def test_heic_is_decoded_and_previewed_as_jpeg(self):
        import pillow_heif
        heif = pillow_heif.from_pillow(Image.new("RGB", (120, 80), "red"))
        output = io.BytesIO()
        heif.save(output)
        asset = ingest_asset(self.machine, self.user, SimpleUploadedFile("phone.heic", output.getvalue()))
        self.assertEqual(asset.mime_type, "image/heic")
        with asset.preview.open("rb") as stream:
            self.assertEqual(Image.open(stream).format, "JPEG")

    def test_limits_and_ownership(self):
        self.limits.max_images = 1
        self.limits.save()
        ingest_asset(self.machine, self.user, photo())
        with self.assertRaises(ValidationError):
            ingest_asset(self.machine, self.user, photo(color="red"))
        with self.assertRaises(PermissionDenied):
            ingest_asset(self.machine, self.other, photo())
        with self.assertRaises(ValidationError):
            ingest_asset(self.machine, self.user, SimpleUploadedFile("fake.mov", b"not a video"))

    def test_huge_image_dimensions_are_rejected_before_full_decode(self):
        import struct
        import zlib
        def chunk(kind, content):
            return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
        payload = b"\x89PNG\r\n\x1a\n"
        payload += chunk(b"IHDR", struct.pack(">IIBBBBB", 8000, 8000, 8, 2, 0, 0, 0))
        payload += chunk(b"IDAT", zlib.compress(b"\x00"))
        payload += chunk(b"IEND", b"")
        with self.assertRaisesMessage(ValidationError, "50 megapíxeles"):
            ingest_asset(self.machine, self.user, SimpleUploadedFile("large.png", payload))

    @skipUnless(shutil.which(os.getenv("FFMPEG_BINARY", "ffmpeg")) and shutil.which(os.getenv("FFPROBE_BINARY", "ffprobe")),
                "Real video conversion requires ffmpeg and ffprobe")
    def test_real_mov_conversion_and_duration_limit(self):
        ffmpeg = shutil.which(os.getenv("FFMPEG_BINARY", "ffmpeg"))
        ffprobe = shutil.which(os.getenv("FFPROBE_BINARY", "ffprobe"))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "fixture.mov"
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=320x240:r=10:d=2",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source)], check=True, timeout=30)
            fixture = source.read_bytes()
            with override_settings(FFMPEG_BINARY=ffmpeg, FFPROBE_BINARY=ffprobe):
                self.limits.max_video_seconds = 1
                self.limits.save()
                with self.assertRaisesMessage(ValidationError, "1 segundos"):
                    ingest_asset(self.machine, self.user, SimpleUploadedFile("phone.mov", fixture))
                self.limits.max_video_seconds = 120
                self.limits.save()
                asset = ingest_asset(self.machine, self.user, SimpleUploadedFile("phone.mov", fixture))
                self.assertEqual(asset.kind, "video")
                self.assertEqual(asset.processing_status, "ready")
                self.assertTrue(asset.preview.name.endswith(".mp4"))
                result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_name,pix_fmt,width,height",
                                         "-of", "json", asset.preview.path], capture_output=True, check=True, timeout=20)
                stream = json.loads(result.stdout)["streams"][0]
                self.assertEqual(stream["codec_name"], "h264")
                self.assertEqual(stream["pix_fmt"], "yuv420p")
                self.assertEqual((stream["width"], stream["height"]), (320, 240))
                self.assertEqual(asset.original.size, len(fixture))

    def test_storage_refuses_public_urls_and_traversal(self):
        storage = PrivateStorage()
        with self.assertRaises(ValueError):
            storage.url("file.jpg")
        with self.assertRaises(SuspiciousFileOperation):
            storage.exists("../../secret.txt")

    def test_consent_deduplication_and_per_user_quota(self):
        asset = ingest_asset(self.machine, self.user, photo())
        one = enqueue_analysis(self.machine, self.user, [str(asset.pk)])
        two = enqueue_analysis(self.machine, self.user, [str(asset.pk)])
        self.assertEqual(one.pk, two.pk)
        self.assertGreater(one.reserved_tokens, 0)
        self.limits.ai_user_daily_limit = 1
        self.limits.save()
        self.machine.revision += 1
        self.machine.save()
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.user)
        Consent.objects.create(user=self.user, machine=self.machine, kind="ai", granted=False)
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.user)

    def test_other_machine_asset_and_documents_cannot_be_analyzed(self):
        asset = ingest_asset(self.machine, self.user, photo(), purpose="document")
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.user, [str(asset.pk)])
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.user, [str(uuid.uuid4())])

    def test_daily_token_reservation_blocks_before_remote_call(self):
        ingest_asset(self.machine, self.user, photo())
        self.limits.ai_daily_token_limit = 1
        self.limits.save()
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.user)
        self.assertEqual(AnalysisJob.objects.count(), 0)

    def test_component_plate_and_partial_serial_are_not_machine_identification(self):
        asset_id = str(uuid.uuid4())
        field = {"key": "serial", "label": "Serie", "value": "ABC123", "source": "plate", "review": "clear",
                 "asset_id": asset_id, "component": "machine", "evidence": "ABC[ilegible]"}
        parsed = analysis_result(asset_id, fields=[field], plates=[{
            "asset_id": asset_id, "component": "engine", "transcription": "ABC[ilegible]", "readability": "partial"}])
        normalized = normalize_analysis(parsed, [asset_id])
        self.assertIsNone(normalized["data"]["serial"])
        field["component"] = "engine"
        parsed = analysis_result(asset_id, fields=[field])
        normalized = normalize_analysis(parsed, [asset_id])
        self.assertNotIn("serial", normalized["data"])
        self.assertIsNone(normalized["fields"][0]["value"])

    def test_request_uses_responses_structured_images_and_omits_private_contact(self):
        asset = ingest_asset(self.machine, self.user, photo())
        self.machine.data["contact_public"] = "private-contact@example.com"
        self.machine.save()
        job = enqueue_analysis(self.machine, self.user)
        response = SimpleNamespace(status="completed", output_parsed=analysis_result(str(asset.pk)),
                                   usage=SimpleNamespace(input_tokens=100, output_tokens=50))
        with patch("openai.OpenAI") as mock:
            mock.return_value.responses.parse.return_value = response
            result, usage = process_analysis(job)
        kwargs = mock.return_value.responses.parse.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertEqual(kwargs["text_format"], MachineAnalysis)
        self.assertEqual(mock.call_args.kwargs["max_retries"], 0)
        self.assertIn("data:image/jpeg;base64,", str(kwargs["input"]))
        self.assertNotIn("private-contact@example.com", str(kwargs["input"]))
        self.assertEqual(result["data"]["title"], "Excavadora")

    def test_consent_revocation_before_worker_prevents_remote_request(self):
        ingest_asset(self.machine, self.user, photo())
        job = enqueue_analysis(self.machine, self.user)
        Consent.objects.create(user=self.user, machine=self.machine, kind="ai", granted=False)
        with patch("openai.OpenAI") as mock, self.assertRaises(ValidationError):
            process_analysis(job)
        mock.assert_not_called()

    def test_worker_saves_suggestions_without_overwriting_user_edits(self):
        asset = ingest_asset(self.machine, self.user, photo())
        job = enqueue_analysis(self.machine, self.user)
        result = normalize_analysis(analysis_result(str(asset.pk)), [str(asset.pk)])
        with patch("portal.processing.process_analysis", return_value=(result, SimpleNamespace(input_tokens=100, output_tokens=50))):
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.reserved_tokens, 0)
        self.assertEqual(job.input_tokens, 100)
        self.assertEqual(self.machine.title, "Mi excavadora")
        self.assertEqual(self.machine.data["brand"], "Marca declarada")
        self.assertFalse(AnalyticsEvent.objects.filter(event="analysis_completed").exists())

    def test_analysis_completion_records_only_unrevoked_optional_context(self):
        asset = ingest_asset(self.machine, self.user, photo())
        self.limits.analytics_enabled = True
        self.limits.save()
        context = {"source": "direct", "device": "desktop", "actor_type": "registered",
                   "session_hash": "a" * 64, "_consent": True,
                   "_expires_at": (timezone.now() + timedelta(minutes=10)).timestamp()}
        job = enqueue_analysis(self.machine, self.user, analytics_context=context)
        result = normalize_analysis(analysis_result(str(asset.pk)), [str(asset.pk)])

        def remote_result_with_revocation(_job):
            # Consent is withdrawn while an already-started API call is running.
            AnalysisJob.objects.filter(pk=job.pk).update(analytics_context={})
            return result, SimpleNamespace(input_tokens=100, output_tokens=50)

        with patch("portal.processing.process_analysis", side_effect=remote_result_with_revocation):
            process_next_job()
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.analytics_context, {})
        self.assertFalse(AnalyticsEvent.objects.filter(event="analysis_completed").exists())

        self.machine.revision += 1
        self.machine.save()
        next_job = enqueue_analysis(self.machine, self.user, analytics_context=context)
        with patch("portal.processing.process_analysis", return_value=(result, SimpleNamespace(input_tokens=100, output_tokens=50))):
            process_next_job()
        next_job.refresh_from_db()
        self.assertEqual(next_job.status, "completed")
        self.assertEqual(AnalyticsEvent.objects.filter(event="analysis_completed").count(), 1)

    def test_failure_is_sanitized_and_stale_worker_has_bounded_recovery(self):
        ingest_asset(self.machine, self.user, photo())
        job = enqueue_analysis(self.machine, self.user, analytics_context={"session_hash": "a" * 64})
        with patch("portal.processing.process_analysis", side_effect=ValueError("secret-api-key-should-never-leak")):
            process_next_job()
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.analytics_context, {})
        self.assertNotIn("secret", job.error)
        job.status = "running"
        job.attempts = self.limits.ai_max_attempts
        job.locked_at = timezone.now() - timedelta(hours=1)
        job.save()
        self.assertIsNone(_claim_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIsNotNone(job.finished_at)

    def test_transient_retry_has_backoff_and_max_attempts(self):
        from openai import APIConnectionError
        import httpx2 as httpx
        ingest_asset(self.machine, self.user, photo())
        job = enqueue_analysis(self.machine, self.user)
        failure = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
        with patch("portal.processing.process_analysis", side_effect=failure):
            process_next_job()
            job.refresh_from_db()
            self.assertEqual(job.status, "queued")
            self.assertGreater(job.locked_at, timezone.now())
            self.assertFalse(process_next_job())
            job.locked_at = timezone.now() - timedelta(seconds=1)
            job.save()
            process_next_job()
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempts, 2)

    def test_notification_delivery_and_bounded_failure(self):
        notice = Notification.objects.create(user=self.user, kind="review", subject="Solicitud recibida",
                                              body="Consulta el estado desde tu panel.", channel="email")
        self.assertEqual(process_notifications(), 1)
        notice.refresh_from_db()
        self.assertEqual(notice.status, "sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        notice.status = "pending"
        notice.attempts = 0
        notice.save()
        with patch("portal.processing.send_mail", side_effect=RuntimeError("password=secret")):
            process_notifications()
        notice.refresh_from_db()
        self.assertEqual(notice.status, "failed")
        self.assertEqual(notice.attempts, 3)
        self.assertNotIn("secret", notice.error)

    def test_invalid_test_domain_is_suppressed_without_claiming_delivery(self):
        self.user.email = "fixture@example.invalid"
        self.user.save()
        notice = Notification.objects.create(user=self.user, kind="review", subject="Prueba",
                                              body="No debe enviarse.", channel="email")
        with patch("portal.processing.send_mail") as send:
            self.assertEqual(process_notifications(), 0)
        send.assert_not_called()
        notice.refresh_from_db()
        self.assertEqual(notice.status, "failed")
        self.assertEqual(notice.error, "Envío suprimido: dirección de prueba .invalid")
        self.assertIsNone(notice.sent_at)

    def test_pdf_requires_public_version_and_excludes_private_fields(self):
        from portal.pdf import build_pdf
        from pypdf import PdfReader
        asset = ingest_asset(self.machine, self.user, photo())
        asset.public_authorized = True
        asset.save()
        plate = ingest_asset(self.machine, self.user, photo(color="orange"), purpose="plate")
        plate.public_authorized = True
        plate.save()
        values = {"brand": "Marca revisada", "serial": "PRIVATE-SERIAL-099", "notes": "PRIVATE-NOTE-099",
                  "description": "Descripción aprobada", "price": "120000", "currency": "MXN",
                  "contact_public": "PRIVATE-CONTACT-099"}
        version = MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.user,
                                                 data={"title": "Título aprobado", "data": values,
                                                       "asset_ids": [str(asset.pk), str(plate.pk)],
                                                       "public_asset_ids": [str(asset.pk), str(plate.pk)],
                                                       "contact_authorized": False,
                                                       "public_contact": {"text": "NONCONSENTED-PERSON"}})
        self.machine.title = "Unreviewed latest title"
        self.machine.availability = "sold"
        with self.assertRaises(ValueError):
            build_pdf(self.machine, values, [asset], public=True)
        public = PdfReader(io.BytesIO(build_pdf(self.machine, values, [asset, plate], public=True, version=version)))
        text = " ".join(page.extract_text() for page in public.pages)
        self.assertIn("Título aprobado", text)
        self.assertIn("Vendida", text)
        self.assertNotIn("PRIVATE-SERIAL", text)
        self.assertNotIn("PRIVATE-NOTE", text)
        self.assertNotIn("PRIVATE-CONTACT", text)
        self.assertNotIn("NONCONSENTED", text)
        self.assertEqual(sum(len(page.images) for page in public.pages), 1)
        self.assertNotIn("Unreviewed", text)
        internal = PdfReader(io.BytesIO(build_pdf(self.machine, values, [asset], version=version)))
        internal_text = " ".join(page.extract_text() for page in internal.pages)
        self.assertIn("PRIVATE-SERIAL-099", internal_text)
        self.assertIn("PRIVATE-NOTE-099", internal_text)

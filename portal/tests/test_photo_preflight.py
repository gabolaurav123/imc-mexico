"""Photo preflight reads safely once and never turns into a draft update."""
from io import BytesIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from PIL import Image

from portal.models import AnalysisJob, Category, Machine, PlatformSettings, User
from portal.processing import MachineAnalysis, enqueue_analysis, ingest_asset, process_next_job
from portal.services import apply_analysis_automatically, apply_analysis_suggestions


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-6-luna", PRIVATE_S3_BUCKET="",
                   SECURE_SSL_REDIRECT=False)
class PhotoPreflightTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="imc-photo-preflight-")
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.owner = User.objects.create_user(email="preflight@example.invalid", is_test=True)
        self.category = Category.objects.create(name="Excavadoras", slug="preflight-excavators")
        self.machine = Machine.objects.create(owner=self.owner, category=self.category)
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=300000)
        image = BytesIO()
        Image.new("RGB", (80, 80), "yellow").save(image, format="JPEG")
        self.asset = ingest_asset(self.machine, self.owner, SimpleUploadedFile("photo.jpg", image.getvalue()))
        self.client.force_login(self.owner)

    def provider_reading(self):
        return MachineAnalysis(title="Excavadora CAT 320", description="Excavadora de prueba.", category="Excavadoras",
            fields=[dict(key="brand", label="Marca", value="CAT", source="image", review="clear",
                         component="machine", asset_id="image_001", evidence="CAT visible"),
                    dict(key="model", label="Modelo", value="320", source="image", review="clear",
                         component="machine", asset_id="image_001", evidence="320 visible")],
            plates=[], warnings=[], questions=[], image_observations=[dict(asset_id="image_001", kind="machine",
                relevance="machinery", category="Excavadoras")])

    def enqueue_preflight(self):
        return enqueue_analysis(self.machine, self.owner, asset_ids=[str(self.asset.pk)], mode="analysis",
            research=False, auto_apply=False, authorize_ai=True, preflight=True)

    def complete_preflight(self):
        job = self.enqueue_preflight()
        with patch("openai.OpenAI") as provider, \
             patch("portal.processing.research_machine") as research, \
             patch("portal.processing.estimate_machine") as valuation, \
             patch("portal.processing.build_family_reference") as family:
            client = provider.return_value
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=self.provider_reading(),
                model="gpt-6-luna", usage=SimpleNamespace(input_tokens=200, output_tokens=90))
            self.assertTrue(process_next_job())
        research.assert_not_called()
        valuation.assert_not_called()
        family.assert_not_called()
        client.responses.parse.assert_called_once()
        job.refresh_from_db()
        self.machine.refresh_from_db()
        return job

    def test_preflight_reads_photos_without_research_valuation_or_draft_generation(self):
        job = self.complete_preflight()
        self.assertEqual(job.status, "completed")
        self.assertTrue(job.result["preflight"])
        self.assertEqual(job.result["research"]["reason"], "photo_preflight")
        self.assertEqual(job.result["valuation"]["reason"], "photo_preflight")
        self.assertEqual(self.machine.data, {})
        self.assertEqual(self.machine.title, "Mi maquinaria")
        self.assertFalse(self.machine.versions.exists())
        self.assertFalse(self.machine.submissions.exists())

    def test_normal_analysis_reuses_completed_preflight_photo_cache_without_a_second_provider_read(self):
        preflight = self.complete_preflight()
        normal = enqueue_analysis(self.machine, self.owner, asset_ids=[str(self.asset.pk)], mode="analysis",
            research=False, auto_apply=False, authorize_ai=True, preflight=False)
        self.assertNotEqual(preflight.fingerprint, normal.fingerprint)
        with patch("openai.OpenAI") as provider:
            self.assertTrue(process_next_job())
        provider.return_value.responses.parse.assert_not_called()
        normal.refresh_from_db()
        self.assertEqual(normal.status, "completed")
        self.assertEqual(normal.result["image_readings"][0]["status"], "reused")
        self.assertFalse(normal.result["preflight"])

    def test_api_preflight_forces_no_research_or_autofill(self):
        queued = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, asset_ids=[str(self.asset.pk)], mode="analysis", fingerprint="a" * 64,
            result={"preflight": True, "progress": {"stage": "queued"}})
        with patch("portal.processing.enqueue_analysis", return_value=queued) as enqueue:
            response = self.client.post(f"/api/maquinarias/{self.machine.pk}/analizar/", {
                "consent": True, "asset_ids": [str(self.asset.pk)], "auto_apply": True,
                "research": True, "preflight": True,
            }, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(enqueue.call_args.kwargs["preflight"])
        self.assertFalse(enqueue.call_args.kwargs["research"])
        self.assertFalse(enqueue.call_args.kwargs["auto_apply"])

    def test_backend_rejects_preflight_that_could_research_or_modify_the_draft(self):
        for options in ({"research": True}, {"auto_apply": True}, {"mode": "description"}):
            with self.subTest(options=options), self.assertRaisesMessage(ValidationError, "no puede modificar ni investigar"):
                enqueue_analysis(self.machine, self.owner, asset_ids=[str(self.asset.pk)], authorize_ai=True,
                    preflight=True, **options)

    def test_preflight_cannot_be_applied_manually_or_automatically(self):
        result = {"preflight": True, "relevance": {"status": "relevant"},
            "data": {"brand": "CAT"}, "provenance": {"brand": {"source": "image", "review": "clear",
            "asset_id": str(self.asset.pk), "component": "machine"}}}
        job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            asset_ids=[str(self.asset.pk)], mode="analysis", fingerprint="b" * 64, status="completed", result=result)
        with self.assertRaisesMessage(ValidationError, "no genera ni modifica"):
            apply_analysis_automatically(self.machine, self.owner, job, self.machine.revision)
        with self.assertRaisesMessage(ValidationError, "no genera ni modifica"):
            apply_analysis_suggestions(self.machine, self.owner, job, ["brand"], self.machine.revision)
        response = self.client.post(f"/api/maquinarias/{self.machine.pk}/aplicar/", {
            "job_id": str(job.pk), "fields": ["brand"], "revision": self.machine.revision,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 400, response.content)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.data, {})

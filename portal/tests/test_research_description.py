"""Research plus deterministic description does not purchase a discarded draft."""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from portal.models import AnalysisJob, Consent, Machine, PlatformSettings, User
from portal.processing import (DescriptionAnalysis, _claim_job, enqueue_analysis,
                               process_analysis, process_next_job)
from portal.research import RESEARCH_RESERVATION, SEARCH_RESERVATION, ResearchCandidate, ResearchCandidates


URL = "https://www.cat.com/en_US/products/new/equipment/backhoe-loaders/420f2.html"
TEXT = "Caterpillar 420F2: potencia 70 kW."


@override_settings(OPENAI_API_KEY="test-only-not-real", OPENAI_MODEL="gpt-4.1-mini")
class ResearchDescriptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="description-test@example.invalid", password="test-only-492")
        self.machine = Machine.objects.create(owner=self.user, title="Título del propietario", data={
            "brand": "Caterpillar", "model": "420F2", "serial": "OWNER123", "hours": 0,
            "price": 0, "location": "", "notes": "PRIVATE NOTES",
        }, provenance={key: {"source": "user", "review": "confirmed"} for key in ("brand", "model", "serial")})
        self.limits = PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=100000,
                                                      ai_max_attempts=2)

    def enqueue(self, **kwargs):
        options = dict(mode="description", research=True, authorize_ai=True, auto_apply=True,
                       expected_revision=self.machine.revision)
        options.update(kwargs)
        return enqueue_analysis(self.machine, self.user, **options)

    def provider(self):
        client = Mock()
        cited = TEXT + f" [Cat]({URL})"
        client.responses.create.return_value = SimpleNamespace(
            status="completed", output_text=cited,
            usage=SimpleNamespace(input_tokens=120, output_tokens=80),
            output=[{"type": "web_search_call", "action": {"sources": [{"url": URL}]}},
                    {"type": "message", "content": [{"text": cited, "annotations": [{
                        "type": "url_citation", "url": URL, "title": "Caterpillar 420F2",
                        "start_index": len(TEXT) + 1, "end_index": len(cited),
                    }]}]}])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed", usage=SimpleNamespace(input_tokens=210, output_tokens=140),
            output_parsed=ResearchCandidates(fields=[ResearchCandidate(
                key="power", value="70 kW", scope="model", passage_index=0,
                matched_serial=None, matched_brand="Caterpillar", matched_model="420F2")]))
        return client

    def test_existing_daily_usage_allows_one_real_research_reservation_and_deduplicates(self):
        previous_usage = self.limits.ai_daily_token_limit - RESEARCH_RESERVATION - 1000
        previous = AnalysisJob.objects.create(machine=self.machine, revision=self.machine.revision,
            requested_by=self.user, fingerprint="a" * 64, status="completed", input_tokens=previous_usage,
            finished_at=timezone.now())
        with patch("openai.OpenAI") as provider:
            job = self.enqueue()
            duplicate = self.enqueue()
        provider.assert_not_called()
        self.assertEqual(job.pk, duplicate.pk)
        self.assertEqual(job.asset_ids, [])
        self.assertTrue(job.result["research_description_only"])
        self.assertEqual(job.result["attempt_limit"], 1)
        self.assertEqual(job.reserved_tokens, RESEARCH_RESERVATION)
        previous.refresh_from_db()
        self.limits.refresh_from_db()
        self.assertEqual(previous.input_tokens, previous_usage)
        self.assertEqual(self.limits.ai_daily_token_limit, 100000)
        self.assertEqual(AnalysisJob.objects.count(), 2)

    def test_insufficient_research_budget_still_rejects_before_provider_or_job(self):
        self.limits.ai_daily_token_limit = RESEARCH_RESERVATION - 1
        self.limits.save()
        with patch("openai.OpenAI") as provider, self.assertRaisesMessage(ValidationError, "No hay capacidad"):
            self.enqueue()
        provider.assert_not_called()
        self.assertFalse(AnalysisJob.objects.exists())

    def test_worker_uses_only_search_and_normalization_then_records_and_applies(self):
        job, client = self.enqueue(), self.provider()
        with patch("openai.OpenAI", return_value=client), patch("portal.processing._image_input") as image:
            self.assertTrue(process_next_job())
        image.assert_not_called()
        self.assertEqual(client.responses.create.call_count, 3)
        client.responses.parse.assert_called_once()
        client.close.assert_called_once()
        self.assertIs(client.responses.parse.call_args.kwargs["text_format"], ResearchCandidates)
        self.assertNotIn("PRIVATE NOTES", str(client.mock_calls))
        request = json.loads(client.responses.create.call_args_list[0].kwargs["input"])
        self.assertEqual(request["identifiers"]["serial"], "OWNER123")
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (24570, 380, 0))
        self.assertEqual(job.result["usage"]["estimated_tokens"], 3 * 8000)
        self.assertEqual(job.result["usage"]["web_search_calls"], 3)
        self.assertEqual(job.result["plates"], [])
        self.assertEqual(self.machine.data["power"], "70 kW")
        self.assertIn("70 kW", self.machine.data["description"])
        self.assertIn("requieren comprobación", self.machine.data["description"])
        self.assertNotIn("OWNER123", self.machine.data["description"])
        self.assertEqual(self.machine.data["hours"], 0)
        self.assertEqual(self.machine.data["price"], 0)
        self.assertEqual(self.machine.data["location"], "")
        self.assertEqual(self.machine.title, "Título del propietario")
        self.assertFalse(self.machine.publications.exists())
        self.assertEqual(self.machine.status, "draft")

    def test_revoked_consent_blocks_all_remote_calls_and_autofill(self):
        job = self.enqueue()
        Consent.objects.create(user=self.user, machine=self.machine, kind="ai", granted=False)
        with patch("openai.OpenAI") as provider, self.assertRaises(ValidationError):
            process_analysis(job)
        provider.assert_not_called()
        self.machine.refresh_from_db()
        self.assertNotIn("power", self.machine.data)

    def test_unknown_search_failure_keeps_conservative_accounting_without_initial_call(self):
        job, client = self.enqueue(), self.provider()
        client.responses.create.side_effect = TimeoutError("provider private details")
        with patch("openai.OpenAI", return_value=client):
            process_next_job()
        self.assertEqual(client.responses.create.call_count, 3)
        client.responses.parse.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["research"]["status"], "degraded")
        self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (3 * SEARCH_RESERVATION, 0, 0))
        self.assertEqual(job.result["usage"]["estimated_tokens"], 3 * SEARCH_RESERVATION)
        self.assertNotIn("private details", str(job.result))

    def test_plain_description_keeps_its_original_single_call_and_text(self):
        job = self.enqueue(research=False)
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed",
            output_parsed=DescriptionAnalysis(description="Descripción visual conservada.", warnings=[], questions=[]),
            usage=SimpleNamespace(input_tokens=30, output_tokens=20))
        self.assertEqual(job.reserved_tokens, 18000)
        with patch("openai.OpenAI", return_value=client):
            result, usage = process_analysis(job)
        client.responses.parse.assert_called_once()
        client.responses.create.assert_not_called()
        self.assertEqual(result["data"]["description"], "Descripción visual conservada.")
        self.assertEqual((usage.input_tokens, usage.output_tokens), (30, 20))

    def test_legacy_job_without_strategy_marker_keeps_preliminary_description(self):
        job, client = self.enqueue(), self.provider()
        job.result.pop("research_description_only")
        job.result.pop("reservation_per_attempt")
        job.result["attempt_limit"] = 2
        job.reserved_tokens = 58000
        job.save()
        job = _claim_job()  # Old queued reservations must be reconciled before spending.
        normalization = client.responses.parse.return_value
        client.responses.parse.side_effect = [SimpleNamespace(status="completed",
            output_parsed=DescriptionAnalysis(description="Descripción anterior.", warnings=[], questions=[]),
            usage=SimpleNamespace(input_tokens=30, output_tokens=20)), normalization]
        with patch("openai.OpenAI", return_value=client):
            result, usage = process_analysis(job)
        self.assertEqual(client.responses.parse.call_count, 2)
        self.assertEqual(client.responses.create.call_count, 3)
        self.assertFalse(result["research_description_only"])
        self.assertEqual((usage.input_tokens, usage.output_tokens), (24600, 400))

    def test_expired_lease_accounts_the_strategy_reserved_before_execution(self):
        self.limits.ai_enabled = False
        self.limits.save()
        for only_research, reservation in ((True, 20000), (False, 29000)):
            with self.subTest(research_only=only_research):
                result = {"research_requested": True, "attempt_limit": 1}
                if only_research:
                    result["research_description_only"] = True
                job = AnalysisJob.objects.create(machine=self.machine, revision=self.machine.revision,
                    requested_by=self.user, fingerprint=("b" if only_research else "c") * 64,
                    mode="description", result=result, status="running", attempts=1,
                    locked_at=timezone.now() - timedelta(hours=1), reserved_tokens=reservation)
                self.assertIsNone(_claim_job())
                job.refresh_from_db()
                self.assertEqual(job.status, "failed")
                self.assertEqual(job.input_tokens, reservation)
                self.assertEqual(job.reserved_tokens, 0)

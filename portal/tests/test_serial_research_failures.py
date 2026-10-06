"""Serial research failures stay distinguishable from absent public evidence."""
import json
from unittest.mock import Mock, patch

import httpx2 as httpx
from openai import AuthenticationError, BadRequestError, NotFoundError, PermissionDeniedError, RateLimitError

from django.test import SimpleTestCase, TestCase, override_settings

from portal.models import Machine, PlatformSettings, User
from portal.processing import enqueue_analysis, process_next_job
from portal.research import compose_description, research_machine
from portal.tests.test_research import vision, web_response


PRIVATE_ERROR = "private-provider-detail OWNER-SECRET owner@example.invalid"


def provider_error(error_type, status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    return error_type(PRIVATE_ERROR, response=response, body={"private": PRIVATE_ERROR})


def no_credit_error():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    return RateLimitError(PRIVATE_ERROR, response=response,
                          body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}})


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-5.6-luna",
                   SECURE_SSL_REDIRECT=False)
class SerialResearchWorkerFailuresTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="serial-regression@example.invalid")
        self.machine = Machine.objects.create(owner=self.user, data={"serial": "UNIT123"},
            provenance={"serial": {"source": "user", "review": "confirmed"}})
        PlatformSettings.objects.create(ai_enabled=True)
        self.provider = self.enterContext(patch("openai.OpenAI"))
        self.enterContext(patch("portal.research_documents.collect_registered_fields", return_value=([], [], False)))
        self.enterContext(patch("portal.research_documents.collect_document_fields", return_value=([], [], False)))
        self.client.force_login(self.user)

    def run_job(self):
        job = enqueue_analysis(self.machine, self.user, mode="description", research=True,
            auto_apply=True, expected_revision=self.machine.revision, authorize_ai=True)
        self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.machine.refresh_from_db()
        return job

    def test_serial_configuration_rejections_fail_once_without_fictitious_usage_or_private_details(self):
        for error_type, status, code in (
            (AuthenticationError, 401, "credentials_unavailable"),
            (PermissionDeniedError, 403, "model_unavailable"),
            (NotFoundError, 404, "model_unavailable"),
        ):
            with self.subTest(error=error_type.__name__):
                self.machine.revision += 1
                self.machine.save(update_fields=["revision"])
                provider = self.provider.return_value
                provider.responses.create.reset_mock()
                provider.responses.create.side_effect = provider_error(error_type, status)
                job = self.run_job()
                self.assertEqual(job.status, "failed")
                self.assertEqual(job.result["provider_error_code"], code)
                self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (0, 0, 0))
                self.assertEqual(job.attempts, 1)
                self.assertEqual(provider.responses.create.call_count, 1)
                provider.responses.parse.assert_not_called()
                response = self.client.get(f"/api/analisis/{job.pk}/")
                self.assertEqual(response.status_code, 200)
                state = response.json()
                self.assertEqual(state["status"], "failed")
                self.assertTrue(state["error"])
                self.assertIn("borrador", state["error"])
                self.assertNotIn("fotograf", state["error"].casefold())
                self.assertNotIn("archivos", state["error"].casefold())
                self.assertIsNone(state["result"])
                self.assertEqual(state["auto_apply"]["reason"], "analysis_failed")
                self.assertNotIn(PRIVATE_ERROR, response.content.decode())
                self.assertNotIn(PRIVATE_ERROR, str(job.result))
                self.assertNotIn("description", self.machine.data)

    def test_serial_identity_extraction_rejection_preserves_only_prior_search_consumption(self):
        provider = self.provider.return_value
        provider.responses.create.return_value = web_response(
            text="Caterpillar modelo 420F2, número de serie UNIT123.", input_tokens=120, output_tokens=80)
        provider.responses.parse.side_effect = provider_error(AuthenticationError, 401)
        job = self.run_job()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.result["provider_error_code"], "credentials_unavailable")
        self.assertEqual((job.input_tokens, job.output_tokens, job.reserved_tokens), (8120, 80, 0))
        self.assertEqual(provider.responses.create.call_count, 1)
        self.assertEqual(provider.responses.parse.call_count, 1)
        self.assertNotIn(PRIVATE_ERROR, str(job.result))

    def test_completed_search_without_identity_stays_incomplete_without_claiming_photos(self):
        provider = self.provider.return_value
        provider.responses.create.return_value = web_response(text="No se encontró una referencia pública.", sources=[])
        job = self.run_job()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["research"]["status"], "no_results")
        self.assertEqual(job.asset_ids, [])
        self.assertEqual(self.machine.data["serial"], "UNIT123")
        self.assertEqual(self.machine.data["description"], "Maquinaria.")
        provider.responses.parse.assert_not_called()
        state = self.client.get(f"/api/analisis/{job.pk}/").json()
        self.assertIn("brand", state["completion"]["missing_fields"])
        self.assertIn("model", state["completion"]["missing_fields"])
        self.assertIn("price_range", state["completion"]["missing_fields"])
        self.assertNotIn("fotograf", self.machine.data["description"].casefold())

    def test_other_provider_rejection_records_safe_http_diagnostics_without_inventing_identity(self):
        self.provider.return_value.responses.create.side_effect = provider_error(BadRequestError, 400)
        job = self.run_job()
        self.assertEqual(job.status, "completed")
        research = job.result["research"]
        self.assertEqual(research["status"], "degraded")
        self.assertTrue(research["diagnostics"]["stages"])
        for stage in research["diagnostics"]["stages"]:
            self.assertEqual(stage["error_type"], "BadRequestError")
            self.assertEqual(stage["error_status"], 400)
        self.assertNotIn("brand", self.machine.data)
        self.assertNotIn("model", self.machine.data)
        self.assertEqual(self.machine.data["description"], "Maquinaria.")
        self.assertNotIn(PRIVATE_ERROR, str(job.result))


class ResearchFailurePreservationTests(SimpleTestCase):
    def test_rejected_search_preserves_visual_readings_and_stops_without_charging_rejected_calls(self):
        client = Mock()
        client.responses.create.side_effect = provider_error(NotFoundError, 404)
        visual = vision()
        with patch("portal.research_documents.collect_registered_fields", return_value=([], [], False)), \
                patch("portal.research_documents.collect_document_fields", return_value=([], [], False)):
            outcome, usage = research_machine(client, "gpt-5.6-luna", visual)
        self.assertEqual(outcome["status"], "degraded")
        self.assertEqual(outcome["provider_error_code"], "model_unavailable")
        self.assertEqual(outcome["diagnostics"]["stages"][0]["error_status"], 404)
        self.assertEqual(visual["data"]["brand"], "Caterpillar")
        self.assertEqual(visual["data"]["model"], "420F2")
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.estimated_tokens), (0, 0, 0))
        self.assertEqual(client.responses.create.call_count, 1)
        client.responses.parse.assert_not_called()
        self.assertNotIn(PRIVATE_ERROR, str(outcome))

    def test_generic_description_makes_no_claim_about_input_images(self):
        self.assertEqual(compose_description({"serial": "UNIT123"}, {}), "Maquinaria.")
        self.assertEqual(compose_description({}, {}, "Excavadoras"), "Excavadora.")


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-5.6-luna",
                   SECURE_SSL_REDIRECT=False)
class NoCreditWorkerFailureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="no-credit@example.invalid")
        self.machine = Machine.objects.create(owner=self.user, data={"serial": "NO-CREDIT-001"},
            provenance={"serial": {"source": "user", "review": "confirmed"}})
        PlatformSettings.objects.create(ai_enabled=True)
        self.provider = self.enterContext(patch("openai.OpenAI"))
        self.client.force_login(self.user)

    def test_insufficient_quota_fails_once_without_consumption_or_auto_apply(self):
        self.provider.return_value.responses.parse.side_effect = no_credit_error()
        job = enqueue_analysis(self.machine, self.user, mode="description", auto_apply=True,
            expected_revision=self.machine.revision, authorize_ai=True)

        self.assertTrue(process_next_job())
        self.assertFalse(process_next_job())

        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.input_tokens, job.output_tokens, job.reserved_tokens),
                         ("failed", 1, 0, 0, 0))
        self.assertEqual(job.result["provider_error_code"], "billing_unavailable")
        self.assertIn("saldo", job.error)
        self.assertNotIn(PRIVATE_ERROR, str(job.result))
        self.assertNotIn("description", self.machine.data)
        self.provider.return_value.responses.parse.assert_called_once()
        response = self.client.get(f"/api/analisis/{job.pk}/")
        self.assertEqual(response.status_code, 200)
        state = response.json()
        self.assertEqual(state["failure_code"], "billing_unavailable")
        self.assertIsNone(state["result"])
        self.assertNotIn(PRIVATE_ERROR, response.content.decode())

    def test_manual_service_retry_creates_one_fresh_job_and_preserves_the_failed_record(self):
        self.provider.return_value.responses.parse.side_effect = no_credit_error()
        failed = enqueue_analysis(self.machine, self.user, mode="description", auto_apply=True,
                                  expected_revision=self.machine.revision, authorize_ai=True)
        self.assertTrue(process_next_job())
        failed.refresh_from_db()
        before = {
            "fingerprint": failed.fingerprint, "attempts": failed.attempts,
            "input": failed.input_tokens, "output": failed.output_tokens,
            "result": failed.result.copy(),
        }

        # This is the normal browser endpoint; enqueue itself is not mocked.
        # Its matching fingerprint must replace only an allowlisted service
        # failure, then repeated clicks must deduplicate the queued retry.
        body = {"consent": True, "revision": self.machine.revision, "research": False,
                "auto_apply": True}
        endpoint = f"/api/maquinarias/{self.machine.pk}/analizar/"
        first = self.client.post(endpoint, data=json.dumps(body), content_type="application/json")
        self.assertEqual(first.status_code, 200, first.content)
        retry_id = first.json()["id"]
        self.assertNotEqual(retry_id, str(failed.pk))
        second = self.client.post(endpoint, data=json.dumps(body), content_type="application/json")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["id"], retry_id)

        failed.refresh_from_db()
        retry = failed.machine.analysis_jobs.get(pk=retry_id)
        self.assertEqual(failed.status, "failed")
        self.assertEqual({"fingerprint": failed.fingerprint, "attempts": failed.attempts,
                          "input": failed.input_tokens, "output": failed.output_tokens,
                          "result": failed.result}, before)
        self.assertEqual(retry.status, "queued")
        self.assertNotEqual(retry.fingerprint, failed.fingerprint)
        self.assertEqual(retry.result["retry_of"], str(failed.pk))
        self.assertEqual(retry.result["retry_origin_fingerprint"], failed.fingerprint)
        self.assertEqual(failed.machine.analysis_jobs.count(), 2)

        # A replacement that later fails for an unrelated reason cannot inherit
        # the original provider code and become another free retry.
        with patch("portal.processing.process_analysis", side_effect=ValueError("local failure")):
            self.assertTrue(process_next_job())
        retry.refresh_from_db()
        self.assertEqual(retry.status, "failed")
        self.assertNotIn("provider_error_code", retry.result)
        terminal = self.client.post(endpoint, data=json.dumps(body), content_type="application/json")
        self.assertEqual(terminal.status_code, 200, terminal.content)
        self.assertEqual(terminal.json()["id"], retry_id)
        self.assertEqual(failed.machine.analysis_jobs.count(), 2)

    def test_completed_service_retry_is_reused_when_the_original_request_is_repeated(self):
        self.provider.return_value.responses.parse.side_effect = no_credit_error()
        failed = enqueue_analysis(self.machine, self.user, mode="description", authorize_ai=True)
        self.assertTrue(process_next_job())
        failed.refresh_from_db()
        endpoint = f"/api/maquinarias/{self.machine.pk}/analizar/"
        body = {"consent": True, "revision": self.machine.revision, "research": False}
        created = self.client.post(endpoint, data=json.dumps(body), content_type="application/json")
        self.assertEqual(created.status_code, 200, created.content)
        retry_id = created.json()["id"]

        # Worker completion replaces `result`, so retry-chain identity must
        # come from deterministic fingerprints rather than JSON metadata.
        with patch("portal.processing.process_analysis", return_value=(
                {}, Mock(input_tokens=0, output_tokens=0))):
            self.assertTrue(process_next_job())
        completed = failed.machine.analysis_jobs.get(pk=retry_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result, {})

        repeated = self.client.post(endpoint, data=json.dumps(body), content_type="application/json")
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(repeated.json()["id"], retry_id)
        self.assertEqual(failed.machine.analysis_jobs.count(), 2)

    def test_analysis_api_drops_unrecognized_provider_failure_codes(self):
        job = enqueue_analysis(self.machine, self.user, mode="description", authorize_ai=True)
        job.status = "failed"
        job.error = "No pudimos completar el análisis."
        job.result = {"provider_error_code": PRIVATE_ERROR}
        job.save(update_fields=["status", "error", "result"])

        response = self.client.get(f"/api/analisis/{job.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["failure_code"], "")
        self.assertNotIn(PRIVATE_ERROR, response.content.decode())

        retry = self.client.post(f"/api/maquinarias/{self.machine.pk}/analizar/", data=json.dumps({
            "consent": True, "revision": self.machine.revision, "research": False,
        }), content_type="application/json")
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json()["id"], str(job.pk))
        self.assertEqual(self.machine.analysis_jobs.count(), 1)

    def test_insufficient_quota_stops_a_price_lookup_without_estimated_usage(self):
        from portal.valuation import estimate_machine

        client = Mock()
        client.responses.create.side_effect = no_credit_error()
        result = {"data": {"brand": "Caterpillar", "model": "420F2"},
                  "provenance": {"brand": {"source": "user", "review": "confirmed"},
                                 "model": {"source": "user", "review": "confirmed"}}}
        with self.assertRaises(RateLimitError) as raised:
            estimate_machine(client, "gpt-5.6-luna", result, result)

        usage = raised.exception.accounted_usage
        self.assertEqual(usage.as_dict(), {"input_tokens": 0, "output_tokens": 0,
                                            "estimated_tokens": 0, "web_search_calls": 0})
        client.responses.create.assert_called_once()

    def test_insufficient_quota_stops_completion_without_estimated_usage(self):
        from portal.ai_completion import complete_machine_reference

        client = Mock()
        client.responses.parse.side_effect = no_credit_error()
        result = {"data": {"brand": "Caterpillar", "model": "420F2"},
                  "provenance": {"brand": {"source": "user", "review": "confirmed"},
                                 "model": {"source": "user", "review": "confirmed"}}}
        with self.assertRaises(RateLimitError) as raised:
            complete_machine_reference(client, "gpt-5.6-luna", result, result)

        self.assertEqual(raised.exception.accounted_usage.as_dict(),
                         {"input_tokens": 0, "output_tokens": 0, "estimated_tokens": 0, "web_search_calls": 0})
        client.responses.parse.assert_called_once()

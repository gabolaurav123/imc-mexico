"""Serial research failures stay distinguishable from absent public evidence."""
from unittest.mock import Mock, patch

import httpx2 as httpx
from openai import AuthenticationError, BadRequestError, NotFoundError, PermissionDeniedError

from django.test import SimpleTestCase, TestCase, override_settings

from portal.models import Machine, PlatformSettings, User
from portal.processing import enqueue_analysis, process_next_job
from portal.research import compose_description, research_machine
from portal.tests.test_research import vision, web_response


PRIVATE_ERROR = "private-provider-detail OWNER-SECRET owner@example.invalid"


def provider_error(error_type, status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    return error_type(PRIVATE_ERROR, response=response, body={"private": PRIVATE_ERROR})


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

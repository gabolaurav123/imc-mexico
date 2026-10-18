"""Photo identifications retain the fast path of verified local references."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import threading

from django.test import SimpleTestCase

from portal.research import ResearchField, UsageTotals, normalize_direct_fields, research_machine
from portal.tests.test_research import candidate, vision, web_response, TEXT
from portal.tests.test_research_stages import extraction, response


class PhotoLocalResearchLatencyTests(SimpleTestCase):
    def reference(self, serial=None):
        identity = {"brand": "Caterpillar", "model": "320", "serial": serial}
        url = "https://www.cat.com/en_US/products/320.html"
        title = "Caterpillar 320 specifications"
        values = {"power": "121 kW", "weight": "21500 kg", "digging_depth": "6720 mm"}
        evidence = {key: f"Caterpillar 320 {key}: {value}." for key, value in values.items()}
        fields = [ResearchField(key=key, value=value, scope="model", source_url=url,
                                evidence=evidence[key], matched_serial=None,
                                matched_brand="Caterpillar", matched_model="320")
                  for key, value in values.items()]
        passages = [{"source_url": url, "text": text} for text in evidence.values()]
        return normalize_direct_fields(identity, "model", [{"url": url, "title": title}],
                                       "\n".join(evidence.values()), passages,
                                       {url: title}, direct_fields=fields)

    def call(self, local, *, serial=None, allowed=None):
        data = {"brand": "Caterpillar", "model": "320"}
        provenance = {key: {"source": "image", "review": "clear", "component": "machine"}
                      for key in data}
        snapshot = {"category": "Excavadoras", "data": {},
                    "provenance": {"category": {"source": "user", "review": "confirmed"}}}
        if serial:
            snapshot["data"]["serial"] = serial
            snapshot["provenance"]["serial"] = {"source": "user", "review": "confirmed"}
        result = {"category": "Excavadoras", "data": data, "provenance": provenance,
                  "fields": [], "warnings": []}
        with patch("portal.knowledge.research_from_knowledge", return_value=local), \
                patch("portal.research_pipeline.research_identified_machine",
                      return_value=({"status": "no_results"}, UsageTotals())) as pipeline:
            outcome = research_machine(Mock(), "gpt-6-luna", result, snapshot,
                                       allowed=allowed, allowed_categories=["Excavadoras"],
                                       knowledge_category=SimpleNamespace(slug="excavadoras"))
        return outcome, pipeline

    def test_clear_photo_identity_reuses_local_core_and_only_researches_missing_period(self):
        local = self.reference()
        self.assertEqual({field["key"] for field in local["fields"]}, {"power", "weight", "digging_depth"})
        _, pipeline = self.call(local)
        seed = pipeline.call_args.kwargs["initial_evidence"]
        self.assertTrue(seed["prioritize_local_reference"])
        self.assertEqual(set(seed["local_field_keys"]), {"power", "weight", "digging_depth"})
        self.assertEqual(len(seed["direct_fields"]), 3)

    def test_serial_still_reaches_pipeline_with_exact_unit_identity(self):
        _, pipeline = self.call(self.reference("UNIT123"), serial="UNIT123")
        self.assertEqual(pipeline.call_args.args[3]["serial"], "UNIT123")
        self.assertEqual(pipeline.call_args.args[4], "exact_serial")

    def test_altered_local_evidence_cannot_activate_the_fast_path(self):
        local = self.reference()
        local["fields"][0]["value"] = "999 kW"
        _, pipeline = self.call(local)
        self.assertNotIn("initial_evidence", pipeline.call_args.kwargs)

    def test_cancelled_authorization_does_not_send_missing_period_query(self):
        (outcome, _), pipeline = self.call(self.reference(), allowed=lambda: False)
        pipeline.assert_not_called()
        self.assertEqual(outcome["status"], "degraded")
        self.assertEqual(outcome["fields"], [])


class ParallelModelResearchTests(SimpleTestCase):
    def test_catalogue_and_manual_overlap_but_merge_evidence_in_order(self):
        manual_started = threading.Event()
        client = Mock()

        def search(**kwargs):
            stage = json.loads(kwargs["input"])["research_stage"]
            if stage == "manufacturer":
                return web_response(sources=[])
            if stage == "catalogs":
                # Sequential execution cannot satisfy this dependency. The
                # returned evidence must still precede the manual's passage.
                self.assertTrue(manual_started.wait(2), "Independent searches did not overlap")
                return response(TEXT, "https://www.ritchiespecs.com/model/caterpillar-420f2")
            manual_started.set()
            return response("Caterpillar 420F2: peso 8400 kg.")

        client.responses.create.side_effect = search
        client.responses.parse.return_value = extraction(candidate(), candidate(1, key="weight", value="8400 kg"))
        with patch("portal.research_documents.collect_document_fields", return_value=([], [], False)):
            value, usage = research_machine(client, "gpt-6-luna", vision())
        self.assertEqual({field["key"]: field["value"] for field in value["fields"]},
                         {"power": "70 kW", "weight": "8400 kg"})
        self.assertEqual(value["diagnostics"]["parallel_stage_count"], 2)
        self.assertEqual([stage["stage"] for stage in value["diagnostics"]["stages"]],
                         ["manufacturer", "catalogs", "manuals"])
        self.assertEqual(usage.web_search_calls, 3)

    def test_parallel_cross_source_conflicts_still_remove_ambiguous_specification(self):
        client = Mock()

        def search(**kwargs):
            stage = json.loads(kwargs["input"])["research_stage"]
            if stage == "manufacturer":
                return web_response(sources=[])
            return (response(TEXT, "https://www.ritchiespecs.com/model/caterpillar-420f2")
                    if stage == "catalogs" else response("Caterpillar 420F2: potencia 99 kW."))

        client.responses.create.side_effect = search
        client.responses.parse.return_value = extraction(candidate(), candidate(1, value="99 kW"))
        with patch("portal.research_documents.collect_document_fields", return_value=([], [], False)):
            value, _ = research_machine(client, "gpt-6-luna", vision())
        self.assertEqual(value["fields"], [])
        self.assertEqual(value["diagnostics"]["rejection_counts"]["conflicting_values"], 1)

    def test_cancellation_discards_all_parallel_evidence_but_counts_both_calls(self):
        authorized = threading.Event()
        authorized.set()
        client = Mock()

        def search(**kwargs):
            stage = json.loads(kwargs["input"])["research_stage"]
            if stage == "manuals":
                authorized.clear()
            return response(TEXT)

        client.responses.create.side_effect = search
        value, usage = research_machine(client, "gpt-6-luna", vision(), allowed=authorized.is_set)
        self.assertEqual(value["status"], "degraded")
        self.assertEqual(value["fields"], [])
        self.assertEqual(usage.web_search_calls, 3)
        self.assertEqual(usage.input_tokens, 3 * (120 + 8000))
        client.responses.parse.assert_not_called()

    def test_first_provider_failure_does_not_start_parallel_requests(self):
        client = Mock()
        error = RuntimeError("Unavailable")
        error.status_code = 401
        client.responses.create.side_effect = error
        with patch("portal.research_pipeline._parallel_search_pair") as parallel:
            value, _ = research_machine(client, "gpt-6-luna", vision())
        parallel.assert_not_called()
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(value["diagnostics"]["parallel_stage_count"], 0)

    def test_serial_research_keeps_dependent_requests_sequential(self):
        client = Mock()
        client.responses.create.return_value = web_response(sources=[])
        with patch("portal.research_pipeline._parallel_search_pair") as parallel:
            value, _ = research_machine(client, "gpt-6-luna", vision(serial="UNIT123"))
        parallel.assert_not_called()
        self.assertEqual([stage["stage"] for stage in value["diagnostics"]["stages"]],
                         ["serial", "manufacturer", "catalogs"])

    def test_joint_reservation_failure_keeps_sequential_budget_checks(self):
        client = Mock()
        # After a larger response, the observed cost is the admission floor
        # for each sibling. Both plus normalization cannot fit in this case.
        client.responses.create.side_effect = [web_response(sources=[], input_tokens=20000),
                                               web_response(sources=[]), web_response(sources=[])]
        with patch("portal.research_pipeline._parallel_search_pair") as parallel:
            value, _ = research_machine(client, "gpt-6-luna", vision())
        parallel.assert_not_called()
        self.assertEqual(value["diagnostics"]["parallel_stage_count"], 0)
        self.assertEqual(client.responses.create.call_count, 3)

    def test_failed_parallel_stage_accounts_the_completed_sibling_before_raising(self):
        from portal.tests.test_serial_research_failures import no_credit_error
        client = Mock()
        failure = no_credit_error()

        def search(**kwargs):
            stage = json.loads(kwargs["input"])["research_stage"]
            if stage == "catalogs":
                raise failure
            return web_response(sources=[])

        client.responses.create.side_effect = search
        with self.assertRaises(type(failure)) as caught:
            research_machine(client, "gpt-6-luna", vision())
        # The rejected catalogue request costs nothing, but both completed
        # manufacturer and manual requests must remain in the worker's usage.
        self.assertEqual(caught.exception.accounted_usage.web_search_calls, 2)
        self.assertEqual(caught.exception.accounted_usage.input_tokens, 2 * (120 + 8000))
        self.assertEqual(caught.exception.accounted_usage.output_tokens, 160)
        client.responses.parse.assert_not_called()

    def test_failed_parallel_stage_accounts_the_timed_out_sibling_conservatively(self):
        from portal.ai_model import token_reservation
        from portal.research import SEARCH_RESERVATION
        from portal.tests.test_serial_research_failures import no_credit_error
        client = Mock()
        failure = no_credit_error()

        def search(**kwargs):
            stage = json.loads(kwargs["input"])["research_stage"]
            if stage == "catalogs":
                raise failure
            if stage == "manuals":
                raise TimeoutError("Uncertain provider outcome")
            return web_response(sources=[])

        client.responses.create.side_effect = search
        with self.assertRaises(type(failure)) as caught:
            research_machine(client, "gpt-6-luna", vision())
        usage = caught.exception.accounted_usage
        self.assertEqual(usage.web_search_calls, 1)
        self.assertEqual(usage.estimated_tokens, 8000 + token_reservation("gpt-6-luna", SEARCH_RESERVATION))

    def test_unexpected_consent_failure_preserves_prior_and_pending_usage(self):
        from django.db import OperationalError
        from portal.models import AnalysisJob
        for failure_type in (OperationalError, AnalysisJob.DoesNotExist):
            for fail_after in ("manufacturer", "manuals"):
                with self.subTest(failure=failure_type.__name__, stage=fail_after):
                    completed = threading.Event()
                    client = Mock()
                    failure = failure_type("Unavailable local authorization state")

                    def search(**kwargs):
                        stage = json.loads(kwargs["input"])["research_stage"]
                        if stage == fail_after:
                            completed.set()
                        return web_response(sources=[])

                    def allowed():
                        if completed.is_set():
                            raise failure
                        return True

                    client.responses.create.side_effect = search
                    with self.assertRaises(failure_type) as caught:
                        research_machine(client, "gpt-6-luna", vision(), allowed=allowed)
                    calls = 1 if fail_after == "manufacturer" else 3
                    usage = caught.exception.accounted_usage
                    self.assertIs(caught.exception, failure)
                    self.assertEqual(client.responses.create.call_count, calls)
                    self.assertEqual(usage.web_search_calls, calls)
                    self.assertEqual(usage.input_tokens, calls * (120 + 8000))
                    self.assertEqual(usage.output_tokens, calls * 80)
                    client.responses.parse.assert_not_called()

    def test_malformed_pending_usage_does_not_hide_original_authorization_failure(self):
        from django.db import OperationalError
        from portal.ai_model import token_reservation
        from portal.research import SEARCH_RESERVATION
        completed = threading.Event()
        client = Mock()
        failure = OperationalError("Unavailable local authorization state")

        def search(**kwargs):
            stage = json.loads(kwargs["input"])["research_stage"]
            if stage == "manuals":
                completed.set()
                return web_response(sources=[], input_tokens="malformed")
            return web_response(sources=[])

        def allowed():
            if completed.is_set():
                raise failure
            return True

        client.responses.create.side_effect = search
        with self.assertRaises(OperationalError) as caught:
            research_machine(client, "gpt-6-luna", vision(), allowed=allowed)
        usage = caught.exception.accounted_usage
        self.assertIs(caught.exception, failure)
        self.assertEqual(usage.web_search_calls, 3)
        self.assertEqual(usage.input_tokens, 2 * (120 + 8000) + token_reservation("gpt-6-luna", SEARCH_RESERVATION))
        self.assertEqual(usage.output_tokens, 160)

    def test_executor_failure_after_first_submission_retains_started_request_usage(self):
        from concurrent.futures import ThreadPoolExecutor
        client = Mock()
        client.responses.create.return_value = web_response(sources=[])
        pool = ThreadPoolExecutor(max_workers=1)
        original_submit = pool.submit
        submissions = 0

        def submit(*args, **kwargs):
            nonlocal submissions
            submissions += 1
            if submissions == 2:
                raise RuntimeError("Cannot start another local worker")
            return original_submit(*args, **kwargs)

        with patch("portal.research_pipeline.ThreadPoolExecutor", return_value=pool), \
                patch.object(pool, "submit", side_effect=submit):
            with self.assertRaises(RuntimeError) as caught:
                research_machine(client, "gpt-6-luna", vision())
        usage = caught.exception.accounted_usage
        self.assertEqual(client.responses.create.call_count, 2)
        self.assertEqual(usage.web_search_calls, 2)
        self.assertEqual(usage.input_tokens, 2 * (120 + 8000))
        self.assertEqual(usage.output_tokens, 160)

import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from portal.research import (
    NORMALIZE_RESERVATION, SEARCH_RESERVATION, ResearchCandidates,
    is_validated_web_field, merge_research, research_machine,
)
from portal.tests.test_research import candidate, vision, web_response, URL
from portal.tests.test_research import fact, normalized, IDENTITY


def extraction(*items):
    return SimpleNamespace(status="completed", output_parsed=ResearchCandidates(fields=list(items)),
                           usage=SimpleNamespace(input_tokens=200, output_tokens=100))


def response(text, url=URL):
    result = web_response(text=text, sources=[{"url": url}])
    result.output_text = text + f" [Fuente]({url})"
    result.output[1]["content"][0].update(text=result.output_text, annotations=[{
        "type": "url_citation", "url": url, "title": "Caterpillar 420F2",
        "start_index": len(text) + 1, "end_index": len(result.output_text),
    }])
    return result


class StagedResearchTests(SimpleTestCase):
    def test_null_model_metadata_cannot_hide_an_explicit_conflicting_model(self):
        for prefix in ("Caterpillar modelo 430F2", "Caterpillar 430F2", "CAT 430F2"):
            with self.subTest(prefix=prefix):
                text = f"{prefix}, número de serie UNIT123, potencia 70 kW."
                research = normalized([fact(scope="exact_serial", matched_serial="UNIT123", matched_model=None, evidence=text)],
                                      {**IDENTITY, "serial": "UNIT123"}, text)
                self.assertEqual(research["fields"], [])
                self.assertEqual(research["diagnostics"]["rejection_counts"], {"model_conflict": 1})

    def test_category_hint_is_catalog_bound_and_human_category_takes_precedence(self):
        for category, expected in [("Compactadores", "compactador compactor"), ("private secret location", None)]:
            with self.subTest(category=category):
                client = Mock()
                client.responses.create.return_value = web_response(sources=[])
                result = vision(serial="UNIT123")
                result["data"]["brand"] = "HESSEN"
                result["data"].pop("model")
                result["provenance"].pop("model")
                snapshot = {"category": category, "provenance": {"category": {"source": "user"}}}
                research_machine(client, "gpt-4.1-mini", result, snapshot,
                                 allowed_categories=["Compactadores", "Retroexcavadoras"])
                for call in client.responses.create.call_args_list:
                    payload = json.loads(call.kwargs["input"])
                    self.assertNotIn("private secret", call.kwargs["input"])
                    self.assertNotIn("retroexcavadora backhoe", payload["query"])
                    if expected:
                        self.assertIn(expected, payload["query"])
                self.assertEqual(client.responses.create.call_count, 3)

    def test_empty_serial_search_continues_with_model_manufacturer_and_external_catalogs(self):
        client = Mock()
        client.responses.create.side_effect = [web_response(sources=[]), response("Caterpillar 420F2: potencia 70 kW."), web_response(sources=[])]
        client.responses.parse.return_value = extraction(candidate())
        research, usage = research_machine(client, "gpt-4.1-mini", vision(serial="UNIT123"))
        requests = [json.loads(call.kwargs["input"]) for call in client.responses.create.call_args_list]
        self.assertEqual([r["research_stage"] for r in requests], ["serial", "manufacturer", "catalogs"])
        self.assertEqual(requests[0]["identifiers"]["serial"], "UNIT123")
        self.assertIsNone(requests[1]["identifiers"]["serial"])
        self.assertNotIn("UNIT123", requests[1]["query"])
        self.assertNotIn("filters", client.responses.create.call_args_list[1].kwargs["tools"][0])
        self.assertIn("site:cat.com", requests[1]["query"])
        self.assertIn("site:lectura-specs.com", requests[2]["query"])
        self.assertIn("site:ritchiespecs.com", requests[2]["query"])
        self.assertEqual(research["fields"][0]["value"], "70 kW")
        self.assertEqual(research["match"], "model")
        self.assertEqual(usage.web_search_calls, 3)
        self.assertEqual(research["diagnostics"]["stage_count"], 3)

    def test_model_only_uses_manual_fallback_and_keeps_late_evidence(self):
        client = Mock()
        client.responses.create.side_effect = [web_response(sources=[]), web_response(sources=[]), response("Caterpillar 420F2: peso 8400 kg.")]
        client.responses.parse.return_value = extraction(candidate(key="weight", value="8400 kg"))
        research, _ = research_machine(client, "gpt-4.1-mini", vision())
        self.assertEqual(research["fields"][0]["key"], "weight")
        self.assertEqual(json.loads(client.responses.create.call_args.kwargs["input"])["research_stage"], "manuals")

    def test_cross_stage_conflicts_are_omitted_not_last_writer_wins(self):
        client = Mock()
        client.responses.create.side_effect = [response("Caterpillar 420F2: potencia 70 kW."),
            response("Caterpillar 420F2: potencia 99 kW.", "https://www.ritchiespecs.com/model/caterpillar-420f2"), web_response(sources=[])]
        client.responses.parse.return_value = extraction(candidate(), candidate(1, value="99 kW"))
        research, _ = research_machine(client, "gpt-4.1-mini", vision())
        self.assertEqual(research["fields"], [])
        self.assertEqual(research["diagnostics"]["rejection_counts"]["conflicting_values"], 1)

    def test_legacy_site_query_rejects_cited_sources_outside_selected_domains(self):
        client = Mock()
        client.responses.create.side_effect = [response("Caterpillar 420F2: potencia 99 kW.", "https://cat.com.badsite.com/specs"),
            response("Caterpillar 420F2: potencia 99 kW.", "https://unrelated.com/specs"), web_response(sources=[])]
        research, _ = research_machine(client, "gpt-4.1-mini", vision())
        client.responses.parse.assert_not_called()
        self.assertEqual(research["fields"], [])
        self.assertEqual(research["sources"], [])

    def test_supported_models_keep_tool_domain_controls(self):
        client = Mock()
        client.responses.create.return_value = web_response(sources=[])
        research_machine(client, "gpt-5-mini", vision())
        self.assertEqual(client.responses.create.call_args_list[0].kwargs["tools"][0]["filters"],
                         {"allowed_domains": ["cat.com"]})

    def test_timeout_of_one_stage_preserves_evidence_from_others_and_counts_usage(self):
        client = Mock()
        client.responses.create.side_effect = [response("Caterpillar 420F2: potencia 70 kW."), TimeoutError("private secret"), web_response(sources=[])]
        client.responses.parse.return_value = extraction(candidate())
        research, usage = research_machine(client, "gpt-4.1-mini", vision())
        self.assertEqual(research["status"], "completed")
        self.assertFalse(research["diagnostics"]["search_complete"])
        self.assertEqual(usage.estimated_tokens, 16000 + SEARCH_RESERVATION)
        self.assertNotIn("private secret", str(research))
        merged = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, research)
        self.assertTrue(is_validated_web_field(merged, "power", "70 kW", merged["provenance"]["power"]))

    def test_cancellation_between_stages_stops_paid_calls_and_discards_suggestions(self):
        client = Mock()
        client.responses.create.return_value = response("Caterpillar 420F2: potencia 70 kW.")
        research, usage = research_machine(client, "gpt-4.1-mini", vision(), allowed=Mock(side_effect=[True, False]))
        self.assertEqual(client.responses.create.call_count, 1)
        client.responses.parse.assert_not_called()
        self.assertEqual(research["status"], "degraded")
        self.assertEqual(research["fields"], [])
        self.assertEqual(usage.web_search_calls, 1)

    def test_exact_serial_can_discover_missing_model_before_model_searches(self):
        client = Mock()
        result = vision(serial="UNIT123")
        result["data"].pop("model")
        result["provenance"].pop("model")
        client.responses.create.side_effect = [response("Caterpillar modelo 420F2, número de serie UNIT123."),
            response("Caterpillar 420F2: potencia 70 kW."), web_response(sources=[])]
        model = candidate(key="model", value="420F2", scope="exact_serial", matched_serial="UNIT123")
        client.responses.parse.side_effect = [extraction(model), extraction(model, candidate(1))]
        research, _ = research_machine(client, "gpt-4.1-mini", result)
        second = json.loads(client.responses.create.call_args_list[1].kwargs["input"])
        self.assertEqual(second["identifiers"]["model"], "420F2")
        self.assertIsNone(second["identifiers"]["serial"])
        self.assertEqual(research["identity"]["model"], "420F2")
        self.assertEqual({f["key"] for f in research["fields"]}, {"model", "power"})
        self.assertEqual(client.responses.parse.call_count, 2)

    def test_missing_model_is_never_guessed_from_brand_category_results(self):
        client = Mock()
        result = vision(serial="UNIT123")
        result["data"].pop("model")
        result["provenance"].pop("model")
        client.responses.create.return_value = response("Caterpillar 420F2: potencia 70 kW.")
        client.responses.parse.return_value = extraction(candidate(key="model", value="420F2"), candidate())
        research, _ = research_machine(client, "gpt-4.1-mini", result)
        self.assertIsNone(research["identity"]["model"])
        self.assertEqual(research["fields"], [])
        self.assertEqual(client.responses.parse.call_count, 1)

    def test_same_serial_from_another_brand_cannot_discover_a_model(self):
        client = Mock()
        result = vision(serial="UNIT123")
        result["data"].pop("model")
        result["provenance"].pop("model")
        client.responses.create.side_effect = [response("Komatsu modelo PC200, número de serie UNIT123."), web_response(sources=[]), web_response(sources=[])]
        client.responses.parse.return_value = extraction(candidate(key="model", value="PC200", scope="exact_serial",
            matched_brand="Komatsu", matched_model="PC200", matched_serial="UNIT123"))
        research, _ = research_machine(client, "gpt-4.1-mini", result)
        self.assertIsNone(research["identity"]["model"])
        self.assertEqual(research["fields"], [])
        self.assertNotIn("PC200", client.responses.create.call_args_list[1].kwargs["input"])

    def test_discovered_model_remains_provisional_until_all_serial_evidence_agrees(self):
        client = Mock()
        result = vision(serial="UNIT123")
        result["data"].pop("model")
        result["provenance"].pop("model")
        client.responses.create.side_effect = [response("Caterpillar modelo 420F2, número de serie UNIT123."),
            response("Caterpillar modelo 430F2, número de serie UNIT123."), response("Caterpillar 420F2: potencia 70 kW.")]
        first = candidate(key="model", value="420F2", scope="exact_serial", matched_serial="UNIT123")
        other = candidate(1, key="model", value="430F2", scope="exact_serial", matched_model="430F2", matched_serial="UNIT123")
        client.responses.parse.side_effect = [extraction(first), extraction(first, other, candidate(2))]
        research, _ = research_machine(client, "gpt-4.1-mini", result)
        self.assertIsNone(research["identity"]["model"])
        self.assertEqual(research["fields"], [])
        self.assertEqual(research["diagnostics"]["discovered_identity_rejected"], ["model"])

    def test_final_normalizer_failure_does_not_certify_provisional_identity(self):
        client = Mock()
        result = vision(serial="UNIT123")
        result["data"].pop("model")
        result["provenance"].pop("model")
        client.responses.create.side_effect = [response("Caterpillar modelo 420F2, número de serie UNIT123."), web_response(sources=[]), web_response(sources=[])]
        client.responses.parse.side_effect = [extraction(candidate(key="model", value="420F2", scope="exact_serial", matched_serial="UNIT123")), TimeoutError()]
        research, _ = research_machine(client, "gpt-4.1-mini", result)
        self.assertEqual(research["status"], "degraded")
        self.assertEqual(research["fields"], [])
        self.assertIsNone(research["identity"]["model"])

    def test_unknown_brand_has_no_fabricated_manufacturer_domain(self):
        client = Mock()
        result = vision()
        result["data"].update(brand="HESSEN", model="016-9020")
        client.responses.create.return_value = web_response(sources=[])
        research, _ = research_machine(client, "gpt-4.1-mini", result)
        first = client.responses.create.call_args_list[0].kwargs
        self.assertNotIn("filters", first["tools"][0])
        self.assertIn("HESSEN", json.loads(first["input"])["query"])
        self.assertEqual(research["status"], "no_results")

    def test_normalization_outage_accounts_reserved_usage_and_does_not_apply_raw_web_prose(self):
        client = Mock()
        client.responses.create.return_value = response("Caterpillar 420F2: potencia 70 kW.")
        client.responses.parse.side_effect = TimeoutError("private")
        research, usage = research_machine(client, "gpt-4.1-mini", vision())
        self.assertEqual(research["fields"], [])
        self.assertEqual(research["status"], "degraded")
        self.assertEqual(usage.estimated_tokens, 24000 + NORMALIZE_RESERVATION)
        self.assertEqual(research["error_stage"], "normalization")

    def test_auth_failure_does_not_repeat_three_known_failing_queries(self):
        client = Mock()
        error = RuntimeError("private")
        error.status_code = 401
        client.responses.create.side_effect = error
        research, _ = research_machine(client, "gpt-4.1-mini", vision())
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(research["status"], "degraded")

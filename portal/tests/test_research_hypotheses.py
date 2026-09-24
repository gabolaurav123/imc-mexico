import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research import (
    ResearchHypothesisCandidate, ResearchHypothesisCandidates,
    _accepted_visual_model_hint, is_validated_general_context, merge_research, research_machine,
)


BRAND = "DEVELON"
CATEGORY = "Excavadoras"
URL_A = "https://www.develon-ce.com/en/products/dx140lcr-5"
URL_B = "https://na.develon-ce.com/fr/construction-equipment/crawler-excavators/dx140lcr-5"


def visual_result():
    return {
        "data": {"brand": BRAND, "title": "Excavadora", "description": ""},
        "provenance": {"brand": {"source": "image", "review": "clear", "component": "machine"}},
        "plates": [], "fields": [], "warnings": [], "category": CATEGORY,
        "visual_description": "Excavadora de orugas naranja con cabina cerrada y cuchara.",
    }


def partial_visual_model_result(asset_id="image_001", accepted_asset_ids=("image_001",), *, source="image",
                                component="machine", kind="machine",
                                evidence='Rótulo lateral: "320D"; posible sufijo pequeño.'):
    return {
        "data": {"brand": "CAT", "model": "320D", "title": "Excavadora", "description": ""},
        "provenance": {
            "brand": {"source": "image", "review": "clear", "component": "machine", "asset_id": "image_001"},
            "model": {"source": source, "review": "needs_review", "component": component, "asset_id": asset_id},
        },
        "fields": [{"key": "model", "value": "320D", "source": source, "review": "needs_review",
                    "component": component, "asset_id": asset_id, "evidence": evidence}],
        "relevance": {"accepted_asset_ids": list(accepted_asset_ids)},
        "image_observations": [{"asset_id": asset_id, "kind": kind, "relevance": "machinery"}],
        "plates": [], "warnings": [], "category": "Excavadoras", "visual_description": "Excavadora de orugas.",
    }


def search_response(passages):
    chunks = []
    sources = []
    for url, title, text in passages:
        chunks.append(f"{text} [Fuente]({url})")
        sources.append({"url": url, "title": title})
    full = "\n\n".join(chunks)
    return SimpleNamespace(
        status="completed", output_text=full,
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        output=[
            {"type": "web_search_call", "status": "completed",
             "action": {"type": "search", "sources": sources}},
            {"type": "message", "content": [{"text": full, "annotations": []}]},
        ],
    )


class PhotoModelHypothesisTests(SimpleTestCase):
    def setUp(self):
        # Web-search regressions remain offline; direct-catalog transport has
        # dedicated tests and is not part of these provider response fixtures.
        direct = patch("portal.research._direct_catalog_context", return_value=None)
        direct.start()
        self.addCleanup(direct.stop)

    def test_same_source_title_can_supply_brand_when_cited_model_passage_omits_it(self):
        client = Mock()
        client.responses.create.return_value = search_response([
            (URL_A, "DEVELON DX140LCR-5 crawler excavator", "DX140LCR-5 crawler excavator."),
        ])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed=ResearchHypothesisCandidates(hypotheses=[
                ResearchHypothesisCandidate(model="DX140LCR-5", matched_brand=BRAND, passage_index=0),
            ]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        research, _ = research_machine(client, "gpt-5.6-luna", visual_result(),
                                       allowed_categories=[CATEGORY])
        self.assertEqual(research["hypotheses"][0]["model"], "DX140LCR-5")
        self.assertTrue(is_validated_general_context({"research": research}))

    def test_same_source_wrong_brand_title_does_not_supply_brand_context(self):
        client = Mock()
        client.responses.create.return_value = search_response([
            (URL_A, "KOMATSU DX140LCR-5 crawler excavator", "DX140LCR-5 crawler excavator."),
        ])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed=ResearchHypothesisCandidates(hypotheses=[
                ResearchHypothesisCandidate(model="DX140LCR-5", matched_brand=BRAND, passage_index=0),
            ]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        research, _ = research_machine(client, "gpt-5.6-luna", visual_result(),
                                       allowed_categories=[CATEGORY])
        self.assertEqual(research["hypotheses"], [])

    def test_verified_develon_hosts_filter_homonym_and_luna_gets_tool_domain_filter(self):
        client = Mock()
        corporate = "https://www.develon.com/en/the-group/"
        client.responses.create.return_value = search_response([
            (corporate, "DEVELON Group", "DEVELON Group corporate information."),
            (URL_A, "DEVELON DX140LCR-5", "DEVELON DX140LCR-5 crawler excavator."),
        ])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed=ResearchHypothesisCandidates(hypotheses=[
                # Citation indexes are rebuilt after the corporate host is
                # filtered, so the official passage is index zero.
                ResearchHypothesisCandidate(model="DX140LCR-5", matched_brand=BRAND, passage_index=0),
            ]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        research, _ = research_machine(client, "gpt-5.6-luna", visual_result(),
                                       allowed_categories=[CATEGORY])
        tool = client.responses.create.call_args.kwargs["tools"][0]
        query = json.loads(client.responses.create.call_args.kwargs["input"])["query"]
        self.assertEqual(tool["filters"], {"allowed_domains": ["develon-ce.com"]})
        self.assertIn("site:develon-ce.com", query)
        self.assertIn("excavator", query)
        self.assertEqual([source["url"] for source in research["sources"]], [URL_A])
        self.assertEqual(research["hypotheses"][0]["model"], "DX140LCR-5")
        self.assertNotIn("develon.com", json.dumps(research))

    def test_withdrawal_after_search_prevents_the_next_provider_call(self):
        client = Mock()
        client.responses.create.return_value = search_response([
            (URL_A, "DEVELON DX140LCR-5", "DEVELON DX140LCR-5 crawler excavator."),
        ])
        research, _ = research_machine(client, "gpt-4.1-mini", visual_result(),
            allowed=Mock(side_effect=[True, False]), allowed_categories=[CATEGORY])
        self.assertEqual(research["status"], "degraded")
        self.assertEqual(research["hypotheses"], [])
        client.responses.parse.assert_not_called()

    def test_two_cited_sources_create_supported_hypothesis_and_period_without_fields(self):
        client = Mock()
        client.responses.create.return_value = search_response([
            (URL_A, "DEVELON DX140LCR-5", "DEVELON DX140LCR-5 crawler excavator. Production years: 2019-2023."),
            (URL_B, "DEVELON DX140LCR-5 Specifications", "DEVELON DX140LCR-5 excavator; production years 2019-2023."),
        ])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed=ResearchHypothesisCandidates(hypotheses=[
                ResearchHypothesisCandidate(model="DX140LCR-5", matched_brand=BRAND, passage_index=0),
                ResearchHypothesisCandidate(model="DX140LCR-5", matched_brand=BRAND, passage_index=1),
            ]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        research, _ = research_machine(client, "gpt-4.1-mini", visual_result(),
                                       allowed_categories=[CATEGORY])

        self.assertEqual(research["status"], "general_context")
        self.assertEqual(research["fields"], [])
        self.assertIsNone(research["identity"]["model"])
        self.assertEqual(len(research["hypotheses"]), 1)
        hypothesis = research["hypotheses"][0]
        self.assertEqual(hypothesis["model"], "DX140LCR-5")
        self.assertEqual(hypothesis["confidence"], "supported")
        self.assertEqual(hypothesis["support_count"], 2)
        self.assertEqual(hypothesis["production_period"]["from"], "2019")
        self.assertEqual(hypothesis["production_period"]["to"], "2023")
        self.assertTrue(is_validated_general_context({"research": research}))

        merged = merge_research(visual_result(), research)
        self.assertNotIn("model", merged["data"])
        self.assertEqual(merged["research"]["hypotheses"][0]["model"], "DX140LCR-5")

    def test_single_source_is_a_lead_and_unrelated_or_wrong_brand_candidates_are_dropped(self):
        client = Mock()
        client.responses.create.return_value = search_response([
            (URL_A, "DEVELON DX140LCR-5", "DEVELON DX140LCR-5 crawler excavator."),
        ])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed=ResearchHypothesisCandidates(hypotheses=[
                ResearchHypothesisCandidate(model="DX140LCR-5", matched_brand=BRAND, passage_index=0),
                ResearchHypothesisCandidate(model="PC200", matched_brand="Komatsu", passage_index=0),
                ResearchHypothesisCandidate(model="DX225", matched_brand=BRAND, passage_index=0),
            ]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        research, _ = research_machine(client, "gpt-4.1-mini", visual_result(),
                                       allowed_categories=[CATEGORY])
        self.assertEqual([(item["model"], item["confidence"]) for item in research["hypotheses"]],
                         [("DX140LCR-5", "lead")])
        self.assertEqual(research["fields"], [])

    def test_candidate_parse_input_contains_only_public_visual_signal(self):
        client = Mock()
        client.responses.create.return_value = search_response([
            (URL_A, "DEVELON DX140LCR-5", "DEVELON DX140LCR-5 crawler excavator."),
        ])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed", output_parsed=ResearchHypothesisCandidates(hypotheses=[]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        result = visual_result()
        result["data"]["notes"] = "PRIVATE OWNER NOTE"
        result["data"]["serial"] = "PRIVATESERIAL"
        result["visual_description"] = "Excavadora de orugas naranja. PRIVATESERIAL está impreso."
        research_machine(client, "gpt-4.1-mini", result, allowed_categories=[CATEGORY])
        payload = json.loads(client.responses.parse.call_args.kwargs["input"])
        self.assertNotIn("PRIVATE OWNER NOTE", client.responses.parse.call_args.kwargs["input"])
        self.assertNotIn("PRIVATESERIAL", client.responses.create.call_args.kwargs["input"])
        self.assertEqual(payload["identity"]["brand"], BRAND)
        self.assertEqual(payload["cited_passages"][0]["source_url"], URL_A)

    def test_accepted_partial_image_label_limits_candidates_without_becoming_identity(self):
        client = Mock()
        url = "https://www.cat.com/en_US/products/new/equipment/excavators.html"
        client.responses.create.return_value = search_response([
            (url, "CAT excavators", "CAT 320D hydraulic excavator."),
            (url, "CAT excavators", "CAT 320DL hydraulic excavator."),
            (url, "CAT excavators", "CAT 323 hydraulic excavator."),
        ])
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed=ResearchHypothesisCandidates(hypotheses=[
                ResearchHypothesisCandidate(model="320D", matched_brand="CAT", passage_index=0),
                ResearchHypothesisCandidate(model="320DL", matched_brand="CAT", passage_index=1),
                ResearchHypothesisCandidate(model="323", matched_brand="CAT", passage_index=2),
            ]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )
        result = partial_visual_model_result()
        research, _ = research_machine(client, "gpt-5.6-luna", result, allowed_categories=["Excavadoras"])
        search_payload = json.loads(client.responses.create.call_args.kwargs["input"])

        self.assertEqual(research["identity"]["model"], None)
        self.assertEqual(research["fields"], [])
        self.assertEqual([item["model"] for item in research["hypotheses"]], ["320D", "320DL"])
        self.assertEqual(search_payload["candidate_model_prefix"], "320D")
        self.assertIn('"320D"', search_payload["query"])
        self.assertEqual(research["discovery_hint"], {
            "key": "model", "value": "320D", "asset_id": "image_001", "source": "image",
            "review": "needs_review", "evidence": 'Rótulo lateral: "320D"; posible sufijo pequeño.',
        })
        self.assertTrue(is_validated_general_context({"research": research}))
        merged = merge_research(result, research)
        self.assertEqual(merged["data"]["model"], "320D")
        self.assertEqual(merged["provenance"]["model"]["review"], "needs_review")

    def test_partial_model_hint_rejects_unaccepted_plate_or_component_readings(self):
        cases = (
            partial_visual_model_result(asset_id="image_002"),
            partial_visual_model_result(source="plate"),
            partial_visual_model_result(component="engine"),
            partial_visual_model_result(kind="plate"),
            partial_visual_model_result(evidence="Rótulo lateral poco legible."),
            {**partial_visual_model_result(), "fields": [
                *partial_visual_model_result()["fields"],
                {**partial_visual_model_result()["fields"][0], "value": "330D", "evidence": "Rótulo: 330D"},
            ]},
        )
        for result in cases:
            with self.subTest(result=result["fields"]):
                self.assertIsNone(_accepted_visual_model_hint(result))

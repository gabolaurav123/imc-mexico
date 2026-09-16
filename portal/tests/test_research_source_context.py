"""Only real titles of the same cited source can supply model context."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from portal.research import (ResearchCandidate, ResearchCandidates, is_validated_web_field,
                             merge_research, normalize_candidates, research_machine, response_sources)

URL = "https://www.cat.com/equipment/example"
IDENTITY = {"serial": None, "brand": "Caterpillar", "model": "420F2"}
TITLE = "Caterpillar 420F2 Specifications"
BODY = "Potencia neta: 70 kW."


def candidate(**overrides):
    item = dict(key="power", value="70 kW", scope="model", passage_index=0,
                matched_serial=None, matched_brand="Caterpillar", matched_model="420F2")
    item.update(overrides)
    return ResearchCandidate(**item)


def normalize(body=BODY, title=TITLE, item=None, identity=None, context=True, sources=None):
    identity = identity or IDENTITY
    return normalize_candidates(ResearchCandidates(fields=[item or candidate()]), identity,
        "exact_serial" if identity.get("serial") else "model", sources or [{"url": URL, "title": title}],
        body, [{"source_url": URL, "text": body}], {URL: title} if context else None)


def provider_response(body=BODY, title=TITLE):
    text = body + f" [Fuente]({URL})"
    return SimpleNamespace(status="completed", output_text=text,
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        output=[{"type": "web_search_call", "action": {"sources": [{"url": URL}]}},
                {"type": "message", "content": [{"text": text, "annotations": [{"type": "url_citation",
                    "url": URL, "title": title, "start_index": len(body) + 1, "end_index": len(text)}]}]}])


class SourceTitleContextTests(SimpleTestCase):
    def test_real_same_source_title_supplies_model_context_and_labeled_evidence(self):
        result = normalize()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["match"], "model")
        field = result["fields"][0]
        self.assertEqual(field["scope"], "model")
        self.assertEqual(field["value"], "70 kW")
        self.assertEqual(field["evidence"], f"Título de la fuente citada: {TITLE}\nFragmento citado: {BODY}")
        self.assertLessEqual(len(field["evidence"]), 800)
        self.assertEqual(result["diagnostics"]["candidate_source_title_context_count"], 1)
        merged = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, result)
        self.assertTrue(is_validated_web_field(merged, "power", "70 kW", merged["provenance"]["power"]))

    def test_title_from_query_or_other_source_is_not_context(self):
        self.assertEqual(normalize(context=False)["fields"], [])
        self.assertEqual(normalize(sources=[{"url": URL, "title": "Generic technical source"}])["fields"], [])
        fields = normalize_candidates(ResearchCandidates(fields=[candidate()]), IDENTITY, "model",
            [{"url": URL, "title": "Generic source"}, {"url": "https://other.example.com/model", "title": TITLE}], BODY,
            [{"source_url": URL, "text": BODY}], {"https://other.example.com/model": TITLE})["fields"]
        self.assertEqual(fields, [])

    def test_ambiguous_title_or_conflicting_brand_model_in_body_are_rejected(self):
        for title in ("Caterpillar 420F2 / 430F2 comparison", "Caterpillar 420F2IT Specifications", "Komatsu 420F2 Specs"):
            with self.subTest(title=title):
                self.assertEqual(normalize(title=title)["fields"], [])
        for body in ("Komatsu: potencia neta 70 kW.", "Modelo 430F2: potencia neta 70 kW.",
                     "Caterpillar 430F2: potencia neta 70 kW.", "Caterpillar 320: potencia neta 70 kW.",
                     "CAT 320: potencia neta 70 kW."):
            with self.subTest(body=body):
                self.assertEqual(normalize(body=body)["fields"], [])

    def test_value_serial_and_year_cannot_be_taken_from_title(self):
        self.assertEqual(normalize(body="Ficha técnica sin potencia publicada.", title=TITLE + " 70 kW")["fields"], [])
        identity = {**IDENTITY, "serial": "UNIT123"}
        result = normalize(title=TITLE + " UNIT123", item=candidate(scope="exact_serial", matched_serial="UNIT123"), identity=identity)
        self.assertNotEqual(result["match"], "exact_serial")
        year = normalize(body="Año: 2018.", title=TITLE, item=candidate(key="year", value="2018", scope="exact_serial", matched_serial="UNIT123"), identity=identity)
        self.assertEqual(year["fields"], [])

    def test_only_retrieved_and_cited_title_is_exposed_as_identity_context(self):
        context = {}
        response_sources(provider_response(), context_titles=context)
        self.assertEqual(context, {URL: TITLE})
        response = provider_response()
        response.output[0]["action"]["sources"] = []
        context = {}
        response_sources(response, context_titles=context)
        self.assertEqual(context, {})
        response = provider_response(title="")
        context = {}
        response_sources(response, context_titles=context)
        self.assertEqual(context, {})

    def test_pipeline_passes_real_identity_context_and_fills_from_original_body(self):
        client = Mock()
        client.responses.create.return_value = provider_response()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=ResearchCandidates(fields=[candidate()]),
                                                              usage=SimpleNamespace(input_tokens=60, output_tokens=30))
        vision = {"data": {"brand": "Caterpillar", "model": "420F2"}, "provenance": {
            key: {"source": "image", "review": "clear", "component": "machine"} for key in ("brand", "model")}, "plates": []}
        result, _ = research_machine(client, "gpt-4.1-mini", vision)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["fields"][0]["value"], "70 kW")
        request = json.loads(client.responses.parse.call_args.kwargs["input"])
        self.assertEqual(request["cited_passages"][0]["text"], BODY)
        self.assertEqual(request["cited_passages"][0]["identity_context"], {"origin": "same_source_title", "title": TITLE})

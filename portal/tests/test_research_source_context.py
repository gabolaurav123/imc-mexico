"""Only real titles of the same cited source can supply model context."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from portal.research import (ResearchCandidate, ResearchCandidates, _contains_identifier,
                             is_validated_web_field, merge_research, normalize_candidates,
                             research_machine, response_sources)

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
        output=[{"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": [{"url": URL}]}},
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

    def test_letter_suffix_variant_in_real_title_cannot_supply_base_model_context(self):
        for suffix in (" IT", " it", "-IT", "IT", " LC", " LGP"):
            with self.subTest(suffix=suffix):
                result = normalize(title="Caterpillar 420F2" + suffix + " Specifications")
                self.assertEqual(result["fields"], [])
                self.assertEqual(result["sources"], [])

    def test_variant_in_cited_body_cannot_borrow_a_base_model_title_or_match_label(self):
        for body in ("Caterpillar 420F2 IT: potencia 70 kW.",
                     "Caterpillar 420F2-IT: potencia 70 kW.",
                     "La potencia del 420F2IT es 70 kW.",
                     "Modelo 420F2 IT: potencia 70 kW.",
                     "Caterpillar 420F2 / 430F2: potencia 70 kW."):
            with self.subTest(body=body):
                result = normalize(body=body)
                self.assertEqual(result["fields"], [])
                self.assertEqual(result["sources"], [])
        exact = normalize(body="Caterpillar 420F2 IT, serie UNIT123: potencia 70 kW.",
                          item=candidate(scope="exact_serial", matched_serial="UNIT123", matched_model=None),
                          identity={**IDENTITY, "serial": "UNIT123"})
        self.assertEqual(exact["fields"], [])
        for suffix in ("it", "lc", "lgp"):
            with self.subTest(lowercase_suffix=suffix):
                result = normalize(body=f"Caterpillar 420F2 {suffix} tiene potencia 70 kW.")
                self.assertEqual(result["fields"], [])
                self.assertEqual(result["diagnostics"]["field_rejection_counts"],
                                 {"power": {"model_variant_suffix": 1}})

    def test_decimal_model_requires_its_complete_literal_identifier(self):
        identity = {**IDENTITY, "model": "307.5"}
        item = candidate(value="36 kW", matched_model="307.5")
        title = "Caterpillar 307.5 Specifications"
        accepted = normalize(body="Caterpillar 307.5: potencia neta 36 kW.", title=title,
                             item=item, identity=identity)
        self.assertEqual(accepted["fields"][0]["value"], "36 kW")
        for evidence in ("Caterpillar 307: potencia neta 36 kW.",
                         "Caterpillar 307.50: potencia neta 36 kW.",
                         "Caterpillar 307.5D: potencia neta 36 kW.",
                         "Caterpillar 308: potencia neta 36 kW."):
            with self.subTest(evidence=evidence):
                self.assertFalse(_contains_identifier(evidence, "307.5"))
                result = normalize(body=evidence, title=title, item=item, identity=identity)
                self.assertEqual(result["fields"], [])

    def test_shared_model_document_requires_explicit_base_model_in_its_own_passage(self):
        for title in ("CAT 420F2/420F2 IT", "Caterpillar 420F2 and 420F2 IT", "CAT 420F2/IT"):
            with self.subTest(title=title):
                self.assertEqual(normalize(title=title)["fields"], [])
                explicit = normalize(title=title, body="Caterpillar 420F2: potencia neta 70 kW.")
                self.assertEqual(explicit["fields"][0]["value"], "70 kW")
                self.assertNotIn("Título de la fuente", explicit["fields"][0]["evidence"])

    def test_actual_full_variant_identity_still_matches_itself(self):
        identity = {**IDENTITY, "model": "420F2 IT"}
        for body in (BODY, "Caterpillar 420F2 IT: potencia neta 70 kW."):
            with self.subTest(body=body):
                result = normalize(body=body, title="Caterpillar 420F2 IT Backhoe Loader Specifications",
                                   identity=identity, item=candidate(matched_model="420F2 IT"))
                self.assertEqual(result["fields"][0]["value"], "70 kW")

    def test_parenthetical_generation_is_a_complete_model_identifier(self):
        identity = {"serial": None, "brand": "Volvo", "model": "ECR58 (first generation)"}
        item = ResearchCandidate(key="power", value="38,2 kW", scope="model", passage_index=0,
                                 matched_serial=None, matched_brand="Volvo", matched_model="ECR58 (first generation)")
        exact = normalize(body="Volvo ECR58 (first generation): potencia 38,2 kW.",
                          title="Volvo ECR58 first generation archive", identity=identity, item=item)
        self.assertEqual(exact["fields"][0]["value"], "38,2 kW")
        other = normalize(body="Volvo ECR58 (second generation): potencia 38,2 kW.",
                          title="Volvo ECR58 archive", identity=identity, item=item)
        self.assertEqual(other["fields"], [])

    def test_engine_code_units_and_document_format_do_not_become_model_variants(self):
        for body, title in (("Caterpillar 420F2: motor C4.4, potencia 70 kW.", TITLE),
                            ("Caterpillar 420F2 has power 70 kW.", TITLE),
                            (BODY, "Caterpillar 420F2 PDF Specifications")):
            with self.subTest(body=body, title=title):
                self.assertEqual(normalize(body=body, title=title)["fields"][0]["value"], "70 kW")

    def test_labeled_engine_manufacturer_and_model_are_not_the_machine_model(self):
        for label in ("Motor", "Engine"):
            with self.subTest(label=label):
                result = normalize(body=f"{label}: Caterpillar C4.4 ACERT DIT.",
                                   title="Caterpillar 420F2 IT Backhoe Loader Specifications",
                                   identity={**IDENTITY, "model": "420F2 IT"},
                                   item=candidate(key="engine", value="Caterpillar C4.4 ACERT DIT",
                                                  matched_model="420F2 IT"))
                self.assertEqual(result["fields"][0]["key"], "engine")
                self.assertEqual(result["fields"][0]["scope"], "model")

    def test_retained_engine_display_copy_does_not_become_another_machine_model(self):
        identity = {"serial": None, "brand": "Volvo", "model": "L110E"}
        body = "Volvo L110E: Engine: Volvo D7D LB E2. Valor métrico conservado: Volvo D7D LB E2."
        item = ResearchCandidate(key="engine", value="Volvo D7D LB E2", scope="model", passage_index=0,
                                 matched_serial=None, matched_brand="Volvo", matched_model="L110E")
        result = normalize(body=body, title="Volvo L110E product archive", identity=identity, item=item)
        self.assertEqual([(field["key"], field["value"]) for field in result["fields"]],
                         [("engine", "Volvo D7D LB E2")])

    def test_hyphenated_serial_after_model_is_not_truncated_into_a_variant_suffix(self):
        result = normalize(body="Caterpillar 420F2 CAT-SN1234: potencia 70 kW.",
                           identity={**IDENTITY, "serial": "CAT-SN1234"},
                           item=candidate(scope="exact_serial", matched_serial="CAT-SN1234"))
        self.assertEqual(result["fields"][0]["value"], "70 kW")
        self.assertEqual(result["fields"][0]["scope"], "exact_serial")

    def test_natural_model_and_component_phrases_do_not_create_machine_conflicts(self):
        phrases = ("El modelo Caterpillar 420F2 IT tiene una potencia de 70 kW.",
                   "Caterpillar 420F2 IT usa un motor con potencia 70 kW.",
                   "Caterpillar 420F2 IT: motor diésel Caterpillar C4.4 ACERT DIT, potencia 70 kW.",
                   "Caterpillar 420F2 IT: modelo de motor C4.4 ACERT DIT, potencia 70 kW.",
                   "El modelo CAT 420F2 IT tiene una potencia de 70 kW.",
                   "Caterpillar 420F2 IT se equipa con un motor de potencia 70 kW.",
                   "Caterpillar 420F2 IT que incorpora un motor de potencia 70 kW.",
                   "Caterpillar 420F2 IT una potencia de 70 kW.",
                   "Caterpillar 420F2 IT sus datos indican potencia 70 kW.",
                   "La Caterpillar 420F2 IT es una máquina. Este modelo tiene potencia 70 kW.")
        for body in phrases:
            with self.subTest(body=body):
                result = normalize(body=body, title="Caterpillar 420F2 IT Backhoe Loader Specifications",
                                   identity={**IDENTITY, "model": "420F2 IT"},
                                   item=candidate(matched_model="420F2 IT"))
                self.assertEqual(result["fields"][0]["value"], "70 kW")
        engine = normalize(body="Modelo de motor C4.4 ACERT DIT.",
                           title="Caterpillar 420F2 IT Backhoe Loader Specifications",
                           identity={**IDENTITY, "model": "420F2 IT"},
                           item=candidate(key="engine", value="C4.4 ACERT DIT", matched_model="420F2 IT"))
        self.assertEqual(engine["fields"][0]["key"], "engine")
        title_prose = normalize(body="Potencia 70 kW.", title="Caterpillar 420F2 IT usa motor diésel",
                                identity={**IDENTITY, "model": "420F2 IT"},
                                item=candidate(matched_model="420F2 IT"))
        self.assertEqual(title_prose["fields"][0]["value"], "70 kW")

    def test_diagnostics_explain_fixed_field_causes_without_copying_private_text(self):
        cases = (("Caterpillar 420F2 IT: potencia 70 kW.", "model_variant_suffix"),
                 ("Caterpillar 420F2/430F2: potencia 70 kW.", "model_comparison"),
                 ("El modelo Caterpillar 430F2 tiene potencia 70 kW.", "explicit_model_mismatch"))
        for body, reason in cases:
            with self.subTest(reason=reason):
                result = normalize(body=body)
                self.assertEqual(result["fields"], [])
                self.assertEqual(result["diagnostics"]["field_rejection_counts"], {"power": {reason: 1}})
                diagnostic_text = json.dumps(result["diagnostics"])
                for forbidden in (body, "70 kW", "Caterpillar", "420F2", URL):
                    self.assertNotIn(forbidden, diagnostic_text)
        mismatch = normalize(body="Caterpillar 420F2: potencia 70 kW.",
                             item=candidate(matched_model="430F2"))
        self.assertEqual(mismatch["diagnostics"]["field_rejection_counts"], {"power": {"candidate_model_mismatch": 1}})

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

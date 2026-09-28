from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase

from django.core import signing

from portal.research import (SIGNING_SALT, ResearchExtraction, ResearchField, _manifest,
                             is_validated_web_field, normalize_research)


URL = "https://www.bomag.com/test-only-model-document"


def normalize(evidence, *, brand="BOMAG", model="1D-40", key="model", value=None):
    identity = {"serial": None, "brand": brand, "model": model}
    field = ResearchField(key=key, value=model if value is None else value, scope="model", source_url=URL,
                          evidence=evidence, matched_serial=None, matched_brand=brand, matched_model=model)
    return normalize_research(ResearchExtraction(fields=[field]), identity, "model",
                              [{"url": URL, "title": evidence}], evidence, citations={URL: [evidence]})


def validate(research, field):
    return is_validated_web_field({"research": research}, field["key"], field["value"],
                                  {**field, "source": "web", "review": "needs_review"})


class ResearchModelIdentityContextTests(SimpleTestCase):
    def test_tail_of_compound_model_does_not_establish_identity(self):
        for evidence in ("BOMAG COMPECTOR BW2 1D-40", "BOMAG compactor BW2 1D40: potencia 70 kW."):
            with self.subTest(evidence=evidence):
                research = normalize(evidence)
                self.assertEqual(research["fields"], [])
                self.assertEqual(research["diagnostics"]["field_rejection_counts"]["model"],
                                 {"model_fragment_prefix": 1})

    def test_component_code_of_another_maker_does_not_establish_machine_model(self):
        for evidence in ("BOMAG compactor powered by Hatz 1D40 engine.",
                         "BOMAG compactor powered by Hatz 1D40 engine producing 10 kW.",
                         "BOMAG compactor powered by Hatz 1D40 engine with 10 kW.",
                         "BOMAG compactor powered by Hatz 1D40 engine producing 10kW.",
                         "BOMAG engine Hatz 1D40.", "BOMAG motor: Hatz 1D-40.",
                         "ACME transmission ZF 4WG200."):
            with self.subTest(evidence=evidence):
                research = normalize(evidence, brand="ACME" if "ACME" in evidence else "BOMAG",
                                     model="4WG200" if "ACME" in evidence else "1D-40")
                self.assertEqual(research["fields"], [])
                self.assertEqual(research["diagnostics"]["field_rejection_counts"]["model"],
                                 {"component_model_identity": 1})

    def test_unambiguous_literal_model_remains_valid(self):
        for evidence in ("BOMAG 1D-40: potencia 70 kW.", "BOMAG compactor 1D40: potencia 70 kW.",
                         "BOMAG compactor de 70kW 1D40.", "BOMAG compactor 2014 1D40."):
            with self.subTest(evidence=evidence):
                research = normalize(evidence)
                self.assertEqual(len(research["fields"]), 1)
                self.assertTrue(validate(research, research["fields"][0]))

    def test_full_compound_identifier_is_not_rejected_as_its_own_fragment(self):
        research = normalize("BOMAG COMPECTOR BW2 1D-40", model="BW2 1D-40")
        self.assertEqual(len(research["fields"]), 1)
        self.assertTrue(validate(research, research["fields"][0]))

    def test_component_manufacturer_can_identify_its_own_equipment(self):
        for evidence in ("Hatz 1D40 engine.", "Hatz engine model 1D40.", "Motor: Hatz 1D40.",
                         "ZF transmission 4WG200."):
            with self.subTest(evidence=evidence):
                research = normalize(evidence, brand="ZF" if "ZF" in evidence else "Hatz",
                                     model="4WG200" if "ZF" in evidence else "1D40")
                self.assertEqual(len(research["fields"]), 1)
                self.assertTrue(validate(research, research["fields"][0]))

    def test_engine_specification_of_identified_machine_remains_valid(self):
        for evidence in ("BOMAG BW62H: engine Hatz 1D40.", "BOMAG compactor BW62H engine Hatz 1D40."):
            with self.subTest(evidence=evidence):
                research = normalize(evidence, model="BW62H", key="engine", value="Hatz 1D40")
                self.assertEqual(len(research["fields"]), 1)
                self.assertTrue(validate(research, research["fields"][0]))

    def test_machine_identity_with_category_and_separate_engine_detail_remains_valid(self):
        for evidence in ("BOMAG compactador 1D40 motor Hatz 1D40: potencia 70 kW.",
                         "Engine: Hatz diesel, BOMAG compactor 1D40: potencia 70 kW."):
            with self.subTest(evidence=evidence):
                research = normalize(evidence)
                self.assertEqual(len(research["fields"]), 1)
                self.assertTrue(validate(research, research["fields"][0]))

    def test_matching_machine_heading_is_not_invalidated_by_same_component_code(self):
        research = normalize("BOMAG 1D40: engine Hatz 1D40.")
        self.assertEqual(len(research["fields"]), 1)
        self.assertTrue(validate(research, research["fields"][0]))

    def test_old_signed_invalid_evidence_is_rechecked_without_rewriting_history(self):
        for evidence in ("BOMAG COMPECTOR BW2 1D-40", "BOMAG compactor powered by Hatz 1D40 engine."):
            with self.subTest(evidence=evidence):
                # Simulate the preceding normalizer, which signed these exact
                # passages before occurrence context was checked.
                with patch("portal.research._ambiguous_model_occurrence_reason", return_value=""):
                    research = normalize(evidence)
                    self.assertEqual(len(research["fields"]), 1)
                    self.assertTrue(validate(research, research["fields"][0]))
                original = deepcopy(research)
                self.assertFalse(validate(research, research["fields"][0]))
                self.assertEqual(research, original)

    def test_guard_does_not_depend_on_component_or_machine_brand_allowlist(self):
        research = normalize("MakerOne compactor powered by MakerTwo X123 engine.",
                             brand="MakerOne", model="X123")
        self.assertEqual(research["fields"], [])
        research = normalize("MakerTwo X123 engine.", brand="MakerTwo", model="X123")
        self.assertEqual(len(research["fields"]), 1)
        self.assertTrue(validate(research, research["fields"][0]))

    def test_an_invalid_old_field_does_not_invalidate_other_signed_references(self):
        with patch("portal.research._ambiguous_model_occurrence_reason", return_value=""):
            research = normalize("BOMAG COMPECTOR BW2 1D-40")
        valid = normalize("BOMAG 1D-40: potencia 70 kW.", key="power", value="70 kW")["fields"][0]
        research["fields"].append(valid)
        research["proof"] = signing.Signer(salt=SIGNING_SALT).sign_object(_manifest(research), compress=True)
        original = deepcopy(research)
        self.assertFalse(validate(research, research["fields"][0]))
        self.assertTrue(validate(research, valid))
        self.assertEqual(research, original)

    def test_brand_with_digits_is_not_misread_as_a_compound_model_prefix(self):
        research = normalize("Maker2 X123: potencia 70 kW.", brand="Maker2", model="X123")
        self.assertEqual(len(research["fields"]), 1)
        self.assertTrue(validate(research, research["fields"][0]))

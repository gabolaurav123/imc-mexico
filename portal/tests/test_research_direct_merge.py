"""Literal document rows and model candidates share one validation/signature."""
from django.test import SimpleTestCase

from portal.research import (
    ResearchCandidate, ResearchCandidates, ResearchField, is_validated_web_field,
    normalize_candidates, normalize_direct_fields,
)


URL = "https://www.cat.com/model-420f2-it"
OTHER_URL = "https://www.lectura-specs.com/model-420f2-it"
TITLE = "Caterpillar 420F2 IT Specifications"
IDENTITY = {"brand": "Caterpillar", "model": "420F2 IT", "serial": None}


def candidate(index=0, **changes):
    values = dict(key="power", value="70 kW", scope="model", passage_index=index,
                  matched_brand="Caterpillar", matched_model="420F2 IT", matched_serial=None)
    return ResearchCandidate(**{**values, **changes})


def direct(evidence="Engine power: 70 kW.", **changes):
    values = dict(key="power", value="70 kW", scope="model", source_url=URL, evidence=evidence,
                  matched_brand="Caterpillar", matched_model="420F2 IT", matched_serial=None)
    return ResearchField(**{**values, **changes})


def normalize(model_fields=(), direct_fields=(), rows=None, identity=None, titles=None, fallback=False):
    rows = rows if rows is not None else [(URL, "Engine power: 70 kW.")]
    titles = titles if titles is not None else {url: TITLE for url, _ in rows}
    sources = [{"url": url, "title": title} for url, title in titles.items()]
    passages = [{"source_url": url, "text": text} for url, text in rows]
    args = (identity or IDENTITY, "model", sources, "\n\n".join(text for _, text in rows), passages, titles)
    if fallback:
        return normalize_direct_fields(*args, direct_fields=direct_fields)
    return normalize_candidates(ResearchCandidates(fields=list(model_fields)), *args, direct_fields=direct_fields)


class DirectResearchMergeTests(SimpleTestCase):
    def assert_signed(self, result):
        for field in result["fields"]:
            meta = {key: field[key] for key in ("scope", "source_url", "source_title", "source_date", "evidence")}
            meta.update(source="web", review="needs_review")
            self.assertTrue(is_validated_web_field({"research": result}, field["key"], field["value"], meta))

    def test_model_and_direct_rows_share_one_signed_manifest(self):
        result = normalize([candidate()], [direct("Weight: 8.2 t.", key="weight", value="8.2 t")],
                           [(URL, "Engine power: 70 kW."), (URL, "Weight: 8.2 t.")])
        self.assertEqual({field["key"] for field in result["fields"]}, {"power", "weight"})
        self.assertEqual(result["diagnostics"]["normalized_candidate_count"], 2)
        self.assert_signed(result)

    def test_different_values_are_removed_even_when_one_is_direct(self):
        rows = [(URL, "Engine power: 70 kW."), (OTHER_URL, "Engine power: 99 kW."), (URL, "Weight: 8.2 t.")]
        result = normalize([candidate()], [direct(rows[1][1], value="99 kW", source_url=OTHER_URL),
                                          direct(rows[2][1], key="weight", value="8.2 t")], rows)
        self.assertEqual([field["key"] for field in result["fields"]], ["weight"])
        self.assertEqual(result["diagnostics"]["rejection_counts"]["conflicting_values"], 1)
        self.assert_signed(result)

    def test_forty_model_candidates_do_not_starve_direct_conflicts_or_fields(self):
        rows = [(URL, "Engine power: 70 kW."), (URL, "Engine power: 99 kW."), (URL, "Weight: 8.2 t.")]
        result = normalize([candidate()] * 40, [direct(rows[1][1], value="99 kW"),
                                               direct(rows[2][1], key="weight", value="8.2 t")], rows)
        self.assertEqual([field["key"] for field in result["fields"]], ["weight"])
        self.assertEqual(result["diagnostics"]["normalized_candidate_count"], 42)

    def test_direct_rows_still_need_retrieved_source_literal_evidence_and_real_title(self):
        for field in (direct(source_url=OTHER_URL), direct(value="999 kW"), direct(evidence="Fabricated evidence 70 kW.")):
            with self.subTest(field=field):
                self.assertEqual(normalize(direct_fields=[field])["fields"], [])
        self.assertEqual(normalize(direct_fields=[direct()], titles={URL: "Generic document"})["fields"], [])

    def test_direct_scope_cannot_promote_model_data_to_an_exact_unit_or_year(self):
        result = normalize(direct_fields=[direct(scope="exact_serial", matched_serial="UNIT123")])
        self.assertEqual(result["fields"], [])
        self.assertEqual(result["diagnostics"]["rejection_counts"], {"direct_scope_not_allowed": 1})
        result = normalize(direct_fields=[direct("Year: 2020.", key="year", value="2020")], rows=[(URL, "Year: 2020.")])
        self.assertEqual(result["fields"], [])

    def test_no_provider_fallback_uses_original_identity_and_rejects_missing_model(self):
        result = normalize(direct_fields=[direct()], fallback=True)
        self.assertEqual(result["fields"][0]["value"], "70 kW")
        self.assertEqual(result["diagnostics"]["llm_candidate_count"], 0)
        self.assert_signed(result)
        result = normalize(direct_fields=[direct()], identity={**IDENTITY, "model": None}, fallback=True)
        self.assertEqual(result["fields"], [])

    def test_combined_dimensions_preserve_literal_labels_and_units(self):
        text = "Transport length: 7.17 m; Transport width: 2.32 m; Transport height: 3.58 m"
        result = normalize(direct_fields=[direct(text, key="dimensions", value=text)], rows=[(URL, text)])
        self.assertEqual(result["fields"][0]["value"], text)
        self.assert_signed(result)
        result = normalize(direct_fields=[direct(text, key="dimensions", value="7.17 x 2.32 x 3.58 m")], rows=[(URL, text)])
        self.assertEqual(result["fields"], [])

    def test_same_validated_row_keeps_direct_label_without_false_conflict(self):
        text = "Operating Weight-Maximum: 11000 kg"
        result = normalize([candidate(key="weight", value="11000 kg")],
                           [direct(text, key="weight", value=text)], [(URL, text)])
        self.assertEqual(result["fields"][0]["value"], text)
        self.assertEqual(result["diagnostics"]["equivalent_direct_readings"], 1)
        self.assert_signed(result)

    def test_direct_label_equivalence_never_crosses_sources_rows_or_numeric_boundaries(self):
        cases = [
            ([(URL, "Operating Weight-Maximum: 11000 kg"), (OTHER_URL, "Operating Weight-Maximum: 11000 kg")], "11000 kg", OTHER_URL),
            ([(URL, "Operating Weight: 11000 kg"), (URL, "Operating Weight-Maximum: 11000 kg")], "11000 kg", URL),
            ([(URL, "Minimum: 70 kg; Maximum: 170 kg"), (URL, "Minimum: 70 kg; Maximum: 170 kg")], "70 kg", URL),
            ([(URL, "Minimum: 7; Maximum: 7.17"), (URL, "Minimum: 7; Maximum: 7.17")], "7", URL),
        ]
        for rows, value, direct_url in cases:
            direct_value = {"70 kg": "Maximum: 170 kg", "7": "Maximum: 7.17"}.get(value, rows[1][1])
            with self.subTest(rows=rows):
                result = normalize([candidate(key="weight", value=value)],
                                   [direct(rows[1][1], key="weight", value=direct_value, source_url=direct_url)], rows)
                self.assertEqual(result["fields"], [])
                self.assertEqual(result["diagnostics"]["rejection_counts"]["conflicting_values"], 1)

    def test_equivalent_direct_row_does_not_erase_an_existing_source_conflict(self):
        text = "Operating Weight-Maximum: 11000 kg"
        rows = [(URL, text), (OTHER_URL, "Weight: 12000 kg")]
        result = normalize([candidate(key="weight", value="11000 kg"), candidate(1, key="weight", value="12000 kg")],
                           [direct(text, key="weight", value=text)], rows)
        self.assertEqual(result["fields"], [])
        self.assertEqual(result["diagnostics"]["rejection_counts"]["conflicting_values"], 1)

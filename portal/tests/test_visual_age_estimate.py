"""Visual age is a broad, photo-bound proposal; it never becomes an exact year."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from pydantic import ValidationError as SchemaValidationError

from portal.processing import (AGE_ESTIMATE_LABELS, AgeEstimate, MachineAnalysis, SYSTEM_PROMPT,
    _bind_image_aliases, _merge_image_results, age_estimate_fields,
    enqueue_analysis, normalize_analysis, process_next_job)
from portal.tests import test_image_bindings as fixtures
from portal.tests.test_image_relevance import field, observation, parsed


BASIS = "Diseño angular de cabina con tablero de instrumentos analógicos."


def age(start=1995, end=2005, basis=BASIS):
    return dict(start_year=start, end_year=end, basis=basis)


def reading(asset="photo", *, estimate=None, kind="machine", relevance="machinery", fields=()):
    return parsed([observation(asset, relevance, kind, category="Montacargas",
        age_estimate=age() if estimate is None else estimate)], fields)


def normalize(response, ids=("photo",)):
    return normalize_analysis(response, list(ids), allowed_categories=["Montacargas"])


class VisualAgeNormalizationTests(SimpleTestCase):
    def test_prompt_distinguishes_exact_year_restrictions_from_optional_visual_estimate(self):
        # Reintroducing either blanket ban contradicts the later age_estimate
        # instructions; completed live analyses exposed this ambiguity by
        # retaining no estimate (the raw provider response was not stored).
        for ambiguous in ("dimensiones, año, horas", "combustible ni año a partir",
                          "combustible, año ni país"):
            self.assertNotIn(ambiguous, SYSTEM_PROMPT)
        self.assertIn("año exacto (year)", SYSTEM_PROMPT)
        self.assertIn("La restricción de year no impide", SYSTEM_PROMPT)
        self.assertIn("debe ser null cuando esos indicios sean insuficientes", SYSTEM_PROMPT)
        self.assertIn("No conviertas ese rango en year", SYSTEM_PROMPT)

    def test_strict_schema_requires_nullable_estimate_and_integer_bounds(self):
        from openai.lib._pydantic import to_strict_json_schema
        schema = to_strict_json_schema(MachineAnalysis)
        observation_schema = schema["$defs"]["ImageObservation"]
        self.assertIn("age_estimate", observation_schema["required"])
        self.assertIn({"type": "null"}, observation_schema["properties"]["age_estimate"]["anyOf"])
        estimate_schema = schema["$defs"]["AgeEstimate"]
        self.assertEqual(set(estimate_schema["required"]), {"start_year", "end_year", "basis"})
        self.assertEqual(estimate_schema["properties"]["start_year"]["type"], "integer")
        for invalid in (True, "1995", 1995.0):
            with self.subTest(invalid=invalid), self.assertRaises(SchemaValidationError):
                AgeEstimate(**age(start=invalid))

    def test_visual_range_is_integer_reviewable_and_never_exact_year(self):
        result = normalize(reading())
        self.assertEqual(result["data"]["estimated_year_from"], 1995)
        self.assertEqual(result["data"]["estimated_year_to"], 2005)
        self.assertIs(type(result["data"]["estimated_year_from"]), int)
        self.assertEqual(result["data"]["estimated_year_basis"], BASIS)
        self.assertNotIn("year", result["data"])
        derived = age_estimate_fields(result)
        self.assertEqual(set(derived), set(AGE_ESTIMATE_LABELS))
        for key, value in derived.items():
            self.assertEqual(value["value"], result["data"][key])
            self.assertEqual(value["source"], "visual_proposal")
            self.assertEqual(value["review"], "needs_review")
            self.assertEqual(value["component"], "machine")
            self.assertEqual(value["asset_id"], "photo")
            self.assertIn("pendiente de confirmar", value["evidence"])

    def test_ineligible_photo_or_relevance_cannot_estimate_age(self):
        for kind, relevance in (("plate", "related"), ("document", "related"),
                                ("other", "related"), ("machine", "unrelated"),
                                ("machine", "uncertain")):
            with self.subTest(kind=kind, relevance=relevance):
                result = normalize(reading(kind=kind, relevance=relevance))
                self.assertFalse(set(AGE_ESTIMATE_LABELS) & result["data"].keys())
                self.assertIsNone(result["image_observations"][0]["age_estimate"])
                self.assertEqual(age_estimate_fields(result), {})

    def test_invalid_bounds_and_narrow_ranges_are_rejected_without_clamping(self):
        current = timezone.localdate().year
        for start, end in ((1899, 1905), (2005, 1995), (2000, 2000), (2000, 2004),
                           (current - 5, current + 1)):
            with self.subTest(start=start, end=end):
                result = normalize(reading(estimate=age(start, end)))
                self.assertNotIn("estimated_year_from", result["data"])
                self.assertIsNone(result["image_observations"][0]["age_estimate"])
        for start, end in ((1900, 1905), (current - 5, current)):
            with self.subTest(valid=(start, end)):
                result = normalize(reading(estimate=age(start, end)))
                self.assertEqual((result["data"]["estimated_year_from"], result["data"]["estimated_year_to"]), (start, end))

    def test_wear_paint_or_rust_is_not_a_dating_basis(self):
        for basis in ("Diseño antiguo porque tiene pintura desgastada.",
                      "Cabina oxidada.", "Mandos desgastados.", "Repainted cab.", "Worn cab design.",
                      "Cabina oxidada y con suciedad.", "Rust and wear on the cab.",
                      "El equipo se ve usado.", "", "Diseño " + "a" * 401):
            with self.subTest(basis=basis):
                result = normalize(reading(estimate=age(basis=basis)))
                self.assertNotIn("estimated_year_from", result["data"])
        result = normalize(reading(estimate=age(basis=BASIS + " La pintura muestra desgaste.")))
        self.assertEqual(result["data"]["estimated_year_basis"], BASIS)

    def test_basis_filters_private_identifiers_dates_links_and_contacts(self):
        for unsafe in ("La cabina indica serie PRIVATESERIAL.", "Diseño propio de 1998.",
                       "Diseño descrito en https://example.com/.", "Diseño; escribe a test@example.invalid.",
                       "Cabina PRIVATESERIAL."):
            with self.subTest(unsafe=unsafe):
                result = normalize(reading(estimate=age(basis=BASIS + " " + unsafe),
                    fields=[field("serial", "PRIVATESERIAL", "photo", "plate")]))
                basis = result["data"]["estimated_year_basis"]
                self.assertIn(BASIS, basis)
                self.assertNotIn("PRIVATESERIAL", basis)
                self.assertNotIn("1998", basis)
                self.assertNotIn("https", basis)
                self.assertNotIn("@", basis)
                self.assertNotIn("PRIVATESERIAL", str(age_estimate_fields(result)))

    def test_provider_flat_estimate_and_legacy_observation_cannot_bypass_bound_evidence(self):
        forged = [field(key, "1995" if key != "estimated_year_basis" else BASIS, "photo")
                  for key in AGE_ESTIMATE_LABELS]
        response = parsed([observation("photo", age_estimate=None)], forged)
        result = normalize(response)
        self.assertFalse(set(AGE_ESTIMATE_LABELS) & result["data"].keys())
        legacy = parsed([dict(asset_id="photo", kind="machine", age_estimate=age())])
        result = normalize(legacy)
        self.assertEqual(result["relevance"]["status"], "unassessed")
        self.assertEqual(age_estimate_fields(result), {})

    def test_exact_readable_year_takes_precedence_but_visual_year_cannot_become_exact(self):
        for source in ("plate", "image"):
            with self.subTest(source=source):
                result = normalize(reading(fields=[field("year", "2001", "photo", source)]))
                self.assertEqual(result["data"]["year"], "2001")
                self.assertFalse(set(AGE_ESTIMATE_LABELS) & result["data"].keys())
                self.assertEqual(age_estimate_fields(result), {})
        result = normalize(reading(fields=[field("year", "2001", "photo", "visual_proposal")]))
        self.assertIsNone(result["data"]["year"])
        self.assertEqual(result["data"]["estimated_year_from"], 1995)
        result["data"]["year"] = 2001
        result["provenance"]["year"] = {"source": "user", "review": "confirmed"}
        self.assertEqual(age_estimate_fields(result), {})
        component_year = {**field("year", "2001", "photo", "plate"), "component": "engine"}
        result = normalize(reading(fields=[component_year]))
        self.assertNotIn("year", result["data"])
        self.assertEqual(result["data"]["estimated_year_from"], 1995)

    def test_photo_disagreement_expands_range_and_preserves_each_safe_basis(self):
        second_basis = "Configuración de mandos mecánicos y capó de líneas redondeadas."
        first = normalize(reading("a", estimate=age(1990, 2000)), ["a"])
        second = normalize(reading("b", estimate=age(2005, 2015, second_basis)), ["b"])
        unrelated = normalize(reading("c", relevance="unrelated", estimate=age(1900, 1905)), ["c"])
        for results, ids in (([first, second, unrelated], ["a", "b", "c"]),
                             ([unrelated, second, first], ["c", "b", "a"])):
            with self.subTest(order=ids):
                merged = _merge_image_results(results, ids, ["Montacargas"])
                self.assertEqual((merged["data"]["estimated_year_from"], merged["data"]["estimated_year_to"]), (1990, 2015))
                self.assertIn(BASIS, merged["data"]["estimated_year_basis"])
                self.assertIn(second_basis, merged["data"]["estimated_year_basis"])
                self.assertEqual(set(merged["age_estimate_support"]), {"a", "b"})
                self.assertNotIn("year", merged["data"])

    def test_server_alias_binding_reaches_age_provenance(self):
        response = reading("image_001")
        mapped = _bind_image_aliases(response, [{"alias": "image_001", "asset_id": fixtures.PLATE_ID}])
        result = normalize(mapped, [fixtures.PLATE_ID])
        self.assertEqual(result["provenance"]["estimated_year_from"]["asset_id"], fixtures.PLATE_ID)
        self.assertEqual(response.image_observations[0].asset_id, "image_001")


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class VisualAgeWorkerTests(TestCase):
    def setUp(self):
        fixtures.ImageMessageBindingTests.setUp(self)

    def test_isolated_photo_reads_merge_age_without_extra_calls_and_keep_actual_usage(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=False)
        responses = [SimpleNamespace(status="completed", output_parsed=reading("image_001", estimate=age(1990, 2000)),
                         usage=SimpleNamespace(input_tokens=400, output_tokens=200)),
                     SimpleNamespace(status="completed", output_parsed=reading("image_001", estimate=age(1995, 2005)),
                         usage=SimpleNamespace(input_tokens=450, output_tokens=220))]
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider:
            provider.return_value.responses.parse.side_effect = responses
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(provider.return_value.responses.parse.call_count, 2)
        self.assertEqual((job.input_tokens, job.output_tokens), (850, 420))
        self.assertEqual((job.result["data"]["estimated_year_from"], job.result["data"]["estimated_year_to"]), (1990, 2005))
        self.assertEqual(job.result["provenance"]["estimated_year_from"]["asset_id"], job.asset_ids[0])
        self.assertNotIn("year", job.result["data"])
        self.assertEqual(set(job.result["age_estimate_support"]), set(job.asset_ids))

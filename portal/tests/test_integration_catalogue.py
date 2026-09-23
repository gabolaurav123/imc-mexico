"""Pure contract tests for preflight catalogue resolution."""
from django.test import SimpleTestCase

from portal.integration_catalogue import resolve_catalogue


def row(type_id="T-01", type="Excavadoras", brand_id="B-01", brand="Caterpillar",
        model_id="M-007", model="307.5 L"):
    return {"type_id": type_id, "type": type, "brand_id": brand_id, "brand": brand,
            "model_id": model_id, "model": model}


class IntegrationCatalogueResolverTests(SimpleTestCase):
    def identity(self, **overrides):
        value = {"type": "Excavadoras", "brand": "Caterpillar", "model": "307.5 L"}
        value.update(overrides)
        return value

    def test_matches_one_exact_authorised_path_and_preserves_opaque_leading_zeroes(self):
        result = resolve_catalogue(self.identity(), [row(type_id="0007", brand_id="B-0002", model_id="000042")])
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["canonical_ids"], {"type_id": "0007", "brand_id": "B-0002", "model_id": "000042"})
        self.assertEqual(result["original_texts"]["model"], "307.5 L")

    def test_missing_does_not_create_or_guess_a_catalogue_item(self):
        result = resolve_catalogue(self.identity(model="308"), [row()])
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["canonical_ids"], {})
        self.assertEqual(result["field_errors"], {"model": "Modelo no encontrado."})

    def test_missing_is_reported_at_the_first_unmatched_hierarchy_level(self):
        self.assertEqual(resolve_catalogue(self.identity(type="Cargadores"), [row()])["field_errors"],
                         {"type": "Tipo de máquina no encontrado."})
        self.assertEqual(resolve_catalogue(self.identity(brand="Komatsu"), [row()])["field_errors"],
                         {"brand": "Marca no encontrada."})

    def test_colliding_authorised_rows_require_review(self):
        result = resolve_catalogue(self.identity(), [row(model_id="M-1"), row(model_id="M-2")])
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["canonical_ids"], {})
        self.assertEqual(result["candidate_ids"], ["M-1", "M-2"])
        self.assertEqual(result["field_errors"], {"model": "Modelo ambiguo; requiere revisión."})

    def test_duplicate_identical_adapter_rows_do_not_create_false_ambiguity(self):
        result = resolve_catalogue(self.identity(), [row(), row()])
        self.assertEqual(result["status"], "matched")

    def test_normalizes_accents_case_spaces_and_hyphens_only(self):
        result = resolve_catalogue(self.identity(type=" excavádoras ", brand="CATERPILLAR", model="307.5-L"), [row()])
        self.assertEqual(result["status"], "matched")
        self.assertEqual(resolve_catalogue(self.identity(model="3075 L"), [row()])["status"], "missing")
        self.assertEqual(resolve_catalogue(self.identity(model="307.5"), [row()])["status"], "missing")

    def test_only_explicit_aliases_are_applied(self):
        aliases = {"brand": {"CAT": "Caterpillar"}}
        self.assertEqual(resolve_catalogue(self.identity(brand="CAT"), [row()], aliases)["status"], "matched")
        self.assertEqual(resolve_catalogue(self.identity(brand="CAT"), [row()])["status"], "missing")

    def test_rejects_numeric_ids_and_malformed_labels(self):
        result = resolve_catalogue(self.identity(), [row(model_id=42)])
        self.assertEqual(result["status"], "missing")
        self.assertIn("rows", result["field_errors"])
        malformed = resolve_catalogue(self.identity(model="\n"), [row()])
        self.assertIn("model", malformed["field_errors"])

    def test_incompatible_parent_linkage_for_a_model_id_fails_closed(self):
        result = resolve_catalogue(self.identity(), [row(model_id="same"), row(model_id="same", brand="Komatsu")])
        self.assertEqual(result["status"], "missing")
        self.assertIn("rows", result["field_errors"])

    def test_model_id_cannot_move_to_different_parent_ids_with_same_labels(self):
        result = resolve_catalogue(self.identity(), [row(model_id="same"), row(type_id="T-02", brand_id="B-02", model_id="same")])
        self.assertEqual(result["status"], "missing")
        self.assertIn("padres incompatibles", result["field_errors"]["rows"])

    def test_type_and_brand_id_label_collisions_fail_closed(self):
        type_collision = resolve_catalogue(self.identity(), [row(), row(type="Cargadores")])
        self.assertIn("tipo", type_collision["field_errors"]["rows"])
        brand_collision = resolve_catalogue(self.identity(), [row(), row(brand="CAT")])
        self.assertIn("marca", brand_collision["field_errors"]["rows"])

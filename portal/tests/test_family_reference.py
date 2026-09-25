from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from portal.family_reference import (build_family_reference, family_identity_matches,
                                     is_family_member, is_validated_family_field,
                                     is_validated_family_reference, merge_family_reference)
from portal.models import Brand, Category, EquipmentModel, MarketReference, TechnicalReference


class FamilyReferenceTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        brand = Brand.objects.create(name="Caterpillar")
        self.base = EquipmentModel.objects.create(brand=brand, name="320D", category=self.category)
        self.long = EquipmentModel.objects.create(brand=brand, name="320D L", category=self.category)
        self.numeric_child = EquipmentModel.objects.create(brand=brand, name="320D2", category=self.category)

    def result(self):
        return {
            "category": "Excavadoras",
            "data": {"brand": "CAT", "model": None},
            "provenance": {
                "brand": {"source": "image", "review": "clear", "component": "machine", "asset_id": "image-1"},
                "model": {"source": "image", "review": "needs_review", "component": "machine", "asset_id": "image-1"},
            },
            "fields": [{"key": "model", "value": None, "source": "image", "review": "needs_review",
                        "component": "machine", "asset_id": "image-1",
                        "evidence": "El rótulo muestra «320D» y un sufijo no confirmable."}],
            "relevance": {"accepted_asset_ids": ["image-1"]},
            "image_observations": [{"asset_id": "image-1", "kind": "machine", "relevance": "machinery"}],
        }

    def technical(self, model, start, end, **changes):
        values = {"category": self.category, "equipment_model": model, "brand": "Caterpillar",
                  "model": model.name, "source": f"https://manufacturer.example.com/{model.name.replace(' ', '-').lower()}/{start}",
                  "source_title": f"{model.name} ficha", "retrieved_at": timezone.localdate(),
                  "period_from": start, "period_to": end,
                  "provenance": {"period_evidence": f"Caterpillar {model.name}: Years of manufacture {start}—{end}."},
                  "review": "approved", "active": True}
        values.update(changes)
        return TechnicalReference.objects.create(**values)

    def market(self, model, suffix, price, **changes):
        values = {"equipment_model": model, "source": f"https://market{suffix}.example.com/listing-{suffix}",
                  "source_title": f"Oferta {suffix}", "price": price, "currency": "USD", "market": "US",
                  "price_type": "asking", "condition": "used", "retrieved_at": timezone.localdate(),
                  "evidence": "Precio publicado, condición usada y mercado declarados.", "review": "approved", "active": True,
                  "unit_key": f"unit-{suffix}"}
        values.update(changes)
        return MarketReference.objects.create(**values)

    def test_family_rule_accepts_only_base_l_and_lc_not_numeric_successors(self):
        self.assertTrue(is_family_member("320D", "320D"))
        self.assertTrue(is_family_member("320D L", "320D"))
        self.assertTrue(is_family_member("320D-LC", "320D"))
        self.assertFalse(is_family_member("320D2", "320D"))
        self.assertFalse(is_family_member("320D LCR", "320D"))

    def test_builds_signed_family_range_without_promoting_exact_model_or_specs(self):
        self.technical(self.base, 2007, 2020)
        self.technical(self.long, 2006, 2014)
        self.technical(self.numeric_child, 2011, 2020)
        self.market(self.base, "one", "60000")
        self.market(self.long, "two", "75900")
        self.market(self.numeric_child, "three", "99999")

        family = build_family_reference(self.result(), category=self.category)

        self.assertTrue(is_validated_family_reference(family))
        self.assertEqual(family["identity"]["model_family"], "320D")
        self.assertEqual((family["fields"]["estimated_year_from"], family["fields"]["estimated_year_to"]), (2006, 2020))
        self.assertEqual((family["fields"]["estimate_min"], family["fields"]["estimate_max"]), ("60000.00", "75900.00"))
        self.assertIsNone(family.get("suggested_price"))
        self.assertNotIn("power", family["fields"])
        self.assertEqual({row["model"] for row in family["comparables"]}, {"320D", "320D L"})
        self.assertNotIn("320D2", {row["model"] for row in family["comparables"]})

    def test_incompatible_configuration_and_sale_type_do_not_make_a_range(self):
        self.technical(self.base, 2007, 2014)
        self.market(self.base, "one", "60000", configurations={"attachment": "thumb"})
        self.market(self.long, "two", "75900", configurations={})
        self.market(self.long, "three", "72000", price_type="sold", configurations={})

        family = build_family_reference(self.result(), category=self.category)

        self.assertTrue(is_validated_family_reference(family))
        self.assertNotIn("estimate_min", family["fields"])
        self.assertEqual(family["comparables"], [])

    def test_market_rows_must_be_current_active_and_independent(self):
        self.technical(self.base, 2007, 2014)
        self.market(self.base, "old", "60000", retrieved_at=timezone.localdate() - timedelta(days=31))
        self.market(self.long, "same-a", "70000", unit_key="shared")
        self.market(self.base, "same-b", "71000", unit_key=" shared ")
        family = build_family_reference(self.result(), category=self.category)

        self.assertNotIn("estimate_min", family["fields"])

    def test_apparent_used_condition_rejects_new_family_group(self):
        self.technical(self.base, 2007, 2014)
        self.market(self.base, "used-one", "60000")
        self.market(self.long, "used-two", "75900")
        self.market(self.base, "new-one", "120000", condition="new")
        self.market(self.long, "new-two", "125000", condition="new")
        result = self.result()
        result["data"]["usage_condition"] = "Usada"
        result["provenance"]["usage_condition"] = {"source": "visual_proposal", "review": "needs_review",
                                                       "component": "machine", "asset_id": "image-1"}

        family = build_family_reference(result, category=self.category)

        self.assertEqual((family["fields"]["estimate_min"], family["fields"]["estimate_max"]), ("60000.00", "75900.00"))
        self.assertEqual(family["identity"]["condition"], "used")
        self.assertTrue(all(item["condition"] == "used" for item in family["comparables"]))

    def test_unknown_condition_keeps_comparable_class_separate_from_the_unit(self):
        self.technical(self.base, 2007, 2014)
        self.market(self.base, "new-one", "120000", condition="new")
        self.market(self.long, "new-two", "125000", condition="new")

        family = build_family_reference(self.result(), category=self.category)

        self.assertIsNone(family["identity"]["condition"])
        self.assertIn("no se atribuye esa condición a la unidad", family["fields"]["estimate_basis"])
        self.assertNotIn("ajuste por condición", family["fields"]["estimate_basis"])

    def test_merge_is_reviewable_and_never_writes_model_or_price(self):
        self.technical(self.base, 2007, 2014)
        self.market(self.base, "one", "60000")
        self.market(self.long, "two", "75900")
        result = self.result()
        family = build_family_reference(result, category=self.category)

        merged = merge_family_reference(result, family)

        self.assertEqual(merged["data"]["model_family"], "320D")
        self.assertIsNone(merged["data"]["model"])
        self.assertNotIn("price", merged["data"])
        meta = merged["provenance"]["estimate_min"]
        self.assertTrue(is_validated_family_field(merged, "estimate_min", "60000.00", meta))
        self.assertFalse(is_validated_family_field(merged, "estimate_min", "1.00", meta))
        self.assertTrue(family_identity_matches({"brand": "Caterpillar", "model": "320D L", "model_family": "320D"}, family))
        self.assertFalse(family_identity_matches({"brand": "Caterpillar", "model": "320D2", "model_family": "320D"}, family))

    def test_rejects_unaccepted_or_unclear_visual_identity(self):
        self.technical(self.base, 2007, 2014)
        result = self.result()
        result["relevance"]["accepted_asset_ids"] = []
        self.assertIsNone(build_family_reference(result, category=self.category))
        result = self.result()
        result["provenance"]["brand"]["review"] = "needs_review"
        self.assertIsNone(build_family_reference(result, category=self.category))

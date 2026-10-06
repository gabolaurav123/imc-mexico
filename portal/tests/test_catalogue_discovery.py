"""Contract tests for paginated catalogue discovery."""
from datetime import date

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from portal.catalogue_intake import catalogue_choices
from portal.models import Brand, Category, EquipmentModel, MarketReference, TechnicalReference


class CatalogueDiscoveryTests(TestCase):
    url = "/api/maquinarias/catalogo/descubrir/"

    def setUp(self):
        self.excavators = Category.objects.create(name="Excavadoras hidráulicas", slug="excavadoras", active=True)
        self.loaders = Category.objects.create(name="Cargadores", slug="cargadores", active=True)
        self.cat = Brand.objects.create(name="Caterpillar", active=True)
        self.jlg = Brand.objects.create(name="JLG", active=True)
        self.inactive_brand = Brand.objects.create(name="Inactiva", active=False)
        self.e450 = EquipmentModel.objects.create(brand=self.jlg, category=self.excavators, name="E450AJ", active=True)
        self.electric = EquipmentModel.objects.create(brand=self.jlg, category=self.excavators, name="E450AJ eléctrica", active=True)
        self.loader = EquipmentModel.objects.create(brand=self.cat, category=self.loaders, name="950", active=True)
        self.inactive = EquipmentModel.objects.create(brand=self.cat, category=self.excavators, name="320", active=False)
        self.inactive_brand_model = EquipmentModel.objects.create(brand=self.inactive_brand, category=self.excavators, name="X1", active=True)
        self._reference(self.e450, self.excavators, specs={"power": {"value": "10 kW", "evidence": "Ficha."}},
                        provenance={"model_aliases": ["E 450 AJ"]}, period_from=2019)
        self._reference(self.e450, self.excavators, specs={})
        self._reference(self.electric, self.excavators, specs={})
        self._reference(self.loader, self.loaders, specs={})
        # It points to an active model but carries the wrong identity category.
        # Discovery and the legacy choices must both leave it out.
        self._reference(self.inactive_brand_model, self.loaders, specs={})
        MarketReference.objects.create(equipment_model=self.e450, source="https://market.example/e450",
            source_title="E450AJ", price="100.00", currency="USD", market="US", evidence="Oferta documentada.",
            retrieved_at=date(2026, 9, 25), review=MarketReference.Review.APPROVED, active=True)

    def _reference(self, model, category, *, specs, provenance=None, period_from=None):
        return TechnicalReference.objects.create(category=category, equipment_model=model,
            brand=model.brand.name, model=model.name, source=f"https://manufacturer.example/{model.pk}/{TechnicalReference.objects.count()}",
            source_title=f"{model.name} ficha", retrieved_at=date(2026, 9, 25), specs=specs,
            provenance=provenance or {}, period_from=period_from,
            review=TechnicalReference.Review.APPROVED, active=True)

    def get(self, **params):
        return self.client.get(self.url, params)

    def test_category_brand_model_cascade_has_exact_identity_and_coverage(self):
        categories = self.get(stage="categories")
        self.assertEqual(categories.status_code, 200, categories.content)
        category_items = categories.json()["items"]
        self.assertEqual({item["id"] for item in category_items}, {self.excavators.pk, self.loaders.pk})

        brands = self.get(stage="brands", category=self.excavators.pk)
        self.assertEqual(brands.status_code, 200, brands.content)
        self.assertEqual([item["id"] for item in brands.json()["items"]], [self.jlg.pk])
        self.assertEqual(brands.json()["items"][0]["category_id"], self.excavators.pk)

        models = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk)
        self.assertEqual(models.status_code, 200, models.content)
        items = {item["model_name"]: item for item in models.json()["items"]}
        self.assertEqual(set(items), {"E450AJ", "E450AJ eléctrica"})
        self.assertEqual(items["E450AJ"]["reference_count"], 2)
        self.assertTrue(items["E450AJ"]["has_specs"])
        self.assertTrue(items["E450AJ"]["has_period"])
        self.assertTrue(items["E450AJ"]["has_market"])
        self.assertTrue(items["E450AJ"]["can_prepare_from_catalogue"])

    def test_normalized_model_and_documented_alias_search(self):
        compact = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk, q="e450aj")
        self.assertEqual([item["model_name"] for item in compact.json()["items"]], ["E450AJ", "E450AJ eléctrica"])
        alias = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk, q="E 450 AJ")
        self.assertEqual([item["model_name"] for item in alias.json()["items"]], ["E450AJ", "E450AJ eléctrica"])
        # Brand aliases are useful before a model can be selected.
        self.assertEqual(self.get(stage="brands", category=self.loaders.pk, q="CAT").json()["items"][0]["label"], "Caterpillar")

    def test_model_search_uses_only_documented_aliases(self):
        alternate = EquipmentModel.objects.create(
            brand=self.jlg, category=self.excavators, name="A-150", active=True)
        self._reference(alternate, self.excavators, specs={}, provenance={
            "model_aliases": ["Altura 150"],
            "editor_note": "palabra-que-no-es-un-alias",
        })
        alias = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk, q="Altura 150")
        self.assertEqual([item["model_name"] for item in alias.json()["items"]], ["A-150"])
        metadata = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk,
                            q="palabra-que-no-es-un-alias")
        self.assertEqual(metadata.status_code, 200, metadata.content)
        self.assertEqual(metadata.json()["items"], [])

    def test_malformed_or_incomplete_scope_is_rejected_and_inactive_scope_is_empty(self):
        for params in ({"stage": "models", "category": "x", "brand": str(self.jlg.pk)},
                       {"stage": "brands"}, {"stage": "wrong"}, {"stage": "categories", "page": "0"},
                       {"stage": "brands", "category": "9" * 40},
                       {"stage": "models", "category": str(self.excavators.pk), "brand": "9" * 40},
                       {"stage": "categories", "page": "9" * 5000},
                       {"stage": "categories", "q": "x" * 81}):
            with self.subTest(params=params):
                response = self.get(**params)
                self.assertEqual(response.status_code, 400, response.content)
        inactive = self.get(stage="models", category=self.excavators.pk, brand=self.inactive_brand.pk)
        self.assertEqual(inactive.status_code, 200)
        self.assertEqual(inactive.json()["items"], [])

    def test_models_are_paged_and_do_not_emit_the_whole_catalogue(self):
        for number in range(30):
            model = EquipmentModel.objects.create(brand=self.jlg, category=self.excavators, name=f"Z{number:02}", active=True)
            self._reference(model, self.excavators, specs={})
        first = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk, page="1")
        second = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk, page="2")
        self.assertEqual(len(first.json()["items"]), 25)
        self.assertTrue(first.json()["has_more"])
        self.assertGreater(second.json()["total"], len(second.json()["items"]))
        self.assertLessEqual(len(second.json()["items"]), 25)

    def test_unfiltered_brands_are_paged_before_serialization(self):
        for number in range(30):
            brand = Brand.objects.create(name=f"Marca {number:02}", active=True)
            model = EquipmentModel.objects.create(brand=brand, category=self.excavators, name="M", active=True)
            self._reference(model, self.excavators, specs={})
        first = self.get(stage="brands", category=self.excavators.pk)
        second = self.get(stage="brands", category=self.excavators.pk, page="2")
        self.assertEqual(len(first.json()["items"]), 25)
        self.assertGreater(first.json()["total"], len(first.json()["items"]))
        self.assertLessEqual(len(second.json()["items"]), 25)

    def test_models_prioritize_documented_coverage_before_alphabetical_identity_rows(self):
        identity_only = EquipmentModel.objects.create(
            brand=self.jlg, category=self.excavators, name="A identity only", active=True)
        documented = EquipmentModel.objects.create(
            brand=self.jlg, category=self.excavators, name="Z documented", active=True)
        self._reference(identity_only, self.excavators, specs={})
        self._reference(documented, self.excavators, specs={"power": {"value": "12 kW", "evidence": "Ficha."}},
                        period_from=2020)
        items = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk).json()["items"]
        names = [item["model_name"] for item in items]
        self.assertLess(names.index("Z documented"), names.index("A identity only"))

    def test_endpoint_is_public_and_has_bounded_query_count(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.get(stage="models", category=self.excavators.pk, brand=self.jlg.pk, q="E450AJ")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertLessEqual(len(queries), 5, "model discovery should remain a small bounded query set")

    def test_legacy_choices_also_exclude_mismatched_reference_categories(self):
        choices = catalogue_choices()
        self.assertNotIn(self.inactive_brand_model.pk, {item["id"] for item in choices})

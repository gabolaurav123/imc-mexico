"""Market-library imports and valuations stay dated, exact and separate from asking price."""
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from portal.market_catalogue import MAX_REFERENCE_AGE_DAYS, ROOT, install_bundled_market, valuation_from_library
from portal.models import Brand, Category, EquipmentModel, MarketReference
from portal.valuation import estimate_machine


class MarketCatalogueTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        self.other_category = Category.objects.create(name="Cargadores", slug="cargadores")
        self.brand = Brand.objects.create(name="Caterpillar")
        self.model = EquipmentModel.objects.create(brand=self.brand, name="320D L", category=self.category)
        self.other_model = EquipmentModel.objects.create(brand=self.brand, name="320D L cargador", category=self.other_category)
        self.today = timezone.localdate()

    def listing(self, number, **overrides):
        value = {"url": f"https://market.example.invalid/{number}", "source": "Mercado de prueba", "title": f"Anuncio {number}",
                 "price": 40000 + number * 1000, "currency": "EUR", "market": "NL", "price_type": "asking",
                 "condition": "used", "observed_at": self.today.isoformat(), "evidence": "Precio, mercado y condición declarados.",
                 "unit_key": f"unit-{number}"}
        value.update(overrides)
        return value

    def bundle(self, listings, subject=None):
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name); (root / "records").mkdir()
        payload = {"subject": subject or {"brand": "Caterpillar", "model": "320D L", "category_slug": "excavadoras"}, "listings": listings}
        raw = json.dumps(payload, ensure_ascii=False).encode()
        (root / "records" / "market.json").write_bytes(raw)
        (root / "bundled.json").write_text(json.dumps({"files": [{"path": "records/market.json", "sha256": sha256(raw).hexdigest()}]}))
        return root

    def identity(self):
        return {"brand": "Caterpillar", "model": "320D L", "condition": "used", "configurations": {}, "compatibility": {}, "market_hint": None}

    def test_seed_links_exact_brand_model_category_and_preserves_staff_changes(self):
        root = self.bundle([self.listing(1), self.listing(2)])
        self.assertEqual(install_bundled_market(root), 2)
        self.assertEqual(set(MarketReference.objects.values_list("equipment_model_id", flat=True)), {self.model.pk})
        item = MarketReference.objects.first(); item.active = False; item.review = "rejected"; item.save()
        self.assertEqual(install_bundled_market(root), 0)
        item.refresh_from_db(); self.assertFalse(item.active); self.assertEqual(item.review, "rejected")
        wrong = self.bundle([self.listing(3)], {"brand": "Caterpillar", "model": "320D L", "category_slug": "cargadores"})
        with self.assertRaises(CommandError): install_bundled_market(wrong)

    def test_future_is_rejected_and_expired_is_historical_not_an_active_valuation(self):
        future = self.bundle([self.listing(1, observed_at=(self.today + timedelta(days=1)).isoformat())])
        with self.assertRaises(CommandError): install_bundled_market(future)
        for number in (1, 2):
            MarketReference.objects.create(equipment_model=self.model, source=f"https://old.example.invalid/{number}", source_title="Histórico",
                price=number * 100, currency="EUR", market="NL", price_type="asking", condition="used", retrieved_at=self.today - timedelta(days=MAX_REFERENCE_AGE_DAYS + 1), evidence="Anuncio histórico.", review="approved", active=True, unit_key=f"old-{number}")
        self.assertIsNone(valuation_from_library(self.identity(), self.category))

    def test_invalid_later_listing_rolls_back_the_complete_bundle(self):
        root = self.bundle([self.listing(1), self.listing(2, observed_at=123)])
        with self.assertRaises(CommandError):
            install_bundled_market(root)
        self.assertFalse(MarketReference.objects.exists())

    def test_market_references_reject_zero_prices_future_dates_and_unapproved_activation(self):
        reference = MarketReference(equipment_model=self.model, source="https://market.example.invalid/validation",
            source_title="Anuncio", price="0", currency="EUR", market="NL", retrieved_at=self.today,
            evidence="Precio visible en el anuncio.")
        with self.assertRaises(ValidationError):
            reference.full_clean()
        reference.price = "100"
        reference.retrieved_at = self.today + timedelta(days=1)
        with self.assertRaises(ValidationError):
            reference.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketReference.objects.create(equipment_model=self.model, source="https://market.example.invalid/unapproved",
                source_title="Anuncio", price="100", currency="EUR", market="NL", retrieved_at=self.today,
                evidence="Precio visible en el anuncio.", review="pending", active=True)

    def test_groups_do_not_mix_currency_market_sale_type_or_condition_and_duplicate_units_are_rejected(self):
        base = dict(equipment_model=self.model, source_title="Listado", currency="EUR", market="NL", price_type="asking", condition="used", retrieved_at=self.today, evidence="Anuncio fechado.", review="approved", active=True)
        for number, price in ((1, 40000), (2, 42000)):
            MarketReference.objects.create(**base, source=f"https://same.example.invalid/{number}", price=price, unit_key=f"unit-{number}")
        for number, currency, market, price_type, condition in ((3, "USD", "NL", "asking", "45000"), (4, "EUR", "MX", "asking", "46000"), (5, "EUR", "NL", "sold", "47000"), (6, "EUR", "NL", "new", "48000")):
            MarketReference.objects.create(**{**base, "currency": currency, "market": market, "price_type": price_type, "condition": condition}, source=f"https://different.example.invalid/{number}", price=price, unit_key=f"other-{number}")
        MarketReference.objects.create(**base, source="https://duplicate.example.invalid/one", price="41000", unit_key="unit-1")
        value = valuation_from_library(self.identity(), self.category)
        self.assertEqual(value["fields"]["estimate_currency"], "EUR")
        self.assertEqual(value["fields"]["estimate_market"], "Países Bajos")
        self.assertEqual(value["diagnostics"]["accepted_comparable_count"], 2)
        self.assertEqual(len(value["comparables"]), 2)

    def test_newest_observation_blocks_an_older_incompatible_variant_of_the_same_unit(self):
        base = dict(equipment_model=self.model, source_title="Listado", currency="EUR", market="NL",
                    price_type="asking", condition="used", evidence="Anuncio fechado.", review="approved", active=True)
        # This unit was later observed as STD. Its previous LC observation must
        # not revive simply because the current machine declares LC.
        MarketReference.objects.create(**base, source="https://market.example.invalid/unit-one-old", price="40000",
            retrieved_at=self.today - timedelta(days=2), unit_key="unit-one", configurations={"variant": "LC"})
        MarketReference.objects.create(**base, source="https://market.example.invalid/unit-one-new", price="41000",
            retrieved_at=self.today, unit_key=" UNIT-ONE ", configurations={"variant": "STD"})
        MarketReference.objects.create(**base, source="https://market.example.invalid/unit-two", price="42000",
            retrieved_at=self.today, unit_key="unit-two", configurations={"variant": "LC"})
        identity = {**self.identity(), "compatibility": {"variant": "LC"}}
        self.assertIsNone(valuation_from_library(identity, self.category))

    def test_malformed_legacy_observation_cannot_interrupt_valid_reuse(self):
        base = dict(equipment_model=self.model, source_title="Listado", currency="EUR", market="NL",
                    price_type="asking", condition="used", retrieved_at=self.today, evidence="Anuncio fechado.",
                    review="approved", active=True)
        MarketReference.objects.create(**base, source="https://market.example.invalid/good-one", price="40000", unit_key="one")
        MarketReference.objects.create(**base, source="https://market.example.invalid/good-two", price="42000", unit_key="two")
        MarketReference.objects.create(**base, source="https://market.example.invalid/legacy", price="43000", unit_key="three",
                                       configurations=[])
        value = valuation_from_library(self.identity(), self.category)
        self.assertEqual(value["status"], "estimated")
        self.assertEqual(value["diagnostics"]["accepted_comparable_count"], 2)

    def test_invalid_identity_collections_fail_closed_without_touching_the_library(self):
        self.assertIsNone(valuation_from_library({**self.identity(), "configurations": []}, self.category))
        self.assertIsNone(valuation_from_library({**self.identity(), "compatibility": []}, self.category))

    def test_library_reuses_normalized_catalogue_model_without_scanning_other_model_rows(self):
        alternate = EquipmentModel.objects.create(brand=self.brand, name="320D-L", category=self.category)
        base = dict(equipment_model=alternate, source_title="Listado", currency="USD", market="US",
                    price_type="asking", condition="used", retrieved_at=self.today,
                    evidence="Anuncio individual fechado.", review="approved", active=True)
        MarketReference.objects.create(**base, source="https://market.example.invalid/alternate-one",
                                       price="40000", unit_key="alternate-one")
        MarketReference.objects.create(**base, source="https://market.example.invalid/alternate-two",
                                       price="42000", unit_key="alternate-two")
        result = valuation_from_library({**self.identity(), "model": "320 D L"}, self.category)
        self.assertEqual(result["status"], "estimated")
        self.assertEqual({item["url"] for item in result["comparables"]}, {
            "https://market.example.invalid/alternate-one", "https://market.example.invalid/alternate-two"})

    def test_library_reference_uses_zero_ai_calls_and_never_sets_owner_price(self):
        root = self.bundle([self.listing(1), self.listing(2)])
        install_bundled_market(root)
        result = {"data": {"brand": "Caterpillar", "model": "320D L", "condition": "Usada"},
                  "provenance": {key: {"source": "user", "review": "confirmed"} for key in ("brand", "model", "condition")}}
        client = Mock()
        value, usage = estimate_machine(client, "test-model", result, result, category=self.category)
        self.assertEqual(value["status"], "estimated")
        self.assertNotIn("price", value["fields"])
        self.assertEqual(usage.web_search_calls, 0)
        client.responses.create.assert_not_called()


class BundledMarketCoverageTests(TestCase):
    """The reviewed bundle remains a small evidence library, not an inventory."""

    def setUp(self):
        excavators = Category.objects.create(name="Excavadoras", slug="excavadoras")
        forklifts = Category.objects.create(name="Montacargas", slug="montacargas")
        loaders = Category.objects.create(name="Cargadores", slug="cargadores")
        backhoes = Category.objects.create(name="Retroexcavadoras", slug="retroexcavadoras")
        cat = Brand.objects.create(name="Caterpillar")
        toyota = Brand.objects.create(name="Toyota")
        komatsu = Brand.objects.create(name="Komatsu")
        manitou = Brand.objects.create(name="Manitou")
        deere = Brand.objects.create(name="John Deere")
        for brand, name, category in ((cat, "320D L", excavators), (cat, "320D", excavators),
                                      (cat, "306 CR", excavators), (toyota, "50-8FGCU25", forklifts),
                                      (komatsu, "PC210LC-11", excavators),
                                      (manitou, "MT-625-H", Category.objects.create(
                                          name="Manipuladores telescópicos", slug="manipuladores-telescopicos")),
                                      (cat, "950 GC", loaders), (deere, "310SL", backhoes)):
            EquipmentModel.objects.create(brand=brand, name=name, category=category)
        self.category = excavators
        self.loaders = loaders
        self.backhoes = backhoes

    def test_bundle_imports_dated_individual_ads_and_reuses_306_cr_range(self):
        self.assertEqual(install_bundled_market(ROOT), 20)
        rows = MarketReference.objects.filter(equipment_model__name="306 CR")
        self.assertEqual(rows.count(), 3)
        self.assertEqual(set(rows.values_list("market", flat=True)), {"US"})
        self.assertEqual(set(rows.values_list("condition", flat=True)), {"used"})
        self.assertEqual(set(rows.values_list("price_type", flat=True)), {"asking"})
        self.assertEqual(set(rows.values_list("year", flat=True)), {2020, 2021, 2024})
        value = valuation_from_library({"brand": "Caterpillar", "model": "306CR", "condition": "used",
                                        "configurations": {}, "compatibility": {}, "market_hint": None}, self.category)
        self.assertEqual(value["status"], "estimated")
        self.assertEqual(value["fields"]["estimate_min"], "38999.00")
        self.assertEqual(value["fields"]["estimate_max"], "65500.00")
        self.assertTrue(all(item["price_type"] == "asking" for item in value["comparables"]))

    def test_new_loader_and_backhoe_ranges_are_reused_locally_without_provider(self):
        self.assertEqual(install_bundled_market(ROOT), 20)
        loader = valuation_from_library({"brand": "Caterpillar", "model": "950GC", "condition": "used",
                                         "configurations": {}, "compatibility": {}, "market_hint": None}, self.loaders)
        backhoe = valuation_from_library({"brand": "John Deere", "model": "310SL", "condition": "used",
                                          "configurations": {}, "compatibility": {}, "market_hint": None}, self.backhoes)

        self.assertEqual((loader["status"], loader["fields"]["estimate_min"], loader["fields"]["estimate_max"]),
                         ("estimated", "199000.00", "239000.00"))
        self.assertEqual((backhoe["status"], backhoe["fields"]["estimate_min"], backhoe["fields"]["estimate_max"]),
                         ("estimated", "59000.00", "59500.00"))
        self.assertEqual(loader["diagnostics"]["parser"], "reviewed_market_library")
        self.assertEqual(backhoe["diagnostics"]["parser"], "reviewed_market_library")
        self.assertTrue(any("configuración 01B" in item["evidence"] for item in loader["comparables"]))

        client = Mock()
        reading = {"data": {"brand": "Caterpillar", "model": "950GC", "condition": "used"},
                   "provenance": {key: {"source": "user", "review": "confirmed"}
                                  for key in ("brand", "model", "condition")}}
        via_pipeline, usage = estimate_machine(client, "test-model", reading, reading, category=self.loaders)
        self.assertEqual((via_pipeline["fields"]["estimate_min"], via_pipeline["fields"]["estimate_max"]),
                         ("199000.00", "239000.00"))
        self.assertEqual(usage.web_search_calls, 0)
        client.responses.create.assert_not_called()

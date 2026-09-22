"""Market-library imports and valuations stay dated, exact and separate from asking price."""
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from portal.market_catalogue import MAX_REFERENCE_AGE_DAYS, install_bundled_market, valuation_from_library
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

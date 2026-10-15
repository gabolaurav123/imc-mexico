"""Curated multi-category evidence stays useful without an AI call."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from portal.catalogue_intake import catalogue_proposal
from portal.knowledge_catalogue import KNOWLEDGE_ROOT, bundled_records, install_bundled_knowledge, validate_record
from portal.market_catalogue import install_bundled_market
from portal.models import Category, EquipmentModel, MarketReference, TechnicalReference
from portal.research import compose_description


OFFICIAL_SOURCE = "catalogue_official_multicategory_2026-10-15.json"
MARKET_SOURCE = "manitou_mt625h_listings_2026-10-15.json"
DEPTH_MODELS_BY_BRAND = {
    "Caterpillar": {"950 GC", "CS10 GC", "CP7", "CS11 GC", "CP11 GC"},
    "Manitou": {"MT-625-H"},
    "Toyota": {"8FGCU25"},
    "Genie": {
        "GS-1930", "GS1330M", "GS1530", "GS1932", "GS2032", "GS2632", "GS3232",
        "GS2046", "GS2646", "GS3246", "GS4047", "GS4655", "Z30-20N", "Z30-20NRJ",
    },
    "Bobcat": {"S740", "S130", "S185", "S160", "S175", "450", "773 C-Series", "642", "853", "E145"},
}


def _release(root: Path, path: str, payload: bytes):
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_bytes(payload)
    (root / "bundled.json").write_text(json.dumps({"files": [{
        "path": path, "sha256": hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest(),
    }]}), encoding="utf-8")


class CatalogueDepthTests(TestCase):
    def setUp(self):
        self.official = json.loads((KNOWLEDGE_ROOT / OFFICIAL_SOURCE).read_text(encoding="utf-8"))["references"]
        self.market = json.loads((KNOWLEDGE_ROOT / "market" / MARKET_SOURCE).read_text(encoding="utf-8"))
        for row in self.official:
            Category.objects.create(slug=row["category_slug"], name={
                "cargadores": "Cargadores",
                "manipuladores-telescopicos": "Manipuladores telescópicos",
                "montacargas": "Montacargas",
                "plataformas-elevadoras": "Plataformas elevadoras",
            }[row["category_slug"]])

    def _install_technical(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = json.dumps({"references": self.official}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            _release(root, "official.json", raw)
            return install_bundled_knowledge(root)

    def _install_market(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = json.dumps(self.market, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            _release(root, "records/manitou.json", raw)
            return install_bundled_market(root)

    def test_official_bundle_covers_distinct_equipment_families_with_cited_specs(self):
        rows = [row for row in bundled_records() if row["source_title"] in {
            "950 GC Wheel Loader | Cat México", "MT 625 H | Manitou",
            "Toyota Core IC Cushion Tire 8FGCU25 specification sheet",
            "Genie GS-1930 Operator's Manual — Specifications",
        }]
        self.assertEqual({row["category_slug"] for row in rows}, {
            "cargadores", "manipuladores-telescopicos", "montacargas", "plataformas-elevadoras",
        })
        for row in rows:
            validate_record(row)
            self.assertEqual(row["provenance"]["authority"], "manufacturer")
            self.assertTrue(row["specs"])
            for spec in row["specs"].values():
                self.assertTrue(spec["value"])
                self.assertIn(row["model"], spec["evidence"])

    def test_official_depth_release_keeps_verified_multi_category_coverage(self):
        rows = [
            row for row in bundled_records()
            if row["retrieved_at"] == "2026-10-15"
            and row["model"] in DEPTH_MODELS_BY_BRAND.get(row["brand"], set())
        ]
        self.assertEqual(len(rows), 31)
        self.assertEqual(sum(len(row["specs"]) for row in rows), 100)
        self.assertGreaterEqual(len({row["category_slug"] for row in rows}), 7)
        for row in rows:
            with self.subTest(model=row["model"]):
                validate_record(row)
                self.assertEqual(row["provenance"]["authority"], "manufacturer")

    def test_catalogue_reuses_local_specs_and_dated_market_range_without_provider(self):
        self.assertEqual(self._install_technical(), 4)
        self.assertEqual(self._install_market(), 2)
        model = EquipmentModel.objects.get(brand__name="Manitou", name="MT-625-H")
        proposal = catalogue_proposal(model.category_id, model.pk)
        self.assertEqual(TechnicalReference.objects.count(), 4)
        self.assertEqual(MarketReference.objects.count(), 2)
        self.assertEqual(proposal["data"]["capacity"], "2500 kg")
        self.assertEqual(proposal["data"]["lift_height"], "5.85 m")
        self.assertEqual(proposal["data"]["estimate_min"], "59900.00")
        self.assertEqual(proposal["data"]["estimate_max"], "71900.00")
        self.assertEqual(proposal["data"]["estimate_currency"], "USD")
        self.assertIn("Capacidad: 2500 kg", proposal["data"]["description"])
        self.assertIn("Altura de elevación: 5.85 m", proposal["data"]["description"])

    def test_category_summaries_use_meaningful_fields_instead_of_one_generic_order(self):
        provenance = {key: {"source": "web", "review": "needs_review"} for key in (
            "brand", "model", "capacity", "lift_height", "horizontal_outreach", "platform_height", "power", "weight",
        )}
        telehandler = compose_description({
            "brand": "Manitou", "model": "MT 625 H", "capacity": "2500 kg", "lift_height": "5.85 m",
            "horizontal_outreach": "3.40 m", "power": "55.40 kW", "weight": "4 800 kg",
        }, provenance, "Manipuladores telescópicos")
        platform = compose_description({
            "brand": "Genie", "model": "GS-1930", "platform_height": "5.85 m",
            "capacity": "227 kg", "weight": "1 498 kg", "power": "eléctrica",
        }, provenance, "Plataformas elevadoras")
        self.assertIn("Alcance horizontal: 3.40 m", telehandler)
        self.assertIn("Altura de plataforma: 5.85 m", platform)
        self.assertIn("Capacidad: 227 kg", platform)

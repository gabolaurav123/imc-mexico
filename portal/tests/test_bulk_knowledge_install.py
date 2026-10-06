"""Regression coverage for the batched reviewed-knowledge installer."""
from __future__ import annotations

import hashlib
import json
from tempfile import TemporaryDirectory
from pathlib import Path

from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from portal.knowledge_catalogue import install_bundled_knowledge
from portal.models import Brand, Category, EquipmentModel, TechnicalReference


class BulkKnowledgeInstallTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras", active=True)

    def record(self, model, **changes):
        item = {
            "category_slug": self.category.slug,
            "brand": "Caterpillar",
            "model": model,
            "variant": "",
            "generation": "",
            "market": "MX",
            "source": f"https://manufacturer.example/{model}",
            "source_title": f"Caterpillar {model} specification",
            "source_version": "release-test",
            "retrieved_at": "2026-10-01",
            "period_from": None,
            "period_to": None,
            "specs": {},
            "provenance": {"authority": "manufacturer", "scope": "model"},
        }
        item.update(changes)
        return item

    def install(self, records):
        with TemporaryDirectory(prefix="imc-bulk-knowledge-") as directory:
            root = Path(directory)
            payload = json.dumps({"references": records}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            path = root / "records.json"
            path.write_bytes(payload)
            manifest = {"files": [{"path": "records.json",
                                    "sha256": hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()}]}
            (root / "bundled.json").write_text(json.dumps(manifest), encoding="utf-8")
            return install_bundled_knowledge(root)

    def test_large_release_uses_batched_queries_and_is_idempotent(self):
        records = [self.record(f"M{index:04d}") for index in range(800)]
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.install(records), 800)
        # Query count scales with batches, not one DB scan or insert per model.
        # SQLite splits bulk inserts for its parameter limit; this remains a
        # small batch-bound query set rather than one query per 800 rows.
        self.assertLessEqual(len(queries), 35, len(queries))
        self.assertEqual(Brand.objects.count(), 1)
        self.assertEqual(EquipmentModel.objects.count(), 800)
        self.assertEqual(TechnicalReference.objects.count(), 800)

        with CaptureQueriesContext(connection) as restart_queries:
            self.assertEqual(self.install(records), 0)
        self.assertLessEqual(len(restart_queries), 12, len(restart_queries))
        self.assertEqual(TechnicalReference.objects.count(), 800)

    def test_existing_staff_link_and_reference_values_are_never_overwritten(self):
        brand = Brand.objects.create(name="Caterpillar", active=False)
        model = EquipmentModel.objects.create(brand=brand, category=self.category, name="320", active=False)
        existing = TechnicalReference.objects.create(
            category=self.category, equipment_model=model, brand="Caterpillar", model="320",
            market="MX", source="https://manufacturer.example/320", variant="", generation="",
            source_title="Título editado por el equipo", source_version="staff-v2", retrieved_at="2026-09-01",
            specs={"power": {"value": "99 kW", "evidence": "Staff value."}}, provenance={"staff": True},
            review=TechnicalReference.Review.APPROVED, active=False,
        )
        self.assertEqual(self.install([self.record("320", specs={"power": {"value": "121 kW", "evidence": "Release value."}})]), 0)
        existing.refresh_from_db(); brand.refresh_from_db(); model.refresh_from_db()
        self.assertEqual(existing.source_title, "Título editado por el equipo")
        self.assertEqual(existing.specs["power"]["value"], "99 kW")
        self.assertEqual(existing.provenance, {"staff": True})
        self.assertFalse(existing.active)
        self.assertFalse(brand.active)
        self.assertFalse(model.active)

    def test_incompatible_staff_model_category_is_not_reclassified(self):
        other = Category.objects.create(name="Cargadores", slug="cargadores", active=True)
        brand = Brand.objects.create(name="Caterpillar")
        staff_model = EquipmentModel.objects.create(brand=brand, category=other, name="320")
        self.assertEqual(self.install([self.record("320")]), 1)
        reference = TechnicalReference.objects.get(source="https://manufacturer.example/320")
        self.assertIsNone(reference.equipment_model_id)
        staff_model.refresh_from_db()
        self.assertEqual(staff_model.category_id, other.pk)

    def test_invalid_later_reference_rolls_back_earlier_batches_and_catalogue_rows(self):
        malformed = self.record("BAD", period_from=2026, period_to=2020)
        with self.assertRaises(CommandError):
            self.install([self.record("GOOD"), malformed])
        self.assertFalse(Brand.objects.exists())
        self.assertFalse(EquipmentModel.objects.exists())
        self.assertFalse(TechnicalReference.objects.exists())

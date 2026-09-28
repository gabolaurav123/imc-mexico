"""Deployment repairs energy labels only in untouched release references."""
from copy import deepcopy
from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ElectricPlatformEnergyMigrationTests(TransactionTestCase):
    previous = [("portal", "0022_ai_usage_reset_50")]
    target = [("portal", "0023_correct_electric_platform_energy")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(self.previous)
        self.old_apps = executor.loader.project_state(self.previous).apps
        self.originals = import_module("portal.migrations.0023_correct_electric_platform_energy").ORIGINAL_RECORDS
        self.category = self.old_apps.get_model("portal", "Category").objects.create(
            name="Plataformas elevadoras", slug="plataformas-elevadoras")

    def reference(self, original, **changes):
        values = deepcopy(original)
        values.pop("category_slug")
        values.update(category=self.category, review="approved", active=True)
        values.update(changes)
        return self.old_apps.get_model("portal", "TechnicalReference").objects.create(**values)

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.target)
        return executor.loader.project_state(self.target).apps.get_model("portal", "TechnicalReference")

    def test_exact_old_release_rows_move_electric_to_fuel_without_changing_evidence(self):
        originals = [(self.reference(record), record) for record in self.originals]
        Reference = self.migrate_forward()
        for old, record in originals:
            with self.subTest(model=record["model"]):
                current = Reference.objects.get(pk=old.pk)
                expected = deepcopy(record["specs"])
                expected["fuel"] = expected.pop("power")
                self.assertEqual(current.specs, expected)
                self.assertEqual(current.specs["fuel"]["value"], "electric")
                self.assertEqual(current.provenance, old.provenance)
                self.assertEqual((current.review, current.active, current.reviewed_by_id), ("approved", True, None))
                self.assertEqual(current.source, old.source)
                self.assertEqual(current.reviewed_at, old.reviewed_at)
        # A later deployment must neither duplicate rows nor rerun the repair.
        self.migrate_forward()
        self.assertEqual(Reference.objects.count(), 2)

    def test_staff_edits_reviews_disabled_and_other_source_records_are_preserved(self):
        user = self.old_apps.get_model("portal", "User").objects.create(email="energy-review@example.invalid")
        preserved = []
        for record in self.originals:
            for change in (
                {"specs": {**record["specs"], "weight": {"value": "edited", "evidence": "Human edit"}}},
                {"provenance": {**record["provenance"], "note": "Human correction"}},
                {"active": False},
                {"reviewed_by": user},
                {"source": "https://manufacturer.example.invalid/another-reference"},
            ):
                reference = self.reference(record, **change)
                preserved.append((reference.pk, reference.specs, reference.provenance,
                                  reference.active, reference.reviewed_by_id, reference.source))
        Reference = self.migrate_forward()
        for pk, specs, provenance, active, reviewer, source in preserved:
            with self.subTest(reference=pk):
                current = Reference.objects.get(pk=pk)
                self.assertEqual(current.specs, specs)
                self.assertEqual(current.provenance, provenance)
                self.assertEqual((current.active, current.reviewed_by_id, current.source), (active, reviewer, source))

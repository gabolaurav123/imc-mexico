from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from portal.knowledge import research_from_knowledge, retrieve_technical_references
from portal.models import Category, Machine, MachineVersion, TechnicalReference, User
from portal.research import research_machine
from portal.structured_data import normalize_structured_data, validate_manual_data, version_search_fields


class StructuredDataTests(SimpleTestCase):
    def test_projects_legacy_units_without_replacing_legacy_text(self):
        payload = {"weight": "22.6 t", "digging_depth": "6720 mm", "power": "117 kW",
                   "capacity": "1.19 m3", "hours": "1200.5", "price": "500000", "currency": "mxn"}
        value = normalize_structured_data(payload)
        self.assertEqual(value["weight_kg"], Decimal("22600.0"))
        self.assertEqual(value["digging_depth_m"], Decimal("6.720"))
        self.assertEqual(value["power_kw"], Decimal("117"))
        self.assertEqual(value["capacity_m3"], Decimal("1.19"))
        self.assertEqual(value["currency"], "MXN")
        self.assertEqual(payload["weight"], "22.6 t")

    def test_ambiguous_or_compound_legacy_values_do_not_become_search_values(self):
        result = normalize_structured_data({"weight": "1,500 kg", "power": "4.8 kW / 6.5 HP"})
        self.assertIsNone(result["weight_kg"])
        self.assertIsNone(result["power_kw"])
        # Old free text stays accepted by manual validation.
        validate_manual_data({"power": "4.8 kW / 6.5 HP"})

    def test_nonfinite_numbers_and_existing_unknown_conservation_do_not_break_projection(self):
        self.assertIsNone(normalize_structured_data({"hours": Decimal("NaN")})["hours"])
        self.assertIsNone(normalize_structured_data({"price": float("inf")})["price"])
        self.assertIsNone(validate_manual_data({"preservation_condition": "Por confirmar"})["preservation_condition"])

    def test_spaced_units_project_and_out_of_range_numbers_remain_null(self):
        self.assertEqual(normalize_structured_data({"weight": "21\u00a0500 kg"})["weight_kg"], Decimal("21500"))
        enormous = normalize_structured_data({"hours": "1000000000000", "price": "100000000000000",
                                               "currency": "MXN", "weight": "100000000000 t",
                                               "digging_depth": "1000000000 m"})
        for key in ("hours", "price", "weight_kg", "digging_depth_m"):
            self.assertIsNone(enormous[key])
        with self.assertRaises(ValidationError):
            validate_manual_data({"hours": "1000000000000"})

    def test_rejects_incompatible_interval_and_uncontrolled_new_values(self):
        with self.assertRaises(ValidationError):
            validate_manual_data({"estimated_year_from": "2020", "estimated_year_to": "2019"})
        with self.assertRaises(ValidationError):
            validate_manual_data({"undercarriage": "tracks maybe"})

    def test_unconfirmed_valuation_price_is_not_indexed(self):
        values = version_search_fields({"data": {"price": "100", "currency": "MXN"},
                                        "provenance": {"price": {"source": "valuation", "review": "needs_review"}}})
        self.assertIsNone(values["price"])
        self.assertEqual(values["currency"], "")


class VersionProjectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="structured@example.test", password="x")
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        self.machine = Machine.objects.create(owner=self.user, category=self.category)

    def test_version_projects_snapshot_without_mutating_it(self):
        payload = {"data": {"brand": "Caterpillar", "model": "320", "weight": "22600 kg",
                             "digging_depth": "6720 mm", "location_country": "MX",
                             "preservation_condition": "Buena"}}
        version = MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.user, data=payload)
        self.assertEqual(version.category, self.category)
        self.assertEqual(version.weight_kg, Decimal("22600"))
        self.assertEqual(version.digging_depth_m, Decimal("6.720"))
        self.assertEqual(version.preservation_condition, "good")
        self.assertNotIn("structured", payload)

    def test_knowledge_requires_review_active_and_exact_variant_market(self):
        reference = TechnicalReference.objects.create(
            category=self.category, brand="Caterpillar", model="320", variant="L", market="MX",
            source="https://www.cat.com/en_MX/products/new/equipment/excavators/medium-excavators/126534.html",
            source_title="320 Hydraulic Excavator", retrieved_at=timezone.localdate(), specs={},
            review=TechnicalReference.Review.APPROVED, active=True)
        snapshot = {"data": {"brand": "Caterpillar", "model": "320", "variant": "L", "location_country": "México"},
                    "provenance": {"location_country": {"source": "user", "review": "confirmed"},
                                   "variant": {"source": "user", "review": "confirmed"}}}
        self.assertEqual(retrieve_technical_references(snapshot, self.category), [reference])
        snapshot["provenance"]["location_country"] = {"source": "image", "review": "clear"}
        self.assertEqual(retrieve_technical_references(snapshot, self.category), [])
        snapshot["provenance"]["location_country"] = {"source": "user", "review": "confirmed"}
        snapshot["data"]["location_country"] = "País no catalogado"
        self.assertEqual(retrieve_technical_references(snapshot, self.category), [])
        snapshot["data"]["location_country"] = "México"
        snapshot["data"]["variant"] = "GC"
        self.assertEqual(retrieve_technical_references(snapshot, self.category), [])

    def test_knowledge_result_uses_existing_signed_research_normalizer(self):
        TechnicalReference.objects.create(
            category=self.category, brand="Caterpillar", model="320", market="MX",
            source="https://www.cat.com/en_MX/products/new/equipment/excavators/medium-excavators/126534.html",
            source_title="320 Hydraulic Excavator", retrieved_at=timezone.localdate(),
            specs={"weight": {"value": "21300 kg", "evidence": "Caterpillar 320: Operating Weight 21300 kg."}},
            review=TechnicalReference.Review.APPROVED, active=True)
        result = research_from_knowledge({}, {"data": {"brand": "Caterpillar", "model": "320", "location_country": "MX"},
                                               "provenance": {"location_country": {"source": "user"}}}, self.category)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["fields"][0]["key"], "weight")
        self.assertEqual(result["fields"][0]["scope"], "model")

    def test_local_import_creates_pending_inactive_reference(self):
        call_command("import_technical_knowledge", path="knowledge/excavadoras")
        reference = TechnicalReference.objects.get(category=self.category, brand="Caterpillar", model="320")
        self.assertEqual(reference.review, TechnicalReference.Review.PENDING)
        self.assertFalse(reference.active)

    def test_complete_local_reference_precedes_external_research(self):
        from unittest.mock import Mock
        TechnicalReference.objects.create(
            category=self.category, brand="Caterpillar", model="320", market="MX",
            source="https://www.cat.com/en_MX/products/new/equipment/excavators/medium-excavators/126534.html",
            source_title="320 Hydraulic Excavator", retrieved_at=timezone.localdate(),
            specs={
                "weight": {"value": "21300 kg", "evidence": "Caterpillar 320: Operating Weight 21300 kg."},
                "power": {"value": "117 kW", "evidence": "Caterpillar 320: Net Power 117 kW."},
                "digging_depth": {"value": "6720 mm", "evidence": "Caterpillar 320: Maximum Digging Depth 6720 mm."},
                "estimated_year_from": {"value": "2018", "evidence": "Caterpillar 320: Production years 2018-2024."},
                "estimated_year_to": {"value": "2024", "evidence": "Caterpillar 320: Production years 2018-2024."},
            },
            review=TechnicalReference.Review.APPROVED, active=True)
        client = Mock()
        snapshot = {"category": "Excavadoras", "provenance": {"category": {"source": "user"},
                    "brand": {"source": "user"}, "model": {"source": "user"},
                    "location_country": {"source": "user"}},
                    "data": {"brand": "Caterpillar", "model": "320", "location_country": "México"}}
        visual = {"data": {"brand": "Caterpillar", "model": "320"},
                  "provenance": {"brand": {"source": "user"}, "model": {"source": "user"}}}
        research, usage = research_machine(client, "gpt-4.1-mini", visual, snapshot,
                                           allowed_categories=["Excavadoras"], knowledge_category=self.category)
        self.assertEqual(research["status"], "completed")
        self.assertEqual({field["key"] for field in research["fields"]},
                         {"weight", "power", "digging_depth", "estimated_year_from", "estimated_year_to", "estimated_year_basis"})
        self.assertEqual(usage.web_search_calls, 0)
        client.responses.create.assert_not_called()

    def test_partial_local_period_supplements_and_retains_verified_fields_after_provider_failure(self):
        from unittest.mock import Mock
        TechnicalReference.objects.create(
            category=self.category, brand="Volvo", model="EC210B", market="MX",
            source="https://www.volvoce.com/global/en/products-and-services/past-products/crawler-excavators/volvo-b-prime-series/ec210b/",
            source_title="EC210B - Volvo | Volvo Construction Equipment", retrieved_at=timezone.localdate(),
            specs={
                "estimated_year_from": {"value": "2003", "evidence": "Volvo EC210B: Production year 2003-2009."},
                "estimated_year_to": {"value": "2009", "evidence": "Volvo EC210B: Production year 2003-2009."},
            }, review=TechnicalReference.Review.APPROVED, active=True)
        client = Mock()
        client.responses.create.side_effect = TimeoutError("provider unavailable")
        snapshot = {"category": "Excavadoras", "data": {"brand": "Volvo", "model": "EC210B", "location_country": "México"},
                    "provenance": {"category": {"source": "user"}, "brand": {"source": "user"},
                                   "model": {"source": "user"}, "location_country": {"source": "user"}}}
        visual = {"data": {"brand": "Volvo", "model": "EC210B"},
                  "provenance": {"brand": {"source": "user"}, "model": {"source": "user"}}}
        research, _ = research_machine(client, "gpt-4.1-mini", visual, snapshot,
                                       allowed_categories=["Excavadoras"], knowledge_category=self.category)
        self.assertTrue(client.responses.create.called)
        self.assertEqual({field["key"] for field in research["fields"]},
                         {"estimated_year_from", "estimated_year_to", "estimated_year_basis"})
        self.assertEqual(research["status"], "completed")
        self.assertTrue(any(warning.startswith("Una etapa de la investigación no se completó")
                            for warning in research["warnings"]))

    def test_cancelled_partial_local_supplement_does_not_apply_partial_fields(self):
        from unittest.mock import Mock
        TechnicalReference.objects.create(
            category=self.category, brand="Volvo", model="EC210B", market="MX",
            source="https://www.volvoce.com/global/en/products-and-services/past-products/crawler-excavators/volvo-b-prime-series/ec210b/",
            source_title="EC210B - Volvo | Volvo Construction Equipment", retrieved_at=timezone.localdate(),
            specs={"estimated_year_from": {"value": "2003", "evidence": "Volvo EC210B: Production year 2003-2009."},
                   "estimated_year_to": {"value": "2009", "evidence": "Volvo EC210B: Production year 2003-2009."}},
            review=TechnicalReference.Review.APPROVED, active=True)
        client = Mock()
        snapshot = {"category": "Excavadoras", "data": {"brand": "Volvo", "model": "EC210B", "location_country": "México"},
                    "provenance": {"category": {"source": "user"}, "brand": {"source": "user"},
                                   "model": {"source": "user"}, "location_country": {"source": "user"}}}
        visual = {"data": {"brand": "Volvo", "model": "EC210B"},
                  "provenance": {"brand": {"source": "user"}, "model": {"source": "user"}}}
        research, _ = research_machine(client, "gpt-4.1-mini", visual, snapshot, allowed=lambda: False,
                                       allowed_categories=["Excavadoras"], knowledge_category=self.category)
        self.assertEqual(research["fields"], [])
        self.assertEqual(research["status"], "degraded")
        client.responses.create.assert_not_called()

    def test_bundled_reference_requires_explicit_tier_three_variant(self):
        call_command("seed")
        snapshot = {"data": {"brand": "Caterpillar", "model": "320", "location_country": "MX"},
                    "provenance": {"location_country": {"source": "user"}}}
        self.assertEqual(retrieve_technical_references(snapshot, self.category), [])
        snapshot["data"]["variant"] = "Tier 3"
        snapshot["provenance"]["variant"] = {"source": "user"}
        self.assertEqual(len(retrieve_technical_references(snapshot, self.category)), 1)

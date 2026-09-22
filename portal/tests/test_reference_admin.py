"""Review actions and market-observation selection stay conservative and auditable."""
from datetime import timedelta
from unittest.mock import Mock

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.utils import timezone

from portal.knowledge_admin import MarketReferenceAdmin, TechnicalReferenceAdmin
from portal.market_observations import latest_market_observations, market_unit_key
from portal.models import (AuditEvent, Brand, Category, EquipmentModel, MarketReference,
                           TechnicalReference, User)


class ReferenceAdminActionsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(email="reference-reviewer@example.invalid", is_staff=True)
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        self.brand = Brand.objects.create(name="Caterpillar")
        self.model = EquipmentModel.objects.create(brand=self.brand, name="320", category=self.category)
        self.today = timezone.localdate()

    def request(self):
        request = self.factory.post("/administracion/")
        request.user = self.user
        return request

    def technical(self, **changes):
        values = {"category": self.category, "equipment_model": self.model, "brand": "Caterpillar",
                  "model": "320", "source": "https://manufacturer.example.invalid/320",
                  "source_title": "Manual", "retrieved_at": self.today, "specs": {}, "provenance": {},
                  "review": TechnicalReference.Review.PENDING, "active": False}
        values.update(changes)
        return TechnicalReference.objects.create(**values)

    def market(self, **changes):
        values = {"equipment_model": self.model, "source": "https://market.example.invalid/listing",
                  "source_title": "Anuncio", "price": "40000", "currency": "USD", "market": "US",
                  "price_type": "asking", "condition": "used", "retrieved_at": self.today,
                  "evidence": "Precio, condición y mercado documentados.", "configurations": {},
                  "review": MarketReference.Review.PENDING, "active": False}
        values.update(changes)
        return MarketReference.objects.create(**values)

    def action_admin(self, model, klass):
        instance = klass(model, admin.site)
        instance.message_user = Mock()
        return instance

    def test_approval_is_atomic_when_a_later_reference_is_invalid(self):
        valid = self.technical()
        invalid = self.technical(source="https://manufacturer.example.invalid/invalid", provenance=[])
        model_admin = self.action_admin(TechnicalReference, TechnicalReferenceAdmin)

        model_admin.approve_references(self.request(), TechnicalReference.objects.filter(pk__in=[valid.pk, invalid.pk]))

        valid.refresh_from_db()
        invalid.refresh_from_db()
        self.assertEqual((valid.review, valid.active, valid.reviewed_by_id), ("pending", False, None))
        self.assertEqual((invalid.review, invalid.active, invalid.reviewed_by_id), ("pending", False, None))
        self.assertFalse(AuditEvent.objects.filter(object_type="TechnicalReference").exists())
        message = model_admin.message_user.call_args.args[1]
        self.assertIn("No se aplicó ningún cambio", message)

    def test_approval_and_deactivation_are_audited_for_each_reference_type(self):
        technical = self.technical()
        market = self.market()
        technical_admin = self.action_admin(TechnicalReference, TechnicalReferenceAdmin)
        market_admin = self.action_admin(MarketReference, MarketReferenceAdmin)

        technical_admin.approve_references(self.request(), TechnicalReference.objects.filter(pk=technical.pk))
        market_admin.approve_references(self.request(), MarketReference.objects.filter(pk=market.pk))
        technical.refresh_from_db()
        market.refresh_from_db()
        self.assertEqual((technical.review, technical.active, technical.reviewed_by_id), ("approved", True, self.user.pk))
        self.assertEqual((market.review, market.active, market.reviewed_by_id), ("approved", True, self.user.pk))
        self.assertSetEqual(set(AuditEvent.objects.values_list("action", flat=True)),
                            {"technical_reference.approved", "market_reference.approved"})

        technical_admin.deactivate_references(self.request(), TechnicalReference.objects.filter(pk=technical.pk))
        market_admin.deactivate_references(self.request(), MarketReference.objects.filter(pk=market.pk))
        technical.refresh_from_db()
        market.refresh_from_db()
        self.assertFalse(technical.active)
        self.assertFalse(market.active)
        self.assertSetEqual(set(AuditEvent.objects.values_list("action", flat=True)), {
            "technical_reference.approved", "market_reference.approved",
            "technical_reference.deactivated", "market_reference.deactivated",
        })

    def test_deactivation_accepts_legacy_invalid_data_without_breaking_database_constraints(self):
        legacy = self.market(source="https://market.example.invalid/legacy", configurations=[])
        model_admin = self.action_admin(MarketReference, MarketReferenceAdmin)

        model_admin.deactivate_references(self.request(), MarketReference.objects.filter(pk=legacy.pk))

        legacy.refresh_from_db()
        self.assertEqual((legacy.review, legacy.active), ("pending", False))
        audit = AuditEvent.objects.get(object_type="MarketReference", object_id=str(legacy.pk))
        self.assertEqual(audit.action, "market_reference.deactivated")

    def test_actions_require_change_permission(self):
        request = self.request()
        technical_admin = TechnicalReferenceAdmin(TechnicalReference, admin.site)
        market_admin = MarketReferenceAdmin(MarketReference, admin.site)
        self.assertNotIn("approve_references", technical_admin.get_actions(request))
        self.assertNotIn("deactivate_references", market_admin.get_actions(request))

        technical_permission = Permission.objects.get(content_type__app_label="portal", codename="change_technicalreference")
        market_permission = Permission.objects.get(content_type__app_label="portal", codename="change_marketreference")
        self.user.user_permissions.add(technical_permission, market_permission)
        request = self.factory.post("/administracion/")
        request.user = User.objects.get(pk=self.user.pk)  # avoid Django's cached permission set from the first check
        self.assertIn("approve_references", technical_admin.get_actions(request))
        self.assertIn("deactivate_references", market_admin.get_actions(request))


class LatestMarketObservationsTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        self.brand = Brand.objects.create(name="Caterpillar")
        self.first_model = EquipmentModel.objects.create(brand=self.brand, name="320", category=self.category)
        self.second_model = EquipmentModel.objects.create(brand=self.brand, name="323", category=self.category)
        self.today = timezone.localdate()

    def observation(self, number, *, model=None, source=None, unit_key="", retrieved_at=None):
        return MarketReference.objects.create(
            equipment_model=model or self.first_model,
            source=source or f"https://market.example.invalid/listing/{number}", source_title=f"Anuncio {number}",
            price="40000", currency="USD", market="US", price_type="asking", condition="used",
            retrieved_at=retrieved_at or self.today, evidence="Precio, condición y mercado documentados.",
            unit_key=unit_key, review="approved", active=True,
        )

    def test_unit_key_is_normalized_per_model_and_newest_observation_wins(self):
        older = self.observation(1, unit_key=" Unit  42 ", retrieved_at=self.today - timedelta(days=1))
        newest = self.observation(2, unit_key="unit 42")
        other_model = self.observation(3, model=self.second_model, unit_key="UNIT 42")

        selected = latest_market_observations(MarketReference.objects.all(), today=self.today)

        self.assertEqual([row.pk for row in selected], [other_model.pk, newest.pk])
        self.assertEqual(market_unit_key(older), market_unit_key(newest))
        self.assertNotEqual(market_unit_key(newest), market_unit_key(other_model))

    def test_url_fallback_strips_tracking_but_preserves_meaningful_identifiers_and_excludes_future(self):
        older = self.observation(1, source="https://market.example.invalid/listing?id=one&color=red&utm_source=mail")
        newest = self.observation(2, source="https://MARKET.example.invalid/listing?color=red&id=one&gclid=tracking")
        different_id = self.observation(3, source="https://market.example.invalid/listing?id=two&fbclid=tracking")
        future = self.observation(4, source="https://market.example.invalid/future?id=future",
                                  retrieved_at=self.today + timedelta(days=1))

        selected = latest_market_observations(MarketReference.objects.all(), today=self.today)

        self.assertEqual([row.pk for row in selected], [different_id.pk, newest.pk])
        self.assertEqual(market_unit_key(older), market_unit_key(newest))
        self.assertNotEqual(market_unit_key(newest), market_unit_key(different_id))
        self.assertNotIn(future.pk, [row.pk for row in selected])

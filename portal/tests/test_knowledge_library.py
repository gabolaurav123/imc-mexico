from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from datetime import timedelta
from django.utils import timezone

from portal.models import Brand, Category, EquipmentModel, MarketReference, TechnicalReference, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TechnicalLibraryTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras")
        self.other_category = Category.objects.create(name="Cargadores", slug="cargadores")
        self.reference = self.make_reference(
            brand="Caterpillar", model="320", variant="GC", market="México",
            period_from=2019, period_to=2023,
            specs={"power": {"value": "110 kW", "evidence": "Potencia neta documentada."}},
        )
        brand = Brand.objects.create(name="Caterpillar")
        self.equipment_model = EquipmentModel.objects.create(brand=brand, name="320", category=self.category)
        self.reference.equipment_model = self.equipment_model
        self.reference.save()
        self.staff = User.objects.create_user(email="technical-reader@example.invalid", is_staff=True)
        self.no_permission = User.objects.create_user(email="technical-no-access@example.invalid", is_staff=True)

    def make_reference(self, **overrides):
        values = {
            "category": self.category,
            "brand": "Marca", "model": "Modelo", "source": "https://manufacturer.example.invalid/manual.pdf",
            "source_title": "Manual técnico privado", "retrieved_at": "2026-09-01",
            "review": TechnicalReference.Review.APPROVED, "active": True,
        }
        values.update(overrides)
        return TechnicalReference.objects.create(**values)

    def login_with_permission(self, user=None):
        user = user or self.staff
        user.user_permissions.add(Permission.objects.get(content_type__app_label="portal", codename="view_technicalreference"))
        self.client.force_login(user)
        device, _ = TOTPDevice.objects.get_or_create(user=user, name="IMC", defaults={"confirmed": True})
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def test_library_requires_the_model_view_permission_and_is_not_public(self):
        self.assertEqual(self.client.get("/operaciones/base-tecnica/").status_code, 403)
        self.client.force_login(self.no_permission)
        device = TOTPDevice.objects.create(user=self.no_permission, name="IMC", confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        self.assertEqual(self.client.get("/operaciones/base-tecnica/").status_code, 403)

    def test_search_filters_and_coverage_are_bounded_to_the_result_set(self):
        self.make_reference(category=self.other_category, brand="Volvo", model="L120", market="Chile",
                            review=TechnicalReference.Review.PENDING, active=False)
        self.login_with_permission()
        response = self.client.get("/operaciones/base-tecnica/", {"q": "caterpillar", "status": "approved", "market": "México"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["references"]), [self.reference])
        self.assertEqual(response.context["coverage"], {"references": 1, "categories": 1, "brands": 1, "models": 1})
        self.assertContains(response, "Excavadoras")
        self.assertNotContains(response, "Volvo")

    def test_detail_shows_human_readable_specs_and_the_internal_source_to_authorized_staff(self):
        self.login_with_permission()
        response = self.client.get(f"/operaciones/base-tecnica/{self.reference.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2019 – 2023")
        self.assertContains(response, "Potencia")
        self.assertContains(response, "110 kW")
        self.assertContains(response, self.reference.source_title)
        self.assertContains(response, self.reference.source)
        self.assertContains(response, "Visible sólo para personal autorizado")
        self.assertContains(response, "no las garantiza")

    def test_non_http_source_is_never_rendered_as_a_link(self):
        reference = self.make_reference(source="javascript:alert(1)", source_title="Enlace inválido")
        self.login_with_permission()
        response = self.client.get(f"/operaciones/base-tecnica/{reference.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La URL registrada no es un enlace HTTP(S) válido.")
        self.assertNotContains(response, 'href="javascript:alert(1)"')

    def test_pagination_uses_twenty_references_per_page(self):
        for number in range(21):
            self.make_reference(brand="Komatsu", model=f"PC-{number}")
        self.login_with_permission()
        response = self.client.get("/operaciones/base-tecnica/", {"page": 2})
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(len(response.context["references"]), 2)

    def test_superuser_has_library_access(self):
        superuser = User.objects.create_superuser(email="technical-super@example.invalid")
        self.client.force_login(superuser)
        device = TOTPDevice.objects.create(user=superuser, name="IMC", confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        self.assertEqual(self.client.get("/operaciones/base-tecnica/").status_code, 200)

    def test_market_ranges_are_separate_from_specs_and_require_two_approved_listings(self):
        values = {"equipment_model": self.equipment_model, "currency": "USD", "market": "NL",
                  "price_type": "asking", "condition": "used", "retrieved_at": "2026-09-01",
                  "evidence": "Precio y condición visibles en el anuncio.", "review": "approved", "active": True}
        MarketReference.objects.create(**values, source="https://market.example.invalid/listing-1", source_title="Anuncio 1", price="45000.00")
        self.login_with_permission()
        response = self.client.get(f"/operaciones/base-tecnica/{self.reference.pk}/")
        self.assertContains(response, "Aún no hay al menos dos anuncios aprobados")
        later_values = {**values, "retrieved_at": "2026-09-09"}
        MarketReference.objects.create(**later_values, source="https://market.example.invalid/listing-2", source_title="Anuncio 2", price="50000.00")
        response = self.client.get(f"/operaciones/base-tecnica/{self.reference.pk}/")
        self.assertContains(response, "45000")
        self.assertContains(response, "50000")
        self.assertContains(response, "Precio anunciado")
        self.assertContains(response, "Usada")
        self.assertContains(response, "Anuncio 1")

    def test_market_reference_is_pending_and_inactive_by_default_and_rejects_bad_configuration(self):
        reference = MarketReference(equipment_model=self.equipment_model, source="https://market.example.invalid/pending",
                                    source_title="Anuncio pendiente", price="1", currency="MXN", market="MX",
                                    retrieved_at="2026-09-01", evidence="Importado para revisar.")
        reference.full_clean(); reference.save()
        self.assertEqual(reference.review, MarketReference.Review.PENDING)
        self.assertFalse(reference.active)
        reference.configurations = []
        with self.assertRaises(ValidationError): reference.full_clean()

    def market_observation(self, suffix, **overrides):
        values = {"equipment_model": self.equipment_model, "currency": "USD", "market": "US",
                  "price_type": "asking", "condition": "used", "retrieved_at": timezone.localdate(),
                  "evidence": "Precio y condición visibles en el anuncio.", "review": "approved", "active": True,
                  "source": f"https://market.example.invalid/{suffix}", "source_title": suffix, "price": "45000.00"}
        values.update(overrides)
        return MarketReference.objects.create(**values)

    def test_availability_filters_and_market_summary_include_only_dated_approved_observations(self):
        self.make_reference(brand="Volvo", model="EC140C")
        self.market_observation("first", unit_key="Unit 1")
        self.market_observation("second", unit_key="Unit 2", price="50000.00")
        self.market_observation("pending", review="pending", active=False, price="1.00")
        self.market_observation("future", retrieved_at=timezone.localdate() + timedelta(days=1), price="2.00")
        self.login_with_permission()
        response = self.client.get("/operaciones/base-tecnica/", {"availability": "with_market"})
        self.assertEqual(list(response.context["references"]), [self.reference])
        self.assertEqual(response.context["completeness"], {"periods": 1, "market_models": 1})
        summary = response.context["references"][0].market_overview["ranges"][0]
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["minimum"], 45000)
        self.assertEqual(summary["median"], 47500)
        response = self.client.get("/operaciones/base-tecnica/", {"availability": "without_market"})
        self.assertEqual([row.model for row in response.context["references"]], ["EC140C"])
        response = self.client.get("/operaciones/base-tecnica/", {"availability": "without_period"})
        self.assertEqual([row.model for row in response.context["references"]], ["EC140C"])
        response = self.client.get("/operaciones/base-tecnica/", {"category": "9" * 100})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["category"], "")

    def test_latest_observation_supersedes_older_condition_and_does_not_create_a_false_range(self):
        self.market_observation("old", unit_key="Stock 1", retrieved_at=timezone.localdate() - timedelta(days=1))
        self.market_observation("new", unit_key="  STOCK   1 ", condition="unknown", price="60000.00")
        self.market_observation("independent", unit_key="Stock 2")
        self.login_with_permission()
        response = self.client.get(f"/operaciones/base-tecnica/{self.reference.pk}/")
        self.assertEqual(len(response.context["market_listings"]), 2)
        self.assertEqual(response.context["market_ranges"], [])
        self.assertNotContains(response, 'href="https://market.example.invalid/old"')

    def test_related_documentation_keeps_variant_scope_and_excludes_inactive_references(self):
        sibling = self.make_reference(brand="Caterpillar", model="320", equipment_model=self.equipment_model,
            variant="GC", market="US", source="https://manufacturer.example.invalid/us-320",
            specs={"weight": {"value": "22000 kg", "evidence": "Peso operativo documentado."}})
        self.make_reference(brand="Caterpillar", model="320", equipment_model=self.equipment_model,
            active=False, source="https://manufacturer.example.invalid/inactive", source_title="Documento inactivo")
        self.login_with_permission()
        response = self.client.get(f"/operaciones/base-tecnica/{self.reference.pk}/")
        self.assertEqual([row["reference"] for row in response.context["related_references"]], [sibling])
        self.assertContains(response, "Más documentación del modelo")
        self.assertContains(response, "22000 kg")
        self.assertContains(response, "US")
        self.assertNotContains(response, "Documento inactivo")

    def test_market_links_are_safe_and_sold_prices_are_labelled_correctly(self):
        self.market_observation("unsafe", source="javascript:alert(1)", price_type="sold")
        self.login_with_permission()
        response = self.client.get(f"/operaciones/base-tecnica/{self.reference.pk}/")
        self.assertNotContains(response, 'href="javascript:alert(1)"')
        self.assertContains(response, "Precio de venta")

    def test_market_summary_does_not_mix_different_documented_configurations(self):
        self.market_observation("diesel", configurations={"fuel": "Diesel"})
        self.market_observation("lpg", configurations={"fuel": "LPG"})
        self.login_with_permission()
        response = self.client.get(f"/operaciones/base-tecnica/{self.reference.pk}/")
        self.assertEqual(response.context["market_ranges"], [])

    def test_database_constraints_block_invalid_bulk_updates_that_bypass_model_clean(self):
        observation = self.market_observation("valid")
        for model, pk, values in (
            (TechnicalReference, self.reference.pk, {"review": "pending", "active": True}),
            (TechnicalReference, self.reference.pk, {"period_from": 2020, "period_to": 2010}),
            (MarketReference, observation.pk, {"review": "pending", "active": True}),
            (MarketReference, observation.pk, {"price": 0}),
        ):
            with self.subTest(model=model.__name__, values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.filter(pk=pk).update(**values)

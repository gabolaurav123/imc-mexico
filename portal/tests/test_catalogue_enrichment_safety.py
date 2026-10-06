"""Server-side guards for the no-media catalogue path."""
from datetime import date

from django.test import TestCase

from portal.catalogue_intake import catalogue_reference_ready
from portal.models import Brand, Category, EquipmentModel, Machine, TechnicalReference, User


class CatalogueEnrichmentSafetyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="catalogue-safety@example.invalid", password=None,
            phone="+525512345678", contact_preference="whatsapp")
        self.category = Category.objects.create(name="Excavadoras", slug="catalogue-safety", active=True)
        self.brand = Brand.objects.create(name="Caterpillar", active=True)
        self.model = EquipmentModel.objects.create(
            brand=self.brand, category=self.category, name="320", active=True)
        TechnicalReference.objects.create(
            category=self.category, equipment_model=self.model, brand="Caterpillar", model="320",
            source="https://manufacturer.example/320", source_title="320 specification sheet",
            retrieved_at=date(2026, 10, 6), review=TechnicalReference.Review.APPROVED, active=True,
            specs={"power": {"value": "121 kW", "evidence": "Net power: 121 kW."}})
        self.client.force_login(self.owner)

    def test_start_form_uses_only_the_selected_approved_model(self):
        response = self.client.post("/panel/maquinarias/nueva/", {
            "category": self.category.pk,
            "entry_mode": "catalogue",
            "catalogue_model": self.model.pk,
            # Hidden controls and free-text fields cannot replace an approved
            # catalogue identity or its initial description on the server.
            "brand": "Injected brand",
            "model": "Injected model",
            "description": "Injected description",
            "catalogue_enrichment": "1",
        })
        self.assertEqual(response.status_code, 302)
        machine = Machine.objects.get(owner=self.owner)
        self.assertEqual(machine.data["brand"], "Caterpillar")
        self.assertEqual(machine.data["model"], "320")
        self.assertNotIn("Injected", machine.data["description"])
        self.assertIn("entrada=catalogue", response.url)
        self.assertIn("completar=1", response.url)

    def test_start_form_rejects_a_hidden_invalid_model_without_creating_a_draft(self):
        response = self.client.post("/panel/maquinarias/nueva/", {
            "category": self.category.pk,
            "entry_mode": "catalogue",
            "catalogue_model": "999999",
            "catalogue_enrichment": "1",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Machine.objects.filter(owner=self.owner).count(), 0)

    def test_ready_check_does_not_accept_a_reference_from_another_category(self):
        other = Category.objects.create(name="Cargadores", slug="catalogue-safety-loaders", active=True)
        self.model.technical_references.update(active=False)
        wrong = TechnicalReference.objects.create(
            category=other, equipment_model=self.model, brand="Caterpillar", model="320",
            source="https://manufacturer.example/wrong-category", source_title="Wrong category",
            retrieved_at=date(2026, 10, 6), review=TechnicalReference.Review.APPROVED, active=True,
            specs={})
        machine = Machine.objects.create(owner=self.owner, category=self.category,
            data={"brand": "Caterpillar", "model": "320"},
            provenance={"model": {"source": "web_model", "scope": "model", "basis": "catalogue_intake",
                                   "source_url": wrong.source}})
        self.assertFalse(catalogue_reference_ready(machine))

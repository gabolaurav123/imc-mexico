"""Compatibility limits for the old authenticated catalogue reader."""
from datetime import date

from django.test import TestCase

from portal.models import Brand, Category, EquipmentModel, TechnicalReference, User


class LegacyCatalogueApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="legacy-catalogue@example.invalid", password=None)
        self.category = Category.objects.create(name="Excavadoras", slug="legacy-catalogue", active=True)
        self.brand = Brand.objects.create(name="Marca", active=True)
        for number in range(30):
            model = EquipmentModel.objects.create(brand=self.brand, category=self.category, name=f"M{number:02}", active=True)
            TechnicalReference.objects.create(category=self.category, equipment_model=model,
                brand=self.brand.name, model=model.name, source=f"https://example.invalid/{number}",
                source_title=f"Ficha {number}", retrieved_at=date(2026, 10, 6), specs={},
                review=TechnicalReference.Review.APPROVED, active=True)
        self.client.force_login(self.user)

    def test_get_remains_compatible_but_is_small_and_paged(self):
        first = self.client.get('/api/maquinarias/catalogo/', {'category': self.category.pk})
        self.assertEqual(first.status_code, 200, first.content)
        data = first.json()
        self.assertEqual(len(data['models']), 25)
        self.assertEqual(set(data['models'][0]), {'id', 'category', 'brand', 'name'})
        self.assertEqual(data['total'], 30)
        self.assertTrue(data['has_more'])
        second = self.client.get('/api/maquinarias/catalogo/', {'category': self.category.pk, 'page': 2})
        self.assertEqual(len(second.json()['models']), 5)
        self.assertFalse(second.json()['has_more'])

    def test_get_reuses_discovery_page_validation(self):
        response = self.client.get('/api/maquinarias/catalogo/', {'page': '0'})
        self.assertEqual(response.status_code, 400)

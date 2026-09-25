from io import StringIO
import json

from django.core.management import call_command
from django.test import TestCase,override_settings

from portal.models import Asset,Brand,Category,EquipmentModel,Machine,MachineVersion,Publication,User
from portal.services import DATA_FIELDS,save_draft


@override_settings(SECURE_SSL_REDIRECT=False,
    STORAGES={'default':{'BACKEND':'portal.storage.PrivateStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class CatalogReferenceTests(TestCase):
    def seed(self):
        call_command('seed',stdout=StringIO())

    def test_reference_seed_adds_suggestions_without_inventory_or_technical_data(self):
        self.seed()
        counts = (Brand.objects.count(), EquipmentModel.objects.count())
        self.seed()
        self.assertEqual((Brand.objects.count(), EquipmentModel.objects.count()), counts)
        self.assertGreaterEqual(Brand.objects.count(),9)
        self.assertGreaterEqual(EquipmentModel.objects.count(),9)
        # The expanded IMC taxonomy groups the source types into 44 canonical
        # equipment families plus the free-text "Otra maquinaria" category.
        self.assertEqual(Category.objects.count(),45)
        for category in Category.objects.all():self.assertLessEqual(set(category.fields),DATA_FIELDS)
        for model in (Machine,MachineVersion,Asset,Publication,User):self.assertEqual(model.objects.count(),0)

    def test_seed_preserves_case_insensitive_custom_catalog_and_disabled_entries(self):
        category=Category.objects.create(slug='plataformas-elevadoras',name='Nombre elegido por IMC',fields=['engine'],active=False)
        brand=Brand.objects.create(name='cASE',active=False)
        model=EquipmentModel.objects.create(brand=brand,name='845 b',category=category,active=False)
        self.seed();self.seed()
        category.refresh_from_db();brand.refresh_from_db();model.refresh_from_db()
        self.assertEqual((category.name,category.fields,category.active),('Nombre elegido por IMC',['engine'],False))
        self.assertEqual((brand.name,brand.active),('cASE',False))
        self.assertEqual((model.name,model.category_id,model.active),('845 b',category.pk,False))
        self.assertEqual(Brand.objects.filter(name__iexact='Case').count(),1)
        self.assertEqual(EquipmentModel.objects.filter(brand=brand,name__iexact='845 B').count(),1)

    def test_wizard_uses_active_suggestions_and_preserves_free_text(self):
        self.seed()
        user=User.objects.create_user(email='catalog-test@example.invalid',password=None)
        machine=Machine.objects.create(owner=user,data={'brand':'Mi marca personalizada','model':'Modelo declarado / variante'})
        Brand.objects.filter(name='Tadano').update(active=False)
        EquipmentModel.objects.filter(name='320DL').update(active=False)
        Category.objects.filter(slug='plataformas-elevadoras').update(active=False)
        self.client.force_login(user)
        response=self.client.get(f'/panel/maquinarias/{machine.pk}/')
        self.assertEqual(response.status_code,200)
        suggestions=response.context['catalog_models_json']
        self.assertFalse(any(item['name'] in {'GR150','320DL','E450AJ'} for item in suggestions))
        self.assertTrue(any(item['name']=='PC200 L' for item in suggestions))
        self.assertNotContains(response,'value="Tadano"')
        self.assertContains(response,'value="Mi marca personalizada"')
        self.assertContains(response,'value="Modelo declarado / variante"')
        self.assertTrue(all(set(item)=={'name','brand','category'} for item in suggestions))
        machine.refresh_from_db()
        self.assertEqual(machine.data,{'brand':'Mi marca personalizada','model':'Modelo declarado / variante'})

    def test_category_change_and_unlisted_values_do_not_fill_model_specs_or_serial(self):
        self.seed()
        user=User.objects.create_user(email='catalog-free@example.invalid',password=None)
        machine=Machine.objects.create(owner=user,data={'brand':'Marca no catalogada','model':'Otro modelo','hours':None,'serial':None})
        category=Category.objects.get(slug='zanjadoras')
        machine=save_draft(machine,user,{'category':category.pk},machine.revision)
        self.assertEqual(machine.data,{'brand':'Marca no catalogada','model':'Otro modelo','hours':None,'serial':None})
        machine=save_draft(machine,user,{'data':{'brand':'JLG','model':'E450AJ'}},machine.revision)
        self.assertIsNone(machine.data['hours']);self.assertIsNone(machine.data['serial'])
        self.assertNotIn('year',machine.data);self.assertNotIn('price',machine.data)
        self.assertNotIn('capacity',machine.data);self.assertNotIn('web_reference',machine.data)

"""The publishing editor offers two conditions and validates the same API contract."""
import json
import re

from django.test import TestCase, override_settings

from portal.models import Category, Machine, User
from portal.services import _family_market_matches_condition


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND': 'portal.storage.PrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class MachineConditionChoicesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='condition-contract@example.invalid')
        self.category = Category.objects.create(name='Pavimentadoras', slug='pavimentadoras')
        self.machine = Machine.objects.create(owner=self.user, category=self.category,
                                               data={'serial': 'QA-PAVER-12345'})
        self.client.force_login(self.user)

    def save(self, condition):
        self.machine.refresh_from_db()
        return self.client.post(f'/api/maquinarias/{self.machine.pk}/guardar/',
            json.dumps({'revision': self.machine.revision, 'data': {'condition': condition}}),
            content_type='application/json')

    def test_editor_only_offers_new_used_and_optional_empty(self):
        response = self.client.get(f'/panel/maquinarias/{self.machine.pk}/')
        self.assertEqual(response.status_code, 200)
        select = re.search(r'<select\b[^>]*\bid="condition"[^>]*>(.*?)</select>', response.content.decode(), re.S)
        self.assertIsNotNone(select)
        self.assertEqual(re.findall(r'<option\b[^>]*\bvalue="([^"]*)"', select.group(1)), ['', 'new', 'used'])

    def test_api_accepts_new_used_empty_and_legacy_language_aliases(self):
        for value, expected in [('new', 'new'), ('used', 'used'), ('', ''), ('Nueva', 'new'), ('Usada', 'used')]:
            with self.subTest(value=value):
                response = self.save(value)
                self.assertEqual(response.status_code, 200, response.content)
                self.machine.refresh_from_db()
                self.assertEqual(self.machine.data.get('condition', ''), expected)

    def test_removed_options_cannot_be_introduced_through_api(self):
        for value in ['refurbished', 'for_repair', 'Reacondicionada', 'Para reparación']:
            with self.subTest(value=value):
                revision = self.machine.revision
                response = self.save(value)
                self.assertEqual(response.status_code, 400, response.content)
                self.machine.refresh_from_db()
                self.assertEqual(self.machine.revision, revision)
                self.assertNotIn('condition', self.machine.data)

    def test_existing_historical_condition_can_be_saved_unchanged(self):
        self.machine.data['condition'] = 'refurbished'
        self.machine.save(update_fields=['data'])
        self.assertEqual(self.save('refurbished').status_code, 200)
        self.assertEqual(self.save('used').status_code, 200)

    def test_used_reference_cannot_price_new_machine_with_canonical_choice(self):
        manifest = {'comparables': [{'condition': 'used'}, {'condition': 'used'}]}
        self.assertTrue(_family_market_matches_condition({'condition': 'used'}, manifest))
        self.assertFalse(_family_market_matches_condition({'condition': 'new'}, manifest))


"""The service entry survives registration/login without starting paid work."""
from django.test import TestCase, override_settings
from portal.models import AnalysisJob, Machine, Notification, PlatformSettings, Publication, User


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND': 'portal.storage.PrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PublishEntryTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.create(pk=1, registration_open=True)

    def registration(self, **changes):
        data = {'first_name': 'Ana', 'last_name': 'Prueba', 'email': 'service-entry@example.invalid',
                'phone_prefix': '+591', 'phone_national': '71234567', 'company': '',
                'contact_preference': 'whatsapp', 'password1': 'Entry-test-password-237!',
                'password2': 'Entry-test-password-237!', 'terms': 'on',
                'next': '/panel/maquinarias/nueva/'}
        return {**data, **changes}

    def test_home_has_a_direct_non_javascript_entry_and_explains_review(self):
        response = self.client.get('/')
        self.assertContains(response, 'Publica tu maquinaria')
        self.assertContains(response, 'href="/publicar/"')
        self.assertContains(response, 'Enviar la ficha no la publica de inmediato')
        entry = self.client.get('/publicar/', follow=True)
        self.assertEqual(entry.status_code, 200)
        self.assertContains(entry, 'name="next" value="/panel/maquinarias/nueva/"')
        self.assertContains(entry, '/iniciar-sesion/?next=/panel/maquinarias/nueva/')
        for model in (User, Machine, AnalysisJob, Notification, Publication):
            self.assertFalse(model.objects.exists())
        self.assertEqual(self.client.post('/publicar/').status_code, 405)

    def test_registration_returns_to_photos_and_only_post_creates_private_draft(self):
        response = self.client.post('/registro/', self.registration())
        self.assertRedirects(response, '/panel/maquinarias/nueva/')
        user = User.objects.get(email='service-entry@example.invalid')
        self.assertEqual((user.first_name, user.last_name, user.phone), ('Ana', 'Prueba', '+59171234567'))
        self.assertFalse(user.is_staff or user.is_superuser or user.email_verified)
        self.assertEqual(user.advertiser_status, 'pending')
        self.assertFalse(Machine.objects.exists())
        self.assertRedirects(self.client.get('/publicar/'), '/panel/maquinarias/nueva/')
        response = self.client.post('/panel/maquinarias/nueva/')
        machine = Machine.objects.get(owner=user)
        self.assertRedirects(response, f'/panel/maquinarias/{machine.pk}/')
        self.assertEqual(machine.status, 'draft')
        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(Publication.objects.exists())

    def test_login_and_error_retry_keep_publication_destination(self):
        user = User.objects.create_user(email='return@example.invalid', password='Entry-test-password-237!')
        response = self.client.get('/iniciar-sesion/?next=/panel/maquinarias/nueva/')
        self.assertContains(response, '/registro/?next=/panel/maquinarias/nueva/')
        response = self.client.post('/iniciar-sesion/', {'username': user.email, 'password': 'wrong', 'next': '/panel/maquinarias/nueva/'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="next" value="/panel/maquinarias/nueva/"')
        response = self.client.post('/iniciar-sesion/', {'username': user.email, 'password': 'Entry-test-password-237!', 'next': '/panel/maquinarias/nueva/'})
        self.assertRedirects(response, '/panel/maquinarias/nueva/')
        self.assertFalse(Machine.objects.exists())

    def test_registration_does_not_accept_an_external_return_url(self):
        response = self.client.post('/registro/', self.registration(next='https://outside.example/'))
        self.assertRedirects(response, '/panel/')


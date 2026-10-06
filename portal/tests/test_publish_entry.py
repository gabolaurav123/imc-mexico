"""The service entry survives registration/login without starting paid work."""
from django.test import TestCase, override_settings
from portal.models import AnalysisJob, Category, GuestDraft, Machine, Notification, PlatformSettings, Publication, User


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND': 'portal.storage.PrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PublishEntryTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.create(pk=1, registration_open=True)
        self.category = Category.objects.create(name="Excavadoras", slug="entry-excavators")

    def registration(self, **changes):
        data = {'first_name': 'Ana', 'last_name': 'Prueba', 'email': 'service-entry@example.invalid',
                'phone_prefix': '+591', 'phone_national': '71234567', 'company': '',
                'contact_preference': 'whatsapp', 'password1': 'Entry-test-password-237!',
                'password2': 'Entry-test-password-237!', 'terms': 'on',
                'next': '/panel/maquinarias/nueva/'}
        return {**data, **changes}

    def test_home_has_a_direct_non_javascript_entry_and_explains_review(self):
        response = self.client.get('/')
        self.assertContains(response, 'Publicar maquinaria')
        self.assertContains(response, 'href="/publicar/"')
        self.assertContains(response, 'IMC México revisa y autoriza la publicación en el catálogo')
        entry = self.client.get('/publicar/')
        self.assertRedirects(entry, '/registro/?next=/panel/maquinarias/nueva/')
        for model in (User, Machine, AnalysisJob, Notification, Publication):
            self.assertFalse(model.objects.exists())
        response = self.client.post('/publicar/', {'brand': 'CAT', 'model': '320'})
        self.assertRedirects(response, '/registro/?next=/panel/maquinarias/nueva/')
        self.assertFalse(GuestDraft.objects.exists())
        self.assertFalse(Machine.objects.exists())

    def test_registration_returns_to_photos_and_only_post_creates_private_draft(self):
        response = self.client.post('/registro/', self.registration())
        self.assertRedirects(response, '/panel/maquinarias/nueva/')
        user = User.objects.get(email='service-entry@example.invalid')
        self.assertEqual((user.first_name, user.last_name, user.phone), ('Ana', 'Prueba', '+59171234567'))
        self.assertFalse(user.is_staff or user.is_superuser or user.email_verified)
        self.assertEqual(user.advertiser_status, 'pending')
        self.assertFalse(Machine.objects.exists())
        self.assertRedirects(self.client.get('/publicar/'), '/panel/maquinarias/nueva/')
        response = self.client.post('/panel/maquinarias/nueva/', {'category': self.category.pk})
        machine = Machine.objects.get(owner=user)
        self.assertRedirects(response, f'/panel/maquinarias/{machine.pk}/')
        self.assertEqual(machine.status, 'draft')
        self.assertFalse(AnalysisJob.objects.exists())
        self.assertFalse(Publication.objects.exists())

    def test_login_and_error_retry_keep_publication_destination(self):
        user = User.objects.create_user(email='return@example.invalid', password='Entry-test-password-237!', phone='+525512345678')
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

    def test_category_entry_survives_registration_and_does_not_create_paid_work(self):
        from urllib.parse import parse_qs, urlsplit
        target = f'/panel/maquinarias/nueva/?tipo={self.category.slug}'
        entry = self.client.get('/publicar/', {'tipo': self.category.slug})
        self.assertEqual(parse_qs(urlsplit(entry.url).query)['next'], [target])
        page = self.client.get(entry.url)
        self.assertEqual(page.context['publication_next'], target)
        self.assertContains(page, f'name="next" value="{target}"')
        sign_in = self.client.get('/iniciar-sesion/', {'next': target})
        self.assertEqual(sign_in.context['publication_next'], target)
        response = self.client.post('/registro/', self.registration(next=target))
        self.assertRedirects(response, target)
        page = self.client.get(target)
        self.assertEqual(page.context['initial_category_slug'], self.category.slug)
        self.assertContains(page, f'data-initial-category="{self.category.slug}"')
        self.assertFalse(Machine.objects.exists())
        self.assertFalse(AnalysisJob.objects.exists())

    def test_category_entry_survives_incomplete_contact(self):
        from urllib.parse import parse_qs, urlsplit
        user = User.objects.create_user(email='category-contact@example.invalid')
        self.client.force_login(user)
        target = f'/panel/maquinarias/nueva/?tipo={self.category.slug}'
        response = self.client.get(target)
        self.assertEqual(urlsplit(response.url).path, '/panel/perfil/')
        self.assertEqual(parse_qs(urlsplit(response.url).query)['next'], [target])
        self.assertFalse(AnalysisJob.objects.exists())

    def test_unknown_or_inactive_category_cannot_preselect_or_redirect(self):
        user = User.objects.create_user(email='category-safe@example.invalid', phone='+525512345678')
        self.client.force_login(user)
        self.category.active = False
        self.category.save(update_fields=['active'])
        for slug in (self.category.slug, 'missing', 'https://outside.example/'):
            with self.subTest(slug=slug):
                response = self.client.get('/publicar/', {'tipo': slug})
                self.assertRedirects(response, '/panel/maquinarias/nueva/')
                page = self.client.get('/panel/maquinarias/nueva/', {'tipo': slug})
                self.assertEqual(page.context['initial_category_slug'], '')
        self.assertFalse(AnalysisJob.objects.exists())

    def test_home_category_shortcuts_only_include_active_categories(self):
        Category.objects.create(name='Compactadores', slug='compactadores', active=True)
        Category.objects.create(name='Cargadores', slug='cargadores', active=False)
        page = self.client.get('/')
        self.assertContains(page, 'href="/publicar/?tipo=compactadores"')
        self.assertNotContains(page, 'href="/publicar/?tipo=cargadores"')

    def test_existing_account_completes_contact_before_new_machine(self):
        user = User.objects.create_user(email='contact-missing@example.invalid')
        self.client.force_login(user)
        self.assertRedirects(self.client.get('/panel/maquinarias/nueva/'), '/panel/perfil/?next=/panel/maquinarias/nueva/')
        page = self.client.get('/panel/perfil/?next=/panel/maquinarias/nueva/')
        self.assertContains(page, user.email)
        response = self.client.post('/panel/perfil/', {'first_name':'Ana', 'last_name':'Prueba',
            'phone_prefix':'+591', 'phone_national':'71234567', 'contact_preference':'whatsapp',
            'email':'attacker@example.invalid', 'next':'/panel/maquinarias/nueva/'})
        self.assertRedirects(response, '/panel/maquinarias/nueva/')
        user.refresh_from_db()
        self.assertEqual(user.email, 'contact-missing@example.invalid')
        self.assertEqual(user.phone, '+59171234567')
        self.assertEqual(user.contact_preference, 'whatsapp')
        self.assertFalse(Machine.objects.exists())

    def test_new_machine_can_investigate_serial_without_type_or_losing_existing_drafts(self):
        user = User.objects.create_user(email='contact-ready@example.invalid', phone='+525512345678')
        existing = Machine.objects.create(owner=user, data={'serial':'KEEP-123'})
        self.client.force_login(user)
        response = self.client.post('/panel/maquinarias/nueva/', {'category':'unsure', 'serial':'CAT320D12345', 'entry_mode':'serial'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Machine.objects.count(), 2)
        new = Machine.objects.exclude(pk=existing.pk).get()
        self.assertIsNone(new.category_id)
        self.assertEqual(new.data['serial'], 'CAT320D12345')
        self.assertEqual(Machine.objects.get(pk=existing.pk).data, {'serial':'KEEP-123'})

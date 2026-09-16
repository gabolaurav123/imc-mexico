"""Only authenticated activity becomes short-lived, privileged security history."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import DatabaseError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from portal.access_tracking import SESSION_MARKER, record_access
from portal.models import AccountAccess, SiteContent, User


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'],
    STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AccountAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='access-owner@example.invalid', password='Synthetic-access-87543!')
        self.staff = User.objects.create_user(email='access-staff@example.invalid', is_staff=True)

    def request(self, **meta):
        request = RequestFactory().get('/panel/?token=DO-NOT-RECORD', **meta)
        request.session = {}
        return request

    def test_real_successful_login_records_safe_network_fields_but_not_secrets(self):
        response = self.client.post('/iniciar-sesion/', {'username': self.owner.email, 'password': 'Synthetic-access-87543!'},
            REMOTE_ADDR='10.0.0.5', HTTP_X_FORWARDED_FOR='198.51.100.6, 10.0.0.6',
            HTTP_USER_AGENT='Mozilla mobile SECRET-UA', HTTP_REFERER='https://example.invalid/PRIVATE')
        self.assertEqual(response.status_code, 302)
        entry = AccountAccess.objects.get(user=self.owner)
        self.assertEqual((entry.event, entry.connection_ip, entry.forwarded_ip, entry.device),
                         ('login', '10.0.0.5', '198.51.100.6', 'mobile'))
        self.assertTrue(timedelta(days=89) < entry.expires_at - entry.created_at < timedelta(days=91))
        self.assertNotIn('SECRET', str(entry.__dict__))
        self.assertNotIn('PRIVATE', str(entry.__dict__))
        self.assertNotIn('password', str(entry.__dict__))
        self.client.get('/panel/')
        self.client.get('/panel/perfil/')
        self.assertEqual(AccountAccess.objects.filter(user=self.owner).count(), 1)

    def test_anonymous_and_failed_login_do_not_create_identified_history(self):
        self.client.get('/')
        self.client.post('/iniciar-sesion/', {'username': self.owner.email, 'password': 'wrong'})
        self.assertFalse(AccountAccess.objects.exists())

    def test_security_notice_is_visible_alongside_custom_privacy_copy_without_tracking_anonymous(self):
        SiteContent.objects.create(key='privacidad', title='Privacidad del portal', body='Texto propio conservado', active=True)
        response = self.client.get('/privacidad/')
        self.assertContains(response, 'Texto propio conservado')
        self.assertContains(response, 'Seguridad de cuentas y accesos')
        self.assertContains(response, '90 días')
        self.assertContains(response, 'dato no verificado')
        self.assertFalse(AccountAccess.objects.exists())

    def test_existing_session_is_observed_once_per_day_without_claiming_new_login(self):
        self.client.force_login(self.owner)
        AccountAccess.objects.all().delete()
        session = self.client.session
        session.pop(SESSION_MARKER, None)
        session.save()
        self.client.get('/panel/', REMOTE_ADDR='2001:db8::1')
        self.client.get('/panel/perfil/', REMOTE_ADDR='2001:db8::1')
        self.assertEqual(list(AccountAccess.objects.values_list('event', flat=True)), ['session'])
        session = self.client.session
        session[SESSION_MARKER] = (timezone.now() - timedelta(days=2)).timestamp()
        session.save()
        self.client.get('/panel/')
        self.assertEqual(AccountAccess.objects.count(), 2)

    def test_invalid_headers_cannot_override_connection_or_store_arbitrary_text(self):
        for forwarded in ('<script>1</script>', '198.51.100.4, not-an-ip', 'x' * 513, 'fe80::1%zone'):
            with self.subTest(forwarded=forwarded):
                entry = record_access(self.request(REMOTE_ADDR='203.0.113.5', HTTP_X_FORWARDED_FOR=forwarded), self.owner, 'login')
                self.assertEqual(entry.connection_ip, '203.0.113.5')
                self.assertIsNone(entry.forwarded_ip)
        entry = record_access(self.request(REMOTE_ADDR='bad-address', HTTP_X_FORWARDED_FOR='198.51.100.9'), self.owner, 'session')
        self.assertIsNone(entry.connection_ip)
        self.assertEqual(entry.forwarded_ip, '198.51.100.9')

    @override_settings(STAFF_MFA_REQUIRED=False)
    def test_history_requires_explicit_permission_and_cannot_be_edited(self):
        entry = record_access(self.request(), self.owner, 'login')
        path = '/admin/portal/accountaccess/'
        self.client.force_login(self.owner)
        self.assertNotEqual(self.client.get(path).status_code, 200)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.staff.user_permissions.add(Permission.objects.get(codename='view_accountaccess'))
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sin verificar')
        self.assertEqual(self.client.get(path + 'add/').status_code, 403)
        self.assertEqual(self.client.post(path + f'{entry.pk}/change/', {'connection_ip': '1.1.1.1'}).status_code, 403)
        self.assertEqual(self.client.post(path + f'{entry.pk}/delete/', {'post': 'yes'}).status_code, 403)
        entry.refresh_from_db()
        self.assertNotEqual(entry.connection_ip, '1.1.1.1')

    def test_expired_records_are_purged_and_retention_is_report_only_by_default(self):
        expired = record_access(self.request(), self.owner, 'login')
        AccountAccess.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        call_command('retention', stdout=StringIO())
        self.assertTrue(AccountAccess.objects.filter(pk=expired.pk).exists())
        fresh = record_access(self.request(), self.owner, 'session')
        self.assertFalse(AccountAccess.objects.filter(pk=expired.pk).exists())
        self.assertTrue(AccountAccess.objects.filter(pk=fresh.pk).exists())
        AccountAccess.objects.filter(pk=fresh.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        call_command('retention', '--apply', stdout=StringIO())
        self.assertFalse(AccountAccess.objects.filter(pk=fresh.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())

    def test_history_storage_failure_does_not_break_authentication(self):
        with patch('portal.access_tracking.AccountAccess.objects.create', side_effect=DatabaseError('secret network detail')):
            with self.assertLogs('portal.access_tracking', level='WARNING') as logs:
                response = self.client.post('/iniciar-sesion/', {'username': self.owner.email, 'password': 'Synthetic-access-87543!'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
        self.assertNotIn('secret network detail', ' '.join(logs.output))

    def test_worker_cleans_expired_access_history_even_without_new_visits(self):
        expired = record_access(self.request(), self.owner, 'login')
        fresh = record_access(self.request(), self.owner, 'session')
        AccountAccess.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with patch('portal.management.commands.runworker.signal.signal'), \
                patch('portal.management.commands.runworker.close_old_connections'), \
                patch('portal.management.commands.runworker.process_next_job', return_value=False), \
                patch('portal.management.commands.runworker.process_notifications', return_value=0):
            call_command('runworker', '--once', stdout=StringIO())
        self.assertFalse(AccountAccess.objects.filter(pk=expired.pk).exists())
        self.assertTrue(AccountAccess.objects.filter(pk=fresh.pk).exists())

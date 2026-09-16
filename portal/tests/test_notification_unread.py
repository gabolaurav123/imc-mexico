"""Unread alerts are private, read-only on GET and acknowledged only via CSRF POST."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Permission
from django.db import OperationalError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.context import site_context
from portal.models import Asset, Machine, Message, Notification, User
from portal.notifications import AUTH_KINDS, notification_target, unread_state
from portal.services import review_submission, submit_machine


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
    STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class NotificationUnreadTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='unread-owner@example.invalid', first_name='Owner')
        self.other = User.objects.create_user(email='unread-other@example.invalid')
        self.staff = User.objects.create_user(email='unread-reviewer@example.invalid', is_staff=True)
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label='portal', codename='review_submission'))
        self.machine = Machine.objects.create(owner=self.owner, title='Ficha de ensayo')
        self.client.force_login(self.owner)

    def notice(self, **changes):
        values = {'user': self.owner, 'machine': self.machine, 'kind': 'reply', 'subject': 'Una observación',
                  'body': 'Revisa el accesorio de la fotografía.', 'channel': 'in_app', 'status': 'sent', 'sent_at': timezone.now()}
        values.update(changes)
        return Notification.objects.create(**values)

    def reviewer_login(self):
        self.client.force_login(self.staff)
        device = TOTPDevice.objects.create(user=self.staff, name='IMC', confirmed=True)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def submission(self):
        Asset.objects.create(machine=self.machine, kind='image', purpose='general', processing_status='ready',
            original='private/synthetic-only.jpg', mime_type='image/jpeg', sha256='c' * 64, size=100)
        return submit_machine(self.machine, self.owner, True)

    def test_summary_is_owner_only_sent_in_app_and_excludes_every_auth_kind(self):
        own = self.notice()
        for changes in ({'user': self.other}, {'channel': 'email'}, {'status': 'pending'}, {'status': 'failed'},
                        *({'kind': kind} for kind in AUTH_KINDS)):
            self.notice(subject='FORBIDDEN-SUBJECT', body='FORBIDDEN-CONTENT', **changes)
        response = self.client.get('/panel/notificaciones/resumen/', {'user': self.other.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'viewer_id': str(self.owner.pk), 'unread_count': 1,
            'latest': {'id': own.pk, 'subject': own.subject, 'body': own.body, 'url': f'/panel/notificaciones/{own.pk}/'}})
        self.assertNotContains(response, 'FORBIDDEN')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        own.refresh_from_db()
        self.assertIsNone(own.read_at)
        inbox = self.client.get('/panel/notificaciones/')
        self.assertEqual([item.pk for item in inbox.context['notifications']], [own.pk])
        self.assertNotContains(inbox, 'FORBIDDEN')

    def test_summary_is_bounded_plain_text_and_never_copies_untrusted_link_destinations(self):
        body = '<b>Observación</b>\x00\n' + ('datos ' * 80) + 'https://other.example/path'
        own = self.notice(subject='<img src=x>Revisar', body=body)
        payload = self.client.get('/panel/notificaciones/resumen/').json()['latest']
        self.assertEqual(payload['subject'], 'Revisar')
        self.assertNotIn('<', payload['body'])
        self.assertNotIn('\x00', payload['body'])
        self.assertNotIn('\n', payload['body'])
        self.assertLessEqual(len(payload['body']), 240)
        self.assertEqual(payload['url'], f'/panel/notificaciones/{own.pk}/')
        own.refresh_from_db()
        self.assertEqual(own.body, body)

    def test_context_and_all_get_views_preserve_unread_state(self):
        own = self.notice()
        for url in ('/panel/', '/panel/notificaciones/', f'/panel/notificaciones/{own.pk}/', '/panel/notificaciones/resumen/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                if response.context:
                    self.assertEqual(response.context['notification_unread_count'], 1)
                    self.assertEqual(response.context['notification_latest_unread'].pk, own.pk)
                own.refresh_from_db()
                self.assertIsNone(own.read_at)
        response = self.client.get(f'/panel/notificaciones/{own.pk}/')
        self.assertEqual(response.context['notification_target_url'], f'/panel/mensajes/?maquinaria={self.machine.pk}')

    def test_read_posts_require_csrf_and_get_cannot_mark_one_or_all(self):
        own = self.notice()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url in (f'/panel/notificaciones/{own.pk}/leer/', '/panel/notificaciones/leer-todas/'):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 405)
                self.assertEqual(client.post(url).status_code, 403)
                own.refresh_from_db()
                self.assertIsNone(own.read_at)
        client.get('/panel/notificaciones/')
        csrf = client.cookies['csrftoken'].value
        response = client.post(f'/panel/notificaciones/{own.pk}/leer/', HTTP_X_CSRFTOKEN=csrf,
                               HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'viewer_id': str(self.owner.pk), 'unread_count': 0, 'latest': None})
        own.refresh_from_db()
        first_read = own.read_at
        self.assertIsNotNone(first_read)
        future = timezone.now() + timedelta(hours=2)
        with patch('portal.notifications.timezone.now', return_value=future):
            response = client.post(f'/panel/notificaciones/{own.pk}/leer/', HTTP_X_CSRFTOKEN=csrf)
        self.assertRedirects(response, f'/panel/notificaciones/{own.pk}/', fetch_redirect_response=False)
        own.refresh_from_db()
        self.assertEqual(own.read_at, first_read)

    def test_mark_all_changes_only_own_delivered_non_auth_unread_and_new_notices_stay_unread(self):
        first = self.notice()
        second = self.notice()
        already_read = self.notice(read_at=timezone.now() - timedelta(days=1))
        original_read = already_read.read_at
        protected = [self.notice(user=self.other), self.notice(channel='email'), self.notice(status='pending'),
                     self.notice(status='failed'), *(self.notice(kind=kind) for kind in AUTH_KINDS)]
        response = self.client.post('/panel/notificaciones/leer-todas/', {'user': self.other.pk})
        self.assertRedirects(response, '/panel/notificaciones/', fetch_redirect_response=False)
        for own in (first, second):
            own.refresh_from_db()
            self.assertIsNotNone(own.read_at)
        already_read.refresh_from_db()
        self.assertEqual(already_read.read_at, original_read)
        for notice in protected:
            notice.refresh_from_db()
            self.assertIsNone(notice.read_at)
        latest = self.notice(subject='Aviso nuevo después de marcar')
        payload = self.client.get('/panel/notificaciones/resumen/').json()
        self.assertEqual(payload['unread_count'], 1)
        self.assertEqual(payload['latest']['id'], latest.pk)

    def test_foreign_auth_pending_and_email_details_and_read_actions_are_not_accessible(self):
        protected = [self.notice(user=self.other), self.notice(channel='email'), self.notice(status='pending'),
                     self.notice(status='failed'), *(self.notice(kind=kind) for kind in AUTH_KINDS)]
        for notice in protected:
            with self.subTest(notice=notice.pk):
                self.assertEqual(self.client.get(f'/panel/notificaciones/{notice.pk}/').status_code, 404)
                self.assertEqual(self.client.post(f'/panel/notificaciones/{notice.pk}/leer/').status_code, 404)
                notice.refresh_from_db()
                self.assertIsNone(notice.read_at)

    def test_anonymous_summary_and_read_actions_do_not_reveal_any_account(self):
        own = self.notice()
        self.client.logout()
        self.assertEqual(self.client.get('/panel/notificaciones/').status_code, 302)
        self.assertEqual(self.client.get(f'/panel/notificaciones/{own.pk}/').status_code, 302)
        self.assertEqual(self.client.get('/panel/notificaciones/resumen/').status_code, 401)
        self.assertEqual(self.client.post(f'/panel/notificaciones/{own.pk}/leer/').status_code, 401)
        self.assertEqual(self.client.post('/panel/notificaciones/leer-todas/').status_code, 401)
        self.assertEqual(unread_state(AnonymousUser()), (0, None))
        own.refresh_from_db()
        self.assertIsNone(own.read_at)

    def test_inbox_is_account_shared_space_for_staff_not_advertiser_mode(self):
        own = self.notice(user=self.staff, machine=None, kind='manual')
        self.client.force_login(self.staff)
        response = self.client.get('/panel/notificaciones/')
        self.assertTrue(response.context['is_management_user'])
        self.assertFalse(response.context['is_advertiser_mode'])
        self.assertEqual(response.context['notification_latest_unread'].pk, own.pk)
        self.assertNotContains(response, 'Aquí están tus propias maquinarias')

    def test_unavailable_read_state_during_migration_does_not_break_page_or_report_fake_summary(self):
        request = RequestFactory().get('/panel/')
        request.user = self.owner
        request.session = {}
        with patch('portal.notifications.unread_state', side_effect=OperationalError('column not available')):
            context = site_context(request)
            response = self.client.get('/panel/notificaciones/resumen/')
        self.assertEqual(context['notification_unread_count'], 0)
        self.assertIsNone(context['notification_latest_unread'])
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'column not available', status_code=503)
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())

    def test_notification_links_do_not_follow_reassigned_or_deleted_machines(self):
        own = self.notice()
        self.machine.owner = self.other
        self.machine.save(update_fields=['owner'])
        for deleted in (False, True):
            if deleted:
                self.machine.owner = self.owner
                self.machine.deleted_at = timezone.now()
                self.machine.save(update_fields=['owner', 'deleted_at'])
            response = self.client.get(f'/panel/notificaciones/{own.pk}/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['notification_target_url'], '')
            self.assertEqual(response.context['notification_target_label'], '')
        self.assertEqual(notification_target(self.notice(machine=None, kind='manual'), self.owner), ('', ''))

    def test_changes_requested_produces_unread_observation_without_waiting_for_email_worker(self):
        submission = self.submission()
        Notification.objects.filter(user=self.owner).update(read_at=timezone.now())
        review_submission(submission, self.staff, 'changes_requested', 'Falta una fotografía del accesorio.')
        notice = Notification.objects.get(user=self.owner, kind='review', channel='in_app')
        self.assertEqual(notice.status, 'sent')
        self.assertIsNotNone(notice.sent_at)
        self.assertIsNone(notice.read_at)
        self.assertEqual(Notification.objects.get(user=self.owner, kind='review', channel='email').status, 'pending')
        summary = self.client.get('/panel/notificaciones/resumen/').json()
        self.assertEqual(summary['unread_count'], 1)
        self.assertEqual(summary['latest']['id'], notice.pk)
        self.assertIn('Falta una fotografía', summary['latest']['body'])

    def test_review_message_notifies_both_channels_and_internal_note_stays_private(self):
        submission = self.submission()
        self.reviewer_login()
        self.assertFalse(self.staff.has_perm('portal.add_message'))
        self.assertFalse(self.staff.has_perm('portal.view_machine'))
        for internal in (False, True):
            response = self.client.post(f'/operaciones/solicitudes/{submission.pk}/', {
                'action': 'message', 'body': 'Observación externa' if not internal else 'Nota interna privada',
                'internal': 'on' if internal else ''})
            self.assertEqual(response.status_code, 302)
        notices = Notification.objects.filter(user=self.owner, machine=self.machine, kind='reply')
        self.assertEqual(notices.count(), 2)
        notice = notices.get(channel='in_app')
        self.assertEqual(notice.status, 'sent')
        self.assertIsNotNone(notice.sent_at)
        self.assertIsNone(notice.read_at)
        self.assertEqual(notices.get(channel='email').status, 'pending')
        self.client.force_login(self.owner)
        summary = self.client.get('/panel/notificaciones/resumen/').json()
        self.assertEqual(summary['latest']['id'], notice.pk)
        self.assertNotIn('Nota interna', str(summary))

    def test_review_message_and_notification_queue_rollback_together(self):
        submission = self.submission()
        self.reviewer_login()
        before = Notification.objects.count()
        with patch('portal.services._notify', side_effect=RuntimeError('synthetic queue failure')):
            with self.assertRaises(RuntimeError):
                self.client.post(f'/operaciones/solicitudes/{submission.pk}/', {'action': 'message', 'body': 'Must roll back'})
        self.assertFalse(Message.objects.filter(body='Must roll back').exists())
        self.assertEqual(Notification.objects.count(), before)

    def test_dashboard_shows_five_latest_external_messages_and_uses_actual_sender(self):
        for index in range(7):
            Message.objects.create(machine=self.machine, sender=self.staff, body=f'External note {index}')
        Message.objects.create(machine=self.machine, sender=self.staff, internal=True, body='INTERNAL SECRET')
        latest = Message.objects.create(machine=self.machine, sender=self.owner, body='Mi respuesta reciente')
        response = self.client.get('/panel/')
        messages = list(response.context['recent_messages'])
        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[0].pk, latest.pk)
        self.assertEqual(messages[0].sender_id, self.owner.pk)
        self.assertNotContains(response, 'External note 0')
        self.assertNotContains(response, 'INTERNAL SECRET')

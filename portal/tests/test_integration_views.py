import json
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import Client, RequestFactory, TestCase, override_settings
from PIL import Image

from portal.admin import PublicationAdmin
from portal.integration import ack_delivery, delivery_metadata, prepare_delivery
from django.core.exceptions import ValidationError
from portal.models import Asset, IntegrationDelivery, Machine, MachineVersion, Publication, User
from portal.export_payload import build_export_payload


@override_settings(STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False,
                   STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
                             'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class IntegrationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email='integration-owner@example.com', advertiser_status='approved')
        cls.other = User.objects.create_user(email='integration-other@example.com')
        cls.publisher = User.objects.create_superuser(email='integration-admin@example.com', password=None)
        cls.staff = User.objects.create_user(email='integration-staff@example.com', is_staff=True)

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        media = override_settings(MEDIA_ROOT=self.directory.name, PRIVATE_S3_BUCKET='')
        media.enable()
        self.addCleanup(media.disable)
        self.machine = Machine.objects.create(owner=self.owner, title='Excavadora', status='approved')
        raw = BytesIO()
        Image.new('RGB', (80, 40), 'orange').save(raw, 'PNG')
        self.asset = Asset(machine=self.machine, kind='image', purpose='general', processing_status='ready',
                           public_authorized=True, mime_type='image/png', size=len(raw.getvalue()), sha256='a'*64)
        self.asset.original.save('original.png', ContentFile(raw.getvalue()))
        self.version = MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.owner,
            data={'title': 'Excavadora', 'category_name': 'Excavadoras',
                  'data': {'brand': 'CAT', 'model': '320D', 'serial': 'SECRET-SERIAL',
                           'owner_email': 'PRIVATE-OWNER', 'notes': 'PRIVATE-NOTES', 'price': 10, 'currency': 'USD',
                           'estimate_basis': 'PRIVATE-ESTIMATE'},
                  'public_asset_ids': [str(self.asset.pk)], 'asset_ids': [str(self.asset.pk)]})
        self.machine.approved_version = self.version
        self.machine.save()
        self.url = f'/operaciones/integracion/{self.machine.pk}/'
        self.client.force_login(self.publisher)

    def prepare(self):
        payload, _ = build_export_payload(self.machine, self.version)
        return prepare_delivery(self.machine, self.publisher, payload)

    def receipt(self, delivery, **changes):
        return {**delivery_metadata(delivery), 'remote_id': '000017', 'external_reference': '0012345678901234',
                'remote_url': 'https://www.imcmexico.com.mx/catalogo-de-prueba-0012345678901234',
                'status': 'acknowledged', **changes}

    def test_operator_pages_are_read_only_and_access_is_restricted(self):
        for path in ['/operaciones/integracion/', self.url]:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(IntegrationDelivery.objects.count(), 0)
        for user in [self.owner, self.staff]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    @override_settings(STAFF_MFA_REQUIRED=True)
    def test_mfa_still_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_csrf_and_malformed_receipts_do_not_change_data(self):
        delivery = self.prepare()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.publisher)
        payload = {'action': 'acknowledge', 'delivery_id': str(delivery.pk),
                   'receipt': json.dumps(self.receipt(delivery)), 'evidence': 'Evidencia de prueba aislada.', 'verified': 'on'}
        self.assertEqual(csrf_client.post(self.url, payload).status_code, 403)
        for invalid in ['no-es-uuid', '']:
            self.assertEqual(self.client.post(self.url, {**payload, 'delivery_id': invalid}).status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'prepared')

    def test_checked_receipt_links_but_does_not_publish_and_return_route_is_private(self):
        delivery = self.prepare()
        response = self.client.post(self.url, {'action': 'acknowledge', 'delivery_id': str(delivery.pk),
            'receipt': json.dumps(self.receipt(delivery)), 'evidence': 'Acuse comprobado en un receptor de prueba aislado.', 'verified': 'on'})
        self.assertEqual(response.status_code, 302)
        pub = Publication.objects.get(machine=self.machine, destination='main')
        self.assertEqual(pub.integration_state, 'acknowledged')
        self.assertNotEqual(pub.status, 'published')
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(f'/panel/maquinarias/{self.machine.pk}/ficha/'), 'Consultar registro en IMC México')
        self.assertRedirects(self.client.get('/panel/vinculos/imc/?id=000017'), f'/panel/maquinarias/{self.machine.pk}/ficha/', fetch_redirect_response=False)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/panel/vinculos/imc/?id=000017').status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get('/panel/vinculos/imc/?id=000017').status_code, 302)

    def test_catalogue_check_reports_missing_and_never_changes_draft(self):
        response = self.client.post(self.url, {'action': 'catalogue_check', 'catalogue': '[]'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['catalogue_result']['status'], 'missing')
        self.assertEqual(IntegrationDelivery.objects.count(), 0)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.revision, 1)

    def test_zip_retries_keep_key_and_use_actual_media_and_safe_projection(self):
        url = f'/operaciones/maquinarias/{self.machine.pk}/exportar/'
        with patch('portal.pdf.build_pdf', return_value=b'%PDF-1.4\n'):
            first, second = self.client.post(url), self.client.post(url)
        self.assertEqual(first.status_code, 200)
        envelopes = []
        for response in (first, second):
            with zipfile.ZipFile(BytesIO(response.content)) as package:
                payload = json.loads(package.read('publicacion.json'))
                envelopes.append(json.loads(package.read('integracion.json')))
                asset = payload['assets'][0]
                self.assertTrue(asset['path'].endswith('.png'))
                self.assertEqual(asset['width'], 80)
                self.assertEqual(asset['height'], 40)
                self.assertEqual(len(package.read(asset['path'])), asset['size'])
                self.assertNotIn('SECRET-SERIAL', json.dumps(payload))
                self.assertNotIn('PRIVATE-', json.dumps(payload))
        self.assertEqual(envelopes[0]['delivery_id'], envelopes[1]['delivery_id'])
        self.assertEqual(IntegrationDelivery.objects.count(), 1)
        self.assertEqual(Publication.objects.get(machine=self.machine, destination='main').status, 'exported')

    def test_storage_failure_keeps_delivery_unprepared(self):
        with patch('portal.export_payload._read_export_file', side_effect=OSError('private/path/secret')):
            response = self.client.post(f'/operaciones/maquinarias/{self.machine.pk}/exportar/')
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(IntegrationDelivery.objects.count(), 0)

    def test_admin_json_reuses_public_projection(self):
        self.prepare()
        request = RequestFactory().post('/admin/')
        request.user = self.publisher
        response = PublicationAdmin(Publication, AdminSite()).export_main(request, Publication.objects.all())
        self.assertNotIn('SECRET-SERIAL', response.content.decode())
        self.assertNotIn('PRIVATE-', response.content.decode())
        record = json.loads(response.content)['records'][0]
        self.assertEqual(record['assets'][0]['mime_type'], 'image/png')
        self.assertEqual(record['integration']['source_machine_id'], str(self.machine.pk))

    def test_media_revocation_before_ack_is_rechecked(self):
        delivery = self.prepare()
        self.asset.public_authorized = False
        self.asset.save(update_fields=['public_authorized'])
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery), 'Acuse sintético comprobado durante la prueba.')
        delivery.refresh_from_db()
        self.assertEqual(delivery.state, 'prepared')

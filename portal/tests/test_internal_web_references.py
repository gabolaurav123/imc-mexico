"""Internal source links stay useful without weakening public publication gates."""
from copy import deepcopy
from io import BytesIO

from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from pypdf import PdfReader

from portal.pdf import build_pdf
from portal.services import _public_reference_url, public_web_references, save_draft, snapshot
from portal.tests import test_web_autofill as fixtures
from portal.views import sheet_context


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False, PRIVATE_S3_BUCKET='',
    STORAGES={'default': {'BACKEND': 'portal.storage.PrivateStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class InternalWebReferenceTests(TestCase):
    result = fixtures.WebAutofillTests.result
    job = fixtures.WebAutofillTests.job
    apply = fixtures.WebAutofillTests.apply

    def setUp(self):
        fixtures.WebAutofillTests.setUp(self)

    def cited_version(self):
        self.private_url = 'https://www.cat.com/equipment/CAT-SN1234?serial=CAT-SN1234'
        result = self.result({'power': '70 kW'}, scope='exact_serial', urls={'power': self.private_url},
                             titles={'power': 'Caterpillar 420F2<br>CAT-SN1234'})
        self.apply(self.job(result))
        return snapshot(self.machine, self.owner)

    def test_private_links_are_explicit_opt_in_and_br_is_display_text_only(self):
        version = self.cited_version()
        original = deepcopy(version.data)
        public = public_web_references(version.data)
        internal = public_web_references(version.data, include_private=True)
        self.assertEqual(public[0]['source_url'], '')
        self.assertEqual(public[0]['source_title'], 'Fuente privada')
        self.assertTrue(public[0]['private_source'])
        self.assertEqual(internal[0]['source_url'], self.private_url)
        self.assertEqual(internal[0]['source_title'], 'Caterpillar 420F2 CAT-SN1234')
        self.assertTrue(internal[0]['private_source'])
        self.assertEqual(version.data, original)
        self.assertEqual(public_web_references(version.data, include_private='true'), public)

    def test_internal_sheet_and_pdf_have_source_link_while_public_versions_never_do(self):
        version = self.cited_version()
        for public in (False, True):
            with self.subTest(public=public):
                context = sheet_context(self.machine, version, public=public, token='synthetic')
                context['user'] = self.owner
                html = render_to_string('portal/sheet.html', context)
                document = PdfReader(BytesIO(build_pdf(self.machine, context['data'], [], public=public, version=version)))
                pdf_text = '\n'.join(page.extract_text() for page in document.pages)
                links = [str(item.get_object().get('/A', {}).get('/URI', ''))
                         for page in document.pages for item in page.get('/Annots', [])]
                if public:
                    self.assertNotIn('CAT-SN1234', html)
                    self.assertNotIn('CAT-SN1234', pdf_text)
                    self.assertNotIn(self.private_url, links)
                else:
                    self.assertIn(self.private_url, html)
                    self.assertIn(self.private_url, links)
                    self.assertIn('Caterpillar 420F2 CAT-SN1234', html)
                    self.assertNotIn('420F2&lt;br&gt;', html)

    def test_internal_option_still_requires_signature_identity_and_safe_url(self):
        version = self.cited_version()
        tampered = deepcopy(version.data)
        analysis_id = next(iter(tampered['web_research']))
        tampered['web_research'][analysis_id]['proof'] = 'invalid'
        self.assertEqual(public_web_references(tampered, include_private=True), [])
        changed = deepcopy(version.data)
        changed['data']['model'] = 'OTHER-MODEL'
        self.assertEqual(public_web_references(changed, include_private=True), [])
        for unsafe in ('javascript:alert(1)', 'https://user:pass@example.com/serial',
                       'https://localhost/serial', 'https://127.0.0.1/serial', 'https://example.com/\nserial'):
            with self.subTest(url=unsafe):
                self.assertEqual(_public_reference_url(unsafe, {'private1234'}, include_private=True), '')

    def ocr_result(self):
        return {'data': {'manufacturer': 'Fabricante de prueba Inc.', 'description': 'Sólo fabricante recién leído.'},
            'provenance': {'manufacturer': {'source': 'plate', 'review': 'clear', 'component': 'machine',
                'asset_id': str(self.asset.pk), 'evidence': 'Manufacturer: Fabricante de prueba Inc.'},
                'description': {'source': 'system', 'review': 'needs_review'}},
            'fields': [], 'plates': [], 'research': {'status': 'disabled', 'fields': [], 'sources': []}}

    def test_ocr_refresh_preserves_prior_web_facts_when_research_is_disabled(self):
        self.apply(self.job(self.result()))
        prior_sources = deepcopy({key: self.machine.provenance[key] for key in ('power', 'weight')})
        self.apply(self.job(self.ocr_result()))
        description = self.machine.data['description']
        for value in ('Fabricante de prueba Inc.', '70 kW', '8000 kg', 'requieren comprobación'):
            self.assertIn(value, description)
        self.assertNotIn('Sólo fabricante recién leído.', description)
        self.assertNotIn('CAT-SN1234', description)
        self.assertEqual({key: self.machine.provenance[key] for key in prior_sources}, prior_sources)
        self.assertEqual(len(public_web_references(snapshot(self.machine, self.owner).data)), 2)

    def test_ocr_refresh_still_preserves_description_edited_while_job_is_running(self):
        self.apply(self.job(self.result()))
        job = self.job(self.ocr_result())
        self.machine = save_draft(self.machine, self.owner,
            {'data': {'description': 'Texto corregido por el propietario.'}}, self.machine.revision)
        self.apply(job)
        self.assertEqual(self.machine.data['description'], 'Texto corregido por el propietario.')
        self.assertEqual(self.machine.data['manufacturer'], 'Fabricante de prueba Inc.')

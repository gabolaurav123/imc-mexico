import json
import uuid
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings

from portal.intake import has_completed_preparation, preparation_mode
from portal.models import AnalysisJob, Asset, Category, Lead, Machine, MachineVersion, PreparedShare, Publication, User
from portal.public_data import public_projection


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_URL="https://example.invalid", STORAGES={
    "default": {"BACKEND": "portal.storage.PrivateStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class PreparedSharingTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        media = override_settings(MEDIA_ROOT=self.directory.name, PRIVATE_S3_BUCKET="")
        media.enable()
        self.addCleanup(media.disable)
        self.user = User.objects.create_user(email="share@example.invalid", phone="+525512345678")
        self.category = Category.objects.create(name="Excavadoras", slug="share-excavators")
        self.machine = Machine.objects.create(owner=self.user, category=self.category, title="Excavadora CAT 320",
            data={"brand": "CAT", "model": "320", "serial": "PRIVATE-SN-123", "notes": "PRIVATE NOTES",
                  "description": "Excavadora sobre orugas.", "estimate_min": "50000", "estimate_max": "80000",
                  "estimate_currency": "USD", "estimated_year_from": 2007, "estimated_year_to": 2012})
        self.client.force_login(self.user)
        self.url = f"/api/maquinarias/{self.machine.pk}/compartir/"

    def photo(self, purpose="general", assessment="accepted"):
        asset = Asset.objects.create(machine=self.machine, kind="image", purpose=purpose,
            mime_type="image/jpeg", sha256=uuid.uuid4().hex, processing_status="ready")
        asset.original.save("test.jpg", ContentFile(b"a-small-private-test-file"))
        if assessment:
            key = {"accepted": "accepted_asset_ids", "unrelated": "excluded_asset_ids", "uncertain": "uncertain_asset_ids"}[assessment]
            AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, revision=self.machine.revision,
                status="completed", fingerprint=uuid.uuid4().hex, asset_ids=[str(asset.pk)],
                result={"relevance": {"status": "relevant" if assessment == "accepted" else assessment, key: [str(asset.pk)]}})
        return asset

    def enable(self, **extra):
        return self.client.post(self.url, json.dumps({"revision": self.machine.revision, **extra}), content_type="application/json")

    def path(self, response):
        return response.json()["url"].removeprefix("https://example.invalid")

    def test_pending_owner_can_share_short_snapshot_without_publishing_or_exposing_private_fields(self):
        photo, plate, document = self.photo(), self.photo("plate"), self.photo("document")
        response = self.enable()
        self.assertEqual(response.status_code, 200, response.content)
        share = PreparedShare.objects.get()
        self.assertEqual(len(share.code), 16)
        self.assertFalse(Publication.objects.exists())
        self.assertFalse(self.machine.versions.exists())
        self.assertEqual(share.snapshot["public_asset_ids"], [str(photo.pk)])
        page = Client().get(self.path(response))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["main_assets"], [photo])
        self.assertFalse(page.context["can_export"])
        self.assertNotIn("serial", page.context["data"])
        self.assertNotContains(page, "PRIVATE NOTES")
        self.assertNotContains(page, "PRIVATE-SN-123")
        self.assertEqual(page.context["data"]["estimate_min"], "50000")
        self.assertContains(page, f'/s/{share.code}/archivo/{photo.pk}/')
        self.assertContains(page, f'data-share-sheet="https://example.invalid/s/{share.code}/"', count=2)
        public_photo = Client().get(f"/s/{share.code}/archivo/{photo.pk}/")
        self.assertEqual(public_photo.status_code, 200)
        public_photo.close()
        for excluded in (plate, document):
            self.assertEqual(Client().get(f"/s/{share.code}/archivo/{excluded.pk}/").status_code, 404)
        self.assertEqual(Client().get(f"/s/{share.code}/pdf/").status_code, 404)
        self.assertEqual(self.client.get(f"/panel/maquinarias/{self.machine.pk}/pdf/").status_code, 403)

    def test_owner_sheet_prepares_the_link_in_a_modal_without_returning_to_the_editor(self):
        page = self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'data-share-machine-id="{self.machine.pk}"', count=2)
        self.assertContains(page, 'id="share-modal"')
        self.assertContains(page, 'WhatsApp')
        self.assertContains(page, 'Facebook')
        self.assertContains(page, 'Instagram y otras apps')
        self.assertNotContains(page, '#share-options')

    def test_ready_editor_uses_the_same_share_modal(self):
        page = self.client.get(f"/panel/maquinarias/{self.machine.pk}/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="share-modal"')
        self.assertContains(page, 'portal/share-modal.js')
        self.assertContains(page, 'data-share-machine', count=2)
        self.assertNotContains(page, 'id="share-options"')

    def test_unexpected_share_failure_remains_a_json_response(self):
        with patch("portal.sharing.preparation_mode", side_effect=RuntimeError("database adapter failed")), \
             patch("portal.sharing.logger"):
            response = self.enable()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["Content-Type"].split(";", 1)[0], "application/json")
        self.assertIn("No se pudo preparar el enlace", response.json()["error"])

    def test_postgres_lock_targets_machine_not_optional_category_join(self):
        from django.db.backends.postgresql.base import DatabaseWrapper
        from portal.sharing import _locked_machine_query

        postgres = DatabaseWrapper({"ENGINE": "django.db.backends.postgresql", "NAME": "share_test"}, "share_test")
        with patch("portal.sharing.connection.features.has_select_for_update_of", True), \
             patch.object(postgres, "get_autocommit", return_value=False):
            sql, _ = _locked_machine_query().query.get_compiler(connection=postgres).as_sql()
        self.assertIn('FOR UPDATE OF "portal_machine"', sql)

    def test_serial_is_explicit_opt_in_and_can_be_removed_without_changing_link(self):
        self.photo()
        first = self.enable(include_serial=True)
        page = Client().get(self.path(first))
        self.assertEqual(page.context["data"]["serial"], "PRIVATE-SN-123")
        self.assertTrue(page.context['public_serial_authorized'])
        self.assertContains(page, 'PRIVATE-SN-123')
        second = self.enable(include_serial=False)
        self.assertEqual(first.json()["url"], second.json()["url"])
        self.assertNotIn("serial", Client().get(self.path(second)).context["data"])
        self.assertNotContains(Client().get(self.path(second)), 'PRIVATE-SN-123')

    def test_contact_opt_in_shares_only_chosen_channel_and_is_revocable(self):
        self.photo()
        first = self.enable()
        self.assertNotIn("contact_public", Client().get(self.path(first)).context["data"])
        shared = self.enable(include_contact=True)
        contact = Client().get(self.path(shared)).context["data"]["contact_public"]
        self.assertEqual(contact, f"Correo: {self.user.email}")
        self.assertNotIn(self.user.phone, contact)
        self.assertTrue(self.client.get(self.url).json()["include_contact"])
        self.assertEqual(self.enable(include_contact="yes").status_code, 400)
        cleared = self.enable(include_contact=False)
        self.assertNotIn("contact_public", Client().get(self.path(cleared)).context["data"])

    def test_readable_model_conflict_can_be_corrected_without_account_penalty(self):
        photo = self.photo()
        job = self.machine.analysis_jobs.get()
        job.result['fields'] = [{"key":"model", "value":"PC210", "source":"image",
            "component":"machine", "review":"clear", "asset_id":str(photo.pk)}]
        job.save(update_fields=['result'])
        self.machine.provenance = {"model":{"source":"user", "review":"confirmed"}}
        self.machine.save(update_fields=['provenance'])
        blocked = self.enable()
        self.assertEqual(blocked.status_code, 400)
        self.assertIn('no coinciden', blocked.json()['error'])
        self.machine.data['model'] = 'PC210'
        self.machine.save(update_fields=['data'])
        self.assertEqual(self.enable().status_code, 200)

    def test_separate_analyses_of_different_machines_do_not_bypass_congruence(self):
        for model in ('320', 'PC210'):
            photo = self.photo()
            job = self.machine.analysis_jobs.filter(asset_ids=[str(photo.pk)]).get()
            job.result['fields'] = [{"key":"model", "value":model, "source":"image",
                "component":"machine", "review":"clear", "asset_id":str(photo.pk)}]
            job.save(update_fields=['result'])
        blocked = self.enable()
        self.assertEqual(blocked.status_code, 400)
        self.assertIn('no coinciden', blocked.json()['error'])
        self.assertFalse(PreparedShare.objects.exists())

    def test_revision_refresh_keeps_code_but_revocation_never_reactivates_old_url(self):
        self.photo()
        first = self.enable()
        self.machine.revision += 1
        self.machine.save(update_fields=["revision"])
        self.assertEqual(Client().get(self.path(first)).status_code, 404)
        fresh = self.enable()
        self.assertEqual(first.json()["url"], fresh.json()["url"])
        self.assertEqual(self.enable(action="disable").status_code, 200)
        self.assertEqual(Client().get(self.path(fresh)).status_code, 404)
        again = self.enable()
        self.assertNotEqual(fresh.json()["url"], again.json()["url"])
        self.assertEqual(Client().get(self.path(fresh)).status_code, 404)

    def test_owner_only_csrf_stale_and_foreign_media_guards(self):
        self.photo()
        other = User.objects.create_user(email="other-share@example.invalid")
        stranger = Client()
        stranger.force_login(other)
        self.assertEqual(stranger.post(self.url, '{}', content_type="application/json").status_code, 404)
        self.assertEqual(Client().post(self.url, '{}', content_type="application/json").status_code, 401)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.url, '{}', content_type="application/json").status_code, 403)
        self.assertEqual(self.enable(revision=self.machine.revision + 1).status_code, 409)
        self.assertEqual(self.enable(asset_ids=[str(uuid.uuid4())]).status_code, 400)
        self.assertFalse(PreparedShare.objects.exists())

    def test_unrelated_photo_stops_share_and_submission_without_suspending_account(self):
        self.photo(assessment="unrelated")
        self.assertEqual(self.enable().status_code, 400)
        submitted = self.client.post(f"/api/maquinarias/{self.machine.pk}/enviar/",
            json.dumps({"advertise_consent": True}), content_type="application/json")
        self.assertEqual(submitted.status_code, 400)
        self.assertIn("no corresponden", submitted.json()["error"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.advertiser_status, "pending")

    def test_unassessed_new_photo_requires_generation_and_is_never_shared(self):
        self.photo()
        unassessed = self.photo(assessment=None)
        blocked = self.enable()
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("nuevas fotografías", blocked.json()["error"])
        self.assertEqual(self.enable(asset_ids=[str(unassessed.pk)]).status_code, 400)

    def test_preflight_for_a_current_photo_cannot_reuse_a_removed_photos_normal_analysis(self):
        old_photo = self.photo()
        old_photo.processing_status = "pending"
        old_photo.save(update_fields=["processing_status"])
        current_photo = self.photo(assessment=None)
        preflight = AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, revision=self.machine.revision,
            status="completed", fingerprint=uuid.uuid4().hex, asset_ids=[str(current_photo.pk)],
            result={"preflight": True, "relevance": {"status": "relevant", "accepted_asset_ids": [str(current_photo.pk)]}})
        with patch("portal.catalogue_intake.catalogue_reference_ready", return_value=True), \
             patch("portal.catalogue_intake.catalogue_reference_stale", return_value=False):
            self.assertFalse(has_completed_preparation(self.machine))
        approved = MachineVersion.objects.create(machine=self.machine, created_by=self.user, number=1,
            data={"data": self.machine.data, "title": self.machine.title})
        self.machine.approved_version = approved
        self.machine.save(update_fields=["approved_version"])
        blocked = self.enable()
        self.assertEqual(blocked.status_code, 400, blocked.content)
        self.assertIn("Genera la ficha", blocked.json()["error"])

        preflight.result["preflight"] = False
        preflight.save(update_fields=["result"])
        self.assertTrue(has_completed_preparation(self.machine))
        self.assertEqual(self.enable().status_code, 200)

    def test_serial_only_can_share_useful_completed_generation_and_contact_lead(self):
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, revision=1,
            status="completed", mode="description", fingerprint=uuid.uuid4().hex)
        result = self.enable()
        self.assertEqual(result.status_code, 200, result.content)
        share = PreparedShare.objects.get()
        page = Client().get(self.path(result))
        self.assertEqual(page.context["main_assets"], [])
        contact_url = page.context["share_contact_url"]
        self.assertEqual(Client().get(contact_url).status_code, 200)
        self.assertEqual(Client().get(f"/contacto/?maquinaria={self.machine.pk}").status_code, 404)
        posted = Client().post('/contacto/', {"machine": self.machine.pk, "share": share.code,
            "name": "Comprador", "email": "buyer@example.invalid", "message": "Me interesa esta excavadora.", "privacy": "on"})
        self.assertEqual(posted.status_code, 302)
        self.assertTrue(Lead.objects.filter(machine=self.machine).exists())

    def test_serial_only_prepared_fiche_can_be_submitted_without_publication(self):
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, revision=1,
            status="completed", mode="description", fingerprint=uuid.uuid4().hex)
        response = self.client.post(f"/api/maquinarias/{self.machine.pk}/enviar/",
            json.dumps({"advertise_consent": True}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.status, 'submitted')
        self.assertFalse(self.machine.assets.exists())
        self.assertEqual(self.machine.versions.get().data['data']['serial'], 'PRIVATE-SN-123')
        self.assertEqual(self.machine.versions.get().data['public_asset_ids'], [])
        self.assertFalse(Publication.objects.exists())
        # Acceptance for human review does not relax catalogue publication.
        from portal.services import set_publication
        self.user.advertiser_status = 'approved'
        self.user.save(update_fields=['advertiser_status'])
        self.machine.approved_version = self.machine.versions.get()
        self.machine.save(update_fields=['approved_version'])
        publisher = User.objects.create_superuser(email='serial-publisher@example.invalid')
        with self.assertRaisesMessage(Exception, 'fotografías autorizadas'):
            set_publication(self.machine, publisher, True)
        self.assertFalse(Publication.objects.exists())

    def test_serial_without_finished_generation_cannot_be_submitted_as_prepared(self):
        response = self.client.post(f"/api/maquinarias/{self.machine.pk}/enviar/",
            json.dumps({"advertise_consent": True}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn('Genera la ficha', response.json()['error'])
        self.assertFalse(self.machine.submissions.exists())

    def test_no_series_or_image_cannot_submit_even_after_old_description_job(self):
        self.machine.data.pop('serial')
        self.machine.save(update_fields=['data'])
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, revision=1,
            status="completed", mode="description", fingerprint=uuid.uuid4().hex)
        response = self.client.post(f"/api/maquinarias/{self.machine.pk}/enviar/",
            json.dumps({"advertise_consent": True}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.machine.submissions.exists())

    def test_account_suspension_transfer_and_withdrawal_close_prepared_links(self):
        self.photo()
        result = self.enable()
        self.user.advertiser_status = "suspended"
        self.user.save(update_fields=["advertiser_status"])
        self.assertEqual(Client().get(self.path(result)).status_code, 404)
        self.user.advertiser_status = "pending"
        self.user.save(update_fields=["advertiser_status"])
        self.machine.availability = "withdrawn"
        self.machine.save(update_fields=["availability"])
        self.assertEqual(Client().get(self.path(result)).status_code, 404)
        self.machine.availability = "available"
        self.machine.owner = User.objects.create_user(email="transferred-share@example.invalid")
        self.machine.save(update_fields=["availability", "owner"])
        self.assertEqual(Client().get(self.path(result)).status_code, 404)

    def test_analysis_requires_category_and_serial_or_photo_not_description(self):
        self.machine.data = {"description": "Texto solo", "brand": "CAT", "model": "320"}
        self.machine.save(update_fields=["data"])
        with patch('portal.processing.enqueue_analysis') as enqueue:
            result = self.client.post(f"/api/maquinarias/{self.machine.pk}/analizar/",
                json.dumps({"consent": True, "mode": "description"}), content_type="application/json")
        self.assertEqual(result.status_code, 400)
        enqueue.assert_not_called()
        self.machine.data["serial"] = "SN123456"
        self.assertEqual(preparation_mode(self.machine), "description")
        self.photo()
        self.assertEqual(preparation_mode(self.machine), "analysis")
        self.machine.category = None
        with self.assertRaisesMessage(Exception, "tipo de máquina"):
            preparation_mode(self.machine)

    def test_price_range_requires_currency_and_order_and_never_becomes_asking_price(self):
        data = {"estimate_min": "10", "estimate_max": "20", "estimate_currency": "USD"}
        self.assertEqual(public_projection({"data": data}), data)
        for updates in ({"estimate_currency": ""}, {"estimate_min": "21"}, {"estimate_min": "NaN"}):
            self.assertNotIn("estimate_min", public_projection({"data": {**data, **updates}}))

    def test_legacy_short_alias_keeps_approval_and_revocation_requirements(self):
        from portal.sharing import legacy_share_url
        photo = self.photo()
        photo.public_authorized = True
        photo.save(update_fields=['public_authorized'])
        self.user.advertiser_status = 'approved'
        self.user.save(update_fields=['advertiser_status'])
        version = MachineVersion.objects.create(machine=self.machine, created_by=self.user, number=1,
            data={'data':self.machine.data, 'title':self.machine.title, 'public_asset_ids':[str(photo.pk)]})
        self.machine.approved_version = version
        self.machine.save(update_fields=['approved_version'])
        publication = Publication.objects.create(machine=self.machine, version=version, enabled=True, status='published')
        path = legacy_share_url(publication.token).removeprefix('https://example.invalid')
        self.assertEqual(len(path.split('/')[2]), 22)
        self.assertEqual(Client().get(path).status_code, 200)
        picture = Client().get(path + f'archivo/{photo.pk}/')
        self.assertEqual(picture.status_code, 200)
        picture.close()
        publication.enabled = False
        publication.save(update_fields=['enabled'])
        self.assertEqual(Client().get(path).status_code, 404)
        self.assertFalse(PreparedShare.objects.exists())

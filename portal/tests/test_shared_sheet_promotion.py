"""The catalogue invitation is restricted to shared HTML documents."""
from copy import deepcopy

from django.test import TestCase, override_settings

from portal.models import Category, Machine, MachineVersion, PreparedShare, Publication, User


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    "default": {"BACKEND": "portal.storage.PrivateStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class SharedSheetPromotionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="promotion@example.invalid", advertiser_status="approved", is_test=True)
        category = Category.objects.create(name="Excavadoras", slug="promotion-excavators")
        self.machine = Machine.objects.create(owner=self.owner, category=category, title="Excavadora de prueba",
            data={"brand": "Marca de prueba", "model": "Modelo de prueba", "description": "Equipo hidráulico."})
        snapshot = {"title": self.machine.title, "category_name": category.name, "data": deepcopy(self.machine.data),
                    "asset_ids": [], "public_asset_ids": [], "provenance": {}}
        self.version = MachineVersion.objects.create(machine=self.machine, number=1, data=deepcopy(snapshot), created_by=self.owner)
        self.machine.approved_version = self.version
        self.machine.save(update_fields=["approved_version"])
        self.publication = Publication.objects.create(machine=self.machine, version=self.version,
            destination="share", enabled=True, status="published")
        self.share = PreparedShare.objects.create(machine=self.machine, authorized_by=self.owner,
            revision=self.machine.revision, snapshot=deepcopy(snapshot), enabled=True)

    def test_both_shared_routes_include_invitation_and_keep_footer_catalogue_link(self):
        for url in (f"/ficha/{self.publication.token}/", f"/s/{self.share.code}/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="similar-machines-modal"', count=1)
                self.assertContains(response, 'similar-machines-modal.css?v=20260927', count=1)
                self.assertContains(response, 'similar-machines-modal.js?v=20260927', count=1)
                self.assertContains(response, '¿Buscas una máquina similar?', count=2)
                self.assertContains(response, 'Consulta el catálogo de maquinaria de IMC México.', count=2)
                self.assertContains(response, 'Ver máquinas similares en IMC México ↗', count=2)
                self.assertContains(response, 'class="similar-machines-cta"', count=1)
                self.assertContains(response, 'Seguir viendo la ficha', count=1)
                self.assertContains(response, 'id="share-modal"', count=1)

    def test_owner_sheet_and_editor_do_not_load_or_render_the_invitation(self):
        self.client.force_login(self.owner)
        for url in (f"/panel/maquinarias/{self.machine.pk}/ficha/", f"/panel/maquinarias/{self.machine.pk}/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'similar-machines-modal')
                self.assertNotContains(response, 'Seguir viendo la ficha')
        owner_sheet = self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/")
        self.assertContains(owner_sheet, 'class="similar-machines-cta"', count=1)

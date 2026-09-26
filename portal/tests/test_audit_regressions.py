"""Cross-cutting regressions found while auditing the published application."""
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from portal.integration import set_imc_media_selection
from portal.models import Asset, Category, Machine, MachineVersion, Publication, User
from portal.services import set_publication
from portal.sharing import legacy_share_url


@override_settings(STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PublicationEligibilityAuditTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="audit-owner@example.invalid", advertiser_status="approved")
        self.publisher = User.objects.create_superuser(email="audit-admin@example.invalid", password=None)
        category = Category.objects.create(name="Excavadora", slug="audit-excavadora")
        self.machine = Machine.objects.create(owner=self.owner, title="Audit CAT 320D", category=category,
                                              status="approved", data={"brand": "CAT", "model": "320D"})
        self.photo = Asset.objects.create(machine=self.machine, original="audit/original.jpg", kind="image",
                                          purpose="general", processing_status="ready", public_authorized=True,
                                          mime_type="image/jpeg", sha256="a" * 64)
        self.version = MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.publisher,
            data={"title": self.machine.title, "category_name": category.name, "data": self.machine.data,
                  "asset_ids": [str(self.photo.pk)], "public_asset_ids": [str(self.photo.pk)]})
        self.machine.approved_version = self.version
        self.machine.save(update_fields=["approved_version"])
        self.publication = Publication.objects.create(machine=self.machine, version=self.version,
                                                       enabled=True, status="published", destination="share")

    def disable_owner(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])

    def test_deactivated_owner_disappears_from_public_catalogue(self):
        self.assertContains(self.client.get("/maquinaria/"), "CAT 320D")
        self.disable_owner()
        response = self.client.get("/maquinaria/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result_count"], 0)
        self.assertNotContains(response, "CAT 320D")

    def test_deactivated_owner_revokes_fiche_alias_asset_and_contact_access(self):
        self.disable_owner()
        token = self.publication.token
        alias_path = "/s/" + legacy_share_url(token).rstrip("/").rsplit("/", 1)[-1] + "/"
        for path in (f"/ficha/{token}/", alias_path,
                     f"/ficha/{token}/archivo/{self.photo.pk}/",
                     alias_path + f"archivo/{self.photo.pk}/",
                     f"/contacto/?maquinaria={self.machine.pk}"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_deactivated_owner_cannot_be_published_again(self):
        self.disable_owner()
        with self.assertRaises(ValidationError):
            set_publication(self.machine, self.publisher, True)

    def test_model_rejects_enabled_publication_for_inactive_owner(self):
        self.disable_owner()
        publication = Publication.objects.select_related("machine__owner").get(pk=self.publication.pk)
        with self.assertRaises(ValidationError):
            publication.full_clean()

    def test_guest_principal_cannot_be_exposed_by_stale_publication(self):
        self.owner.is_guest = True
        self.owner.save(update_fields=["is_guest"])
        self.assertEqual(self.client.get("/maquinaria/").context["result_count"], 0)
        self.assertEqual(self.client.get(f"/ficha/{self.publication.token}/").status_code, 404)
        self.assertEqual(self.client.get(f"/contacto/?maquinaria={self.machine.pk}").status_code, 404)
        with self.assertRaises(ValidationError):
            set_publication(self.machine, self.publisher, True)

    def test_media_selection_locks_only_machine_with_nullable_approved_version_join(self):
        # SQLite ignores SELECT FOR UPDATE. Preserve the explicit lock target so
        # the same operation remains valid on production PostgreSQL.
        with patch.object(Machine.objects, "select_for_update", wraps=Machine.objects.select_for_update) as lock:
            publication = set_imc_media_selection(self.machine, self.publisher, [f"{self.photo.pk}|1"])
        lock.assert_called_once_with(of=("self",))
        self.assertEqual(publication.imc_asset_ids, [str(self.photo.pk)])
        self.assertEqual(publication.imc_selection_version_id, self.version.pk)

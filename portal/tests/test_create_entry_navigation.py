"""Opening the intake page must work without JavaScript or a draft-creation POST."""
from html.parser import HTMLParser

from django.test import TestCase, override_settings
from django.urls import reverse

from portal.models import AnalysisJob, Category, GuestDraft, Machine, Publication, User


class _CreationControls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.active = []
        self.controls = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {"a", "button"}:
            self.active.append({"tag": tag, "attrs": dict(attrs), "text": ""})

    def handle_data(self, data):
        if self.active:
            self.active[-1]["text"] += data

    def handle_endtag(self, tag):
        if self.active and self.active[-1]["tag"] == tag:
            control = self.active.pop()
            if " ".join(control["text"].split()).startswith("Agregar "):
                self.controls.append(control)


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False, STORAGES={
    "default": {"BACKEND": "portal.storage.PrivateStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class CreateEntryNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="entry-owner@example.invalid", phone="+525512345678")
        cls.staff = User.objects.create_user(email="entry-staff@example.invalid", phone="+525512345679", is_staff=True)
        Category.objects.create(name="Excavadoras", slug="entry-navigation-excavators")

    def test_dashboard_list_empty_state_and_editorial_ctas_are_native_intake_links(self):
        destination = reverse("machine_create")
        for user in (self.owner, self.staff):
            self.client.force_login(user)
            pages = (("/panel/?modo=anunciante" if user.is_staff else "/panel/", 2),
                     (reverse("machines"), 2), ("/guia-de-fotos/", 1))
            for path, expected_controls in pages:
                with self.subTest(staff=user.is_staff, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    controls = _CreationControls(response.content.decode()).controls
                    self.assertEqual(len(controls), expected_controls)
                    for control in controls:
                        self.assertEqual(control["tag"], "a")
                        self.assertEqual(control["attrs"].get("href"), destination)
                        self.assertNotIn("data-create", control["attrs"])

    def test_opening_intake_does_not_create_records_for_owner_or_staff(self):
        existing = Machine.objects.create(owner=self.owner, data={"serial": "KEEP-ENTRY-123"})
        tracked = (Machine, AnalysisJob, GuestDraft, Publication)
        before = {model: model.objects.count() for model in tracked}
        for user in (self.owner, self.staff):
            self.client.force_login(user)
            with self.subTest(staff=user.is_staff):
                response = self.client.get(reverse("machine_create"))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "portal/start.html")
                self.assertEqual({model: model.objects.count() for model in tracked}, before)
        existing.refresh_from_db()
        self.assertEqual(existing.data, {"serial": "KEEP-ENTRY-123"})

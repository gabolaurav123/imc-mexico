from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.urls import reverse

from portal.models import Machine, User


@override_settings(STAFF_MFA_REQUIRED=False)
class AdminMachineCountsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="machine-count-admin@example.invalid", password="safe-test-password")
        self.owner = User.objects.create_user(email="many-machines@example.invalid", password=None)
        self.other = User.objects.create_user(email="other-machines@example.invalid", password=None)
        self.guest = User.objects.create_user(email="technical-guest@example.invalid", password=None, is_guest=True)
        self.owned = [Machine.objects.create(owner=self.owner, title=f"Ficha {number}") for number in range(3)]
        self.other_machine = Machine.objects.create(owner=self.other, title="Ajena")
        Machine.objects.create(owner=self.guest, title="Borrador temporal")
        self.client.force_login(self.admin)

    def test_user_list_counts_real_owners_and_links_to_their_machines(self):
        user_list = self.client.get(reverse("admin:portal_user_changelist"))
        self.assertEqual(user_list.status_code, 200)
        href = reverse("admin:portal_machine_changelist") + "?" + urlencode({"owner__id__exact": self.owner.pk})
        self.assertContains(user_list, "3 fichas")
        self.assertContains(user_list, href)
        self.assertNotContains(user_list, self.guest.email)

        filtered = self.client.get(href)
        self.assertEqual(filtered.status_code, 200)
        for machine in self.owned:
            self.assertContains(filtered, machine.folio)
        self.assertNotContains(filtered, self.other_machine.folio)

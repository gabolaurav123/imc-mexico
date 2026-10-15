from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.admin_workspace import connections_workspace, people_workspace, person_workspace
from portal.models import AccountAccess, AccountRequest, Lead, Machine, MachineVersion, Submission, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AdminPeopleWorkspaceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff = User.objects.create_user(email="operator@example.invalid", is_staff=True)
        self.owner = User.objects.create_user(email="owner@example.invalid", first_name="Owner", phone="5550101")
        self.other = User.objects.create_user(email="other@example.invalid", first_name="Other")
        self.machine = Machine.objects.create(owner=self.owner, title="Owner draft")
        self.second_machine = Machine.objects.create(owner=self.owner, title="Owner pending", status="submitted")
        self.other_machine = Machine.objects.create(owner=self.other, title="Other machine")
        version = MachineVersion.objects.create(machine=self.second_machine, number=1, created_by=self.owner,
                                                data={"data": {}, "title": self.second_machine.title})
        Submission.objects.create(machine=self.second_machine, version=version, status="submitted")
        AccountAccess.objects.create(user=self.owner, event="login", connection_ip="198.51.100.11", device="desktop")
        Lead.objects.create(user=self.owner, machine=self.second_machine, name="Owner", email=self.owner.email,
                            message="Necesito una cotización.")
        AccountRequest.objects.create(user=self.owner, kind="export", detail="Necesito una copia de mis datos.")

    def grant(self, *codes):
        self.staff.user_permissions.set(Permission.objects.filter(content_type__app_label="portal", codename__in=codes))
        for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.staff.__dict__.pop(cache, None)
        # Keep the query guard below about the paginated workspace itself,
        # rather than Django's first permission-cache fill for this request.
        self.staff.get_all_permissions()
        device, _ = TOTPDevice.objects.get_or_create(user=self.staff, name="workspace", confirmed=True)
        self.staff.is_verified = lambda: True
        self.assertTrue(device.confirmed)

    def request(self, path, data=None):
        request = self.factory.get(path, data or {})
        request.user = self.staff
        return request

    def test_people_are_grouped_once_with_only_authorized_work_counts(self):
        self.grant("operate_platform", "view_user", "view_machine", "view_submission")
        with CaptureQueriesContext(connection) as queries:
            response = people_workspace(self.request("/operaciones/personas/"))
        body = response.content.decode()
        self.assertEqual(body.count("Owner draft"), 0)
        self.assertEqual(body.count("owner@example.invalid"), 1)
        self.assertIn(">2</td><td>1</td><td>1</td><td>1</td>", body)
        # The shared authenticated layout loads its notification counters too.
        # Keep the complete paginated response bounded, rather than issuing a
        # query for each person or each of their submissions.
        self.assertLessEqual(len(queries), 8)

    def test_person_detail_keeps_connections_separate_from_work_permissions(self):
        self.grant("operate_platform", "view_user", "view_machine", "view_submission")
        response = person_workspace(self.request(f"/operaciones/personas/{self.owner.pk}/"), self.owner.pk)
        body = response.content.decode()
        self.assertIn("Owner draft", body)
        self.assertIn("Owner pending", body)
        self.assertNotIn("198.51.100.11", body)

        self.grant("operate_platform", "view_user", "view_accountaccess")
        response = person_workspace(self.request(f"/operaciones/personas/{self.owner.pk}/"), self.owner.pk)
        body = response.content.decode()
        self.assertIn("198.51.100.11", body)
        self.assertIn("Conexiones", body)
        self.assertNotIn("Owner draft", body)

    def test_connections_requires_its_own_read_permission(self):
        self.grant("operate_platform", "view_user")
        with self.assertRaises(PermissionDenied):
            connections_workspace(self.request("/operaciones/conexiones/"))
        self.grant("operate_platform", "view_accountaccess")
        response = connections_workspace(self.request("/operaciones/conexiones/"))
        self.assertIn("198.51.100.11", response.content.decode())

    def test_person_history_keeps_leads_and_account_requests_behind_their_permissions(self):
        self.grant("operate_platform", "view_user")
        body = person_workspace(self.request(f"/operaciones/personas/{self.owner.pk}/"), self.owner.pk).content.decode()
        self.assertNotIn("Necesito una cotización.", body)
        self.assertNotIn("Necesito una copia de mis datos.", body)

        self.grant("operate_platform", "view_user", "view_lead", "view_accountrequest")
        body = person_workspace(self.request(f"/operaciones/personas/{self.owner.pk}/"), self.owner.pk).content.decode()
        self.assertIn("Historial de consultas", body)
        self.assertIn("Necesito una cotización.", body)
        self.assertIn("Solicitudes de la cuenta", body)
        self.assertIn("Necesito una copia de mis datos.", body)

    def test_person_work_histories_are_paginated_independently(self):
        for index in range(30):
            Machine.objects.create(owner=self.owner, title=f"Machine page {index}")
            Lead.objects.create(user=self.owner, name="Owner", email=self.owner.email,
                                message=f"Lead navigation {index}")
            AccountRequest.objects.create(user=self.owner, kind="export",
                                          detail=f"Account request navigation {index}")
        version = MachineVersion.objects.get(machine=self.second_machine, number=1)
        for _ in range(30):
            Submission.objects.create(machine=self.second_machine, version=version, status="submitted")
        self.grant("operate_platform", "view_user", "view_machine", "view_submission",
                   "view_lead", "view_accountrequest")
        response = person_workspace(self.request(
            f"/operaciones/personas/{self.owner.pk}/", {
                "machines_page": "2", "submissions_page": "2", "leads_page": "2",
                "account_requests_page": "2",
            }
        ), self.owner.pk)
        body = response.content.decode()
        self.assertIn('Página 2 de 2', body)
        self.assertIn('machines_page=1', body)
        self.assertIn('submissions_page=1', body)
        self.assertIn('leads_page=2', body)
        self.assertIn('account_requests_page=2', body)

    def test_person_leads_and_account_requests_are_paginated_independently(self):
        for index in range(30):
            Lead.objects.create(user=self.owner, name="Owner", email=self.owner.email,
                                message=f"Lead page {index}")
            AccountRequest.objects.create(user=self.owner, kind="export",
                                          detail=f"Account request page {index}")
        self.grant("operate_platform", "view_user", "view_lead", "view_accountrequest")
        response = person_workspace(self.request(
            f"/operaciones/personas/{self.owner.pk}/", {
                "machines_page": "1", "submissions_page": "1", "leads_page": "2",
                "account_requests_page": "2",
            }
        ), self.owner.pk)
        body = response.content.decode()
        self.assertIn("Lead page 0", body)
        self.assertIn("Account request page 0", body)
        self.assertIn('leads_page=1', body)
        self.assertIn('account_requests_page=1', body)

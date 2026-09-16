"""Operations datasets must obey each model permission as well as staff MFA."""
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from portal.models import AnalysisJob, Lead, Machine, MachineVersion, Submission, User


@override_settings(STAFF_MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class OperationsPermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="private-owner@example.invalid")
        self.operator = User.objects.create_user(email="restricted-staff@example.invalid", is_staff=True)
        self.machine = Machine.objects.create(owner=self.owner, title="PRIVATE-SUBMISSION-TITLE", status="submitted")
        version = MachineVersion.objects.create(machine=self.machine, number=1, created_by=self.owner,
                                               data={"data": {}, "title": self.machine.title})
        self.submission = Submission.objects.create(machine=self.machine, version=version)
        self.job_machine = Machine.objects.create(owner=self.owner, title="PRIVATE-JOB-TITLE")
        self.job = AnalysisJob.objects.create(machine=self.job_machine, requested_by=self.owner, revision=1,
            fingerprint="a" * 64, status="failed", error="PRIVATE-JOB-ERROR", input_tokens=101, output_tokens=22)
        self.lead = Lead.objects.create(name="PRIVATE-LEAD-NAME", email="private-lead@example.invalid", message="Private enquiry")
        self.permissions("operate_platform")

    def permissions(self, *names):
        self.operator.user_permissions.set(Permission.objects.filter(content_type__app_label="portal", codename__in=names))

    def login(self, user=None, verified=True):
        user = user or self.operator
        self.client.logout()
        self.client.force_login(user)
        if verified:
            device, _ = TOTPDevice.objects.get_or_create(user=user, name="IMC", defaults={"confirmed": True})
            session = self.client.session
            session[DEVICE_ID_SESSION_KEY] = device.persistent_id
            session.save()

    def get_operations(self):
        response = self.client.get("/operaciones/")
        self.assertEqual(response.status_code, 200)
        return response

    def test_operate_permission_alone_exposes_no_business_datasets_or_backup(self):
        self.login()
        with patch("portal.views.get_backup_status") as backup:
            response = self.get_operations()
        backup.assert_not_called()
        for dataset in ("leads", "jobs", "submissions"):
            self.assertEqual(list(response.context[dataset]), [])
        self.assertTrue(all(value is None for value in response.context["counts"].values()))
        self.assertIsNone(response.context["backup_status"])
        for value in (self.owner.email, self.lead.name, self.lead.email, self.machine.title, self.job_machine.title, self.job.error):
            self.assertNotContains(response, value)

    def test_publication_staff_cannot_read_leads_or_analysis_jobs(self):
        self.permissions("operate_platform", "view_machine", "view_machineversion", "view_asset", "view_publication",
                         "publish_machine", "view_submission", "view_user")
        self.login()
        response = self.get_operations()
        self.assertEqual(list(response.context["submissions"]), [self.submission])
        self.assertEqual(list(response.context["leads"]), [])
        self.assertEqual(list(response.context["jobs"]), [])
        for key in ("leads", "failed_jobs", "tokens"):
            self.assertIsNone(response.context["counts"][key])
        for value in (self.lead.name, self.lead.email, self.job_machine.title, self.job.error):
            self.assertNotContains(response, value)
        self.assertIsNone(response.context["backup_status"])

    def test_commercial_staff_can_read_leads_but_not_submissions_or_jobs(self):
        self.permissions("operate_platform", "view_lead", "change_lead", "view_machine", "view_user", "view_message")
        self.login()
        response = self.get_operations()
        self.assertEqual(list(response.context["leads"]), [self.lead])
        self.assertEqual(list(response.context["submissions"]), [])
        self.assertEqual(list(response.context["jobs"]), [])
        self.assertEqual(response.context["counts"]["leads"], 1)
        self.assertContains(response, self.lead.email)
        self.assertNotContains(response, self.machine.title)
        self.assertNotContains(response, self.job.error)

    def test_view_change_and_workflow_permissions_enable_only_their_datasets(self):
        cases = [("view_lead", "leads", self.lead), ("change_lead", "leads", self.lead),
                 ("view_analysisjob", "jobs", self.job), ("change_analysisjob", "jobs", self.job),
                 ("view_submission", "submissions", self.submission),
                 ("change_submission", "submissions", self.submission),
                 ("review_submission", "submissions", self.submission)]
        for permission, dataset, record in cases:
            with self.subTest(permission=permission):
                self.permissions("operate_platform", permission)
                self.login()
                response = self.get_operations()
                self.assertEqual(list(response.context[dataset]), [record])
                for other in {"leads", "jobs", "submissions"} - {dataset}:
                    self.assertEqual(list(response.context[other]), [])
                self.assertIsNone(response.context["backup_status"])
                self.assertIsNone(response.context["counts"]["users"])
                if dataset == "jobs":
                    self.assertEqual(response.context["counts"]["failed_jobs"], 1)
                    self.assertEqual(response.context["counts"]["tokens"], 123)

    def test_backup_status_requires_settings_read_or_change_permission(self):
        sample = {"available": False, "stale": False}
        for permission in ("view_platformsettings", "change_platformsettings"):
            with self.subTest(permission=permission):
                self.permissions("operate_platform", permission)
                self.login()
                with patch("portal.views.get_backup_status", return_value=sample) as backup:
                    response = self.get_operations()
                backup.assert_called_once_with()
                self.assertEqual(response.context["backup_status"], sample)
                self.assertEqual(list(response.context["leads"]), [])

    def test_create_permission_does_not_grant_read_and_revocation_applies_next_request(self):
        self.permissions("operate_platform", "add_lead")
        self.login()
        self.assertEqual(list(self.get_operations().context["leads"]), [])
        self.permissions("operate_platform", "view_lead")
        self.assertEqual(list(self.get_operations().context["leads"]), [self.lead])
        self.permissions("operate_platform")
        response = self.get_operations()
        self.assertEqual(list(response.context["leads"]), [])
        self.assertNotContains(response, self.lead.email)

    def test_model_permissions_do_not_replace_operations_gate_or_mfa(self):
        self.permissions("view_lead", "view_submission", "view_analysisjob")
        self.login()
        self.assertEqual(self.client.get("/operaciones/").status_code, 403)
        self.permissions("operate_platform", "view_lead", "view_submission", "view_analysisjob")
        self.login(verified=False)
        response = self.client.get("/operaciones/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/panel/seguridad/"))
        for value in (self.lead.email, self.machine.title, self.job.error):
            self.assertNotIn(value, response.content.decode())

    def test_verified_superuser_keeps_full_operations_access(self):
        admin = User.objects.create_superuser(email="full-admin@example.invalid")
        self.login(admin)
        with patch("portal.views.get_backup_status", return_value={"available": False, "stale": False}) as backup:
            response = self.get_operations()
        backup.assert_called_once_with()
        self.assertEqual(list(response.context["leads"]), [self.lead])
        self.assertEqual(list(response.context["jobs"]), [self.job])
        self.assertEqual(list(response.context["submissions"]), [self.submission])
        self.assertTrue(all(value is not None for value in response.context["counts"].values()))

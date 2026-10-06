"""Operational queue filters stay bounded and keep staff in the permitted queue."""
from django.test import TestCase, override_settings

from portal.models import Machine, MachineVersion, Submission, User


@override_settings(STAFF_MFA_REQUIRED=False)
class OperationsWorkspaceTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(email="workspace-admin@example.invalid")
        self.owner = User.objects.create_user(email="workspace-owner@example.invalid")
        self.client.force_login(self.staff)
        self.submissions = {}
        for number, status in enumerate(("submitted", "in_review", "changes_requested", "approved"), start=1):
            machine = Machine.objects.create(owner=self.owner, title=f"Queue {status}", status=status)
            version = MachineVersion.objects.create(machine=machine, number=1, created_by=self.owner,
                data={"data": {}, "title": machine.title})
            self.submissions[status] = Submission.objects.create(machine=machine, version=version, status=status)

    def test_quick_queue_filters_only_use_known_workflow_groups(self):
        response = self.client.get("/operaciones/", {"queue": "review"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["submission_queue"], "review")
        self.assertEqual(set(response.context["submissions"]), {
            self.submissions["submitted"], self.submissions["in_review"],
        })

        response = self.client.get("/operaciones/", {"queue": "unknown", "status": "invalid"})
        self.assertEqual(response.context["submission_queue"], "")
        self.assertEqual(set(response.context["submissions"]), set(self.submissions.values()))

    def test_filter_controls_are_visible_and_keep_the_active_quick_view(self):
        response = self.client.get("/operaciones/", {"queue": "changes", "q": "Queue"})
        self.assertContains(response, "POR ATENDER")
        self.assertContains(response, "Con cambios solicitados")
        self.assertContains(response, 'name="queue" value="changes"')
        self.assertContains(response, "Base técnica")

    def test_reset_links_remove_query_parameters_and_filter_labels_are_visible(self):
        response = self.client.get("/operaciones/", {"queue": "changes", "q": "Queue"})
        self.assertContains(response, 'href="/operaciones/#solicitudes"')
        self.assertContains(response, '<label for="review-search">Buscar solicitudes</label>')
        self.assertContains(response, '<label for="review-status">Estado</label>')

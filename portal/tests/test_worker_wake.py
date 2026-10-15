import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from portal.auth_views import activation_email
from portal.management.commands import runworker
from portal.models import Consent, Machine, PlatformSettings, User
from portal.processing import enqueue_analysis, ingest_asset
from portal.services import _notify
from portal.worker_wake import WorkerWake, wake_worker_after_commit


class WorkerWakeTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="imc-worker-wake-")
        self.addCleanup(self.directory.cleanup)
        self.wake = WorkerWake(Path(self.directory.name) / "wake")

    def test_signal_changes_token_and_wait_observes_it_without_database_access(self):
        before = self.wake.token()
        self.assertTrue(self.wake.signal())
        self.assertNotEqual(self.wake.token(), before)
        self.assertTrue(self.wake.wait_for_change(before, 0, check_interval=0.5))

    def test_wake_is_deferred_until_the_surrounding_transaction_commits(self):
        with patch.dict(os.environ, {"WORKER_WAKE_FILE": str(self.wake.path)}):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                wake_worker_after_commit()
                self.assertIsNone(self.wake.token())
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
        self.assertIsNotNone(self.wake.token())

    def test_timing_options_preserve_a_short_local_wake_check(self):
        self.assertEqual(runworker._seconds(None, "NOT_SET", 3, minimum=1), 3)
        self.assertEqual(runworker._seconds("broken", "NOT_SET", 3, minimum=1), 3)
        self.assertEqual(runworker._seconds("nan", "NOT_SET", 3, minimum=1), 3)
        self.assertEqual(runworker._seconds("inf", "NOT_SET", 3, minimum=1), 3)
        self.assertEqual(runworker._seconds(9, "NOT_SET", 3, minimum=1, maximum=1), 1)

    def test_idle_cycle_waits_locally_after_closing_connections(self):
        command = runworker.Command()

        class StopAfterWait:
            def token(self):
                return "unchanged"

            def wait_for_change(self, token, timeout, **kwargs):
                self.called = (token, timeout, kwargs)
                command.stopping = True
                return False

        wake = StopAfterWait()
        with patch.object(runworker, "WorkerWake", return_value=wake), \
             patch.object(runworker.signal, "signal"), \
             patch.object(runworker, "process_next_job", return_value=False) as next_job, \
             patch.object(runworker, "process_notifications", return_value=0) as notifications, \
             patch.object(runworker, "purge_expired_accesses"), \
             patch.object(runworker, "purge_expired_guest_drafts"), \
             patch.object(runworker.connections, "close_all") as close_all:
            command.handle(once=False, poll=3, idle_backoff_max=900, wake_check=0.5, retry_poll_max=15)
        next_job.assert_called_once_with()
        notifications.assert_called_once_with()
        close_all.assert_called_once_with()
        self.assertEqual(wake.called[0:2], ("unchanged", 3))
        self.assertEqual(wake.called[2]["check_interval"], 0.5)


@override_settings(OPENAI_API_KEY="test-not-a-real-key", OPENAI_MODEL="gpt-4.1-mini",
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class QueueWakeIntegrationTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory(prefix="imc-worker-queue-")
        self.addCleanup(self.media.cleanup)
        self.settings = override_settings(MEDIA_ROOT=self.media.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.user = User.objects.create_user(email="wake@example.com", password="tests-only-pass-4821")
        self.machine = Machine.objects.create(owner=self.user, title="Equipo", data={"brand": "IMC"})
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=300000)
        Consent.objects.create(user=self.user, machine=self.machine, kind="ai", granted=True)

    def asset(self):
        payload = io.BytesIO()
        Image.new("RGB", (120, 80), "navy").save(payload, format="JPEG")
        return ingest_asset(self.machine, self.user, SimpleUploadedFile("photo.jpg", payload.getvalue(), content_type="image/jpeg"))

    def test_analysis_enqueue_registers_a_post_commit_wake(self):
        with patch("portal.processing.wake_worker_after_commit") as wake:
            first = enqueue_analysis(self.machine, self.user, [str(self.asset().pk)])
            duplicate = enqueue_analysis(self.machine, self.user, [str(self.machine.assets.first().pk)])
        self.assertEqual(first.pk, duplicate.pk)
        self.assertEqual(wake.call_count, 2)

    def test_email_outboxes_register_a_post_commit_wake(self):
        with patch("portal.worker_wake.wake_worker_after_commit") as wake:
            activation_email(self.user, "recovery")
            _notify(self.user, self.machine, "reply", "Asunto", "Contenido")
        self.assertEqual(wake.call_count, 2)

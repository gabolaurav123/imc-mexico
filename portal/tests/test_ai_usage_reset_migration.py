"""The deployment resets allowances once and preserves durable analysis history."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class AIUsageResetMigrationTests(TransactionTestCase):
    previous = [("portal", "0021_ai_user_daily_limit_20")]
    target = [("portal", "0022_ai_usage_reset_50")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(self.previous)
        self.old_apps = executor.loader.project_state(self.previous).apps

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.target)
        return executor.loader.project_state(self.target).apps

    def test_existing_limits_reset_once_without_losing_jobs_or_custom_token_settings(self):
        config = self.old_apps.get_model("portal", "PlatformSettings")
        config.objects.create(pk=1, ai_user_daily_limit=7, ai_global_daily_limit=83,
                              ai_daily_token_limit=456_789, ai_max_attempts=3, ai_enabled=True)
        owner = self.old_apps.get_model("portal", "User").objects.create(email="migration-reset@example.invalid")
        machine = self.old_apps.get_model("portal", "Machine").objects.create(owner=owner)
        job_model = self.old_apps.get_model("portal", "AnalysisJob")
        before_job = job_model.objects.create(machine=machine, requested_by=owner, revision=1,
            fingerprint="historical-paid-analysis", status="completed", input_tokens=1234, output_tokens=567,
            attempts=2, finished_at=timezone.now(), result={"usage": {"input_tokens": 1234, "output_tokens": 567}})
        queued_job = job_model.objects.create(machine=machine, requested_by=owner, revision=1,
            fingerprint="reserved-analysis", status="queued", reserved_tokens=90_000)
        event = self.old_apps.get_model("portal", "AuditEvent").objects.create(actor=owner,
            action="analysis.completed", object_type="AnalysisJob", object_id=str(before_job.pk), metadata={"kept": True})
        before_data = job_model.objects.get(pk=before_job.pk).__dict__.copy()
        before_data.pop("_state")
        start = timezone.now()
        apps = self.migrate_forward()
        end = timezone.now()
        current_config = apps.get_model("portal", "PlatformSettings")
        current = current_config.objects.get(pk=1)
        self.assertEqual((current.ai_user_daily_limit, current.ai_global_daily_limit), (50, 50))
        self.assertEqual((current.ai_daily_token_limit, current.ai_max_attempts, current.ai_enabled), (456_789, 3, True))
        self.assertLessEqual(start, current.ai_usage_reset_at)
        self.assertLessEqual(current.ai_usage_reset_at, end)
        current_jobs = apps.get_model("portal", "AnalysisJob")
        after_data = current_jobs.objects.get(pk=before_job.pk).__dict__.copy()
        after_data.pop("_state")
        self.assertEqual(after_data, before_data)
        self.assertEqual(current_jobs.objects.count(), 2)
        self.assertEqual(current_jobs.objects.get(pk=queued_job.pk).reserved_tokens, 90_000)
        self.assertEqual(apps.get_model("portal", "AuditEvent").objects.get(pk=event.pk).metadata, {"kept": True})

        # Normal later deploys must not silently grant another allowance or undo edits.
        original_reset = current.ai_usage_reset_at
        current.ai_user_daily_limit, current.ai_global_daily_limit = 12, 34
        current.save(update_fields=["ai_user_daily_limit", "ai_global_daily_limit"])
        self.migrate_forward()
        current.refresh_from_db()
        self.assertEqual((current.ai_user_daily_limit, current.ai_global_daily_limit), (12, 34))
        self.assertEqual(current.ai_usage_reset_at, original_reset)

    def test_new_configuration_uses_fifty_defaults_without_a_perpetual_reset(self):
        apps = self.migrate_forward()
        configuration = apps.get_model("portal", "PlatformSettings")
        self.assertFalse(configuration.objects.exists())
        new = configuration.objects.create(pk=1)
        self.assertEqual((new.ai_user_daily_limit, new.ai_global_daily_limit), (50, 50))
        self.assertIsNone(new.ai_usage_reset_at)
        self.assertEqual((new.ai_daily_token_limit, new.ai_max_attempts), (200_000, 2))
        self.assertFalse(configuration._meta.get_field("ai_usage_reset_at").editable)

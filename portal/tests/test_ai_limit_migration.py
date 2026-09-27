from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from portal.models import PlatformSettings


class AILimitDefaultTests(SimpleTestCase):
    def test_new_configuration_allows_twenty_jobs_without_changing_global_budgets(self):
        configuration = PlatformSettings()
        self.assertEqual(configuration.ai_user_daily_limit, 20)
        self.assertEqual(configuration.ai_global_daily_limit, 100)
        self.assertEqual(configuration.ai_daily_token_limit, 200000)
        self.assertEqual(configuration.ai_max_attempts, 2)


class AILimitMigrationTests(TransactionTestCase):
    previous = [("portal", "0020_prepared_share")]
    target = [("portal", "0021_ai_user_daily_limit_20")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(self.previous)
        self.old_configuration = executor.loader.project_state(self.previous).apps.get_model(
            "portal", "PlatformSettings",
        )

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.target)
        return executor.loader.project_state(self.target).apps.get_model("portal", "PlatformSettings")

    def test_existing_default_increases_once_and_other_settings_remain_unchanged(self):
        self.old_configuration.objects.create(
            pk=1, ai_user_daily_limit=10, ai_enabled=True,
            ai_global_daily_limit=83, ai_daily_token_limit=456789, ai_max_attempts=3,
        )
        configuration_model = self.migrate_forward()
        configuration = configuration_model.objects.get(pk=1)
        self.assertEqual(configuration.ai_user_daily_limit, 20)
        self.assertTrue(configuration.ai_enabled)
        self.assertEqual(configuration.ai_global_daily_limit, 83)
        self.assertEqual(configuration.ai_daily_token_limit, 456789)
        self.assertEqual(configuration.ai_max_attempts, 3)
        self.assertEqual(configuration_model().ai_user_daily_limit, 20)

        configuration.ai_user_daily_limit = 7
        configuration.save(update_fields=["ai_user_daily_limit"])
        self.migrate_forward()
        configuration.refresh_from_db()
        self.assertEqual(configuration.ai_user_daily_limit, 7)

    def test_existing_custom_limits_are_preserved(self):
        for limit in (0, 7, 20, 40):
            with self.subTest(limit=limit):
                MigrationExecutor(connection).migrate(self.previous)
                self.old_configuration.objects.update_or_create(
                    pk=1, defaults={"ai_user_daily_limit": limit},
                )
                configuration_model = self.migrate_forward()
                self.assertEqual(configuration_model.objects.get(pk=1).ai_user_daily_limit, limit)

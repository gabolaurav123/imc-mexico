from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RegistrationMigrationTests(TransactionTestCase):
    def test_existing_installation_opens_without_changing_other_settings(self):
        previous = [('portal', '0005_optional_acquisition_analytics')]
        current = [('portal', '0006_open_user_registration')]
        executor = MigrationExecutor(connection)
        executor.migrate(previous)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(current))
        old_apps = executor.loader.project_state(previous).apps
        old_configuration = old_apps.get_model('portal', 'PlatformSettings')
        old_configuration.objects.create(
            pk=1, registration_open=False, legal_validated=False,
            ai_enabled=True, contact_email='contact@example.com',
            analytics_enabled=True, analytics_require_consent=True,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        new_apps = executor.loader.project_state(current).apps
        configuration_model = new_apps.get_model('portal', 'PlatformSettings')
        configuration = configuration_model.objects.get(pk=1)
        self.assertTrue(configuration.registration_open)
        self.assertFalse(configuration.legal_validated)
        self.assertTrue(configuration.ai_enabled)
        self.assertTrue(configuration.analytics_enabled)
        self.assertTrue(configuration.analytics_require_consent)
        self.assertEqual(configuration.contact_email, 'contact@example.com')
        self.assertTrue(configuration_model().registration_open)

        # Future deploys must respect an administrator pausing registrations.
        configuration.registration_open = False
        configuration.save(update_fields=['registration_open'])
        MigrationExecutor(connection).migrate(current)
        configuration.refresh_from_db()
        self.assertFalse(configuration.registration_open)

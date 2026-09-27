from django.db import migrations, models


def increase_default_user_limit(apps, schema_editor):
    configuration = apps.get_model("portal", "PlatformSettings")
    configuration.objects.using(schema_editor.connection.alias).filter(
        pk=1, ai_user_daily_limit=10,
    ).update(ai_user_daily_limit=20)


class Migration(migrations.Migration):
    dependencies = [("portal", "0020_prepared_share")]

    operations = [
        migrations.AlterField(
            model_name="platformsettings",
            name="ai_user_daily_limit",
            field=models.PositiveIntegerField(default=20, verbose_name="trabajos por usuario/día"),
        ),
        # Preserve custom limits. A rollback cannot distinguish a migrated 20
        # from an administrator's chosen 20, so it must leave stored values alone.
        migrations.RunPython(increase_default_user_limit, migrations.RunPython.noop),
    ]

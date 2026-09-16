from django.db import migrations, models


def open_registration(apps, schema_editor):
    configuration = apps.get_model('portal', 'PlatformSettings')
    configuration.objects.using(schema_editor.connection.alias).filter(pk=1).update(
        registration_open=True,
    )


def close_registration(apps, schema_editor):
    configuration = apps.get_model('portal', 'PlatformSettings')
    configuration.objects.using(schema_editor.connection.alias).filter(pk=1).update(
        registration_open=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('portal', '0005_optional_acquisition_analytics'),
    ]

    operations = [
        migrations.AlterField(
            model_name='platformsettings',
            name='registration_open',
            field=models.BooleanField(
                default=True,
                help_text='Permite crear cuentas y preparar borradores. Puedes desactivarlo para pausar nuevos registros; no concede permisos de anunciante ni de administración.',
                verbose_name='registro público abierto',
            ),
        ),
        # Open existing installations once, without changing the legal review,
        # AI configuration or any account permissions. Later admin choices persist.
        migrations.RunPython(open_registration, close_registration),
    ]

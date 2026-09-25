from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0018_integration_manual_metadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='publication',
            name='imc_asset_ids',
            field=models.JSONField(blank=True, default=list, verbose_name='medios seleccionados para IMC'),
        ),
        migrations.AddField(
            model_name='publication',
            name='imc_selection_version',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='imc_media_selections', to='portal.machineversion',
                                    verbose_name='versión de medios IMC'),
        ),
    ]

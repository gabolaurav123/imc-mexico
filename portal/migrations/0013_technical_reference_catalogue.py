import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portal", "0012_version_search_indexes")]

    operations = [
        migrations.AddField(
            model_name="technicalreference",
            name="equipment_model",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="technical_references", to="portal.equipmentmodel",
                                    verbose_name="modelo del catálogo"),
        ),
    ]

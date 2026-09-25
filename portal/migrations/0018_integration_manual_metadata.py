# Generated manually to preserve the immutable delivery payload while keeping
# a separate operator audit trail for the manual IMC workflow.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0017_guest_drafts'),
    ]

    operations = [
        migrations.AddField(
            model_name='integrationdelivery',
            name='manual_metadata',
            field=models.JSONField(blank=True, default=dict, verbose_name='bitácora manual de preparación'),
        ),
    ]

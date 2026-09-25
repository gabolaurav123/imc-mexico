import django.db.models.deletion
import portal.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portal", "0019_publication_imc_media_selection"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name="PreparedShare",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("code", models.CharField(default=portal.models.prepared_share_code, editable=False, max_length=20, unique=True)),
            ("enabled", models.BooleanField(default=False)),
            ("revision", models.PositiveIntegerField()),
            ("snapshot", models.JSONField(default=dict)),
            ("include_serial", models.BooleanField(default=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("authorized_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("machine", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="prepared_share", to="portal.machine")),
        ],
        options={"verbose_name": "enlace de ficha preparada", "verbose_name_plural": "enlaces de fichas preparadas"},
    )]

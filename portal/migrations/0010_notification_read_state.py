from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portal", "0009_account_access_history")]

    operations = [
        migrations.AddField(
            model_name="notification", name="read_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="leída el"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "channel", "status", "read_at"], name="notification_inbox_unread"),
        ),
    ]

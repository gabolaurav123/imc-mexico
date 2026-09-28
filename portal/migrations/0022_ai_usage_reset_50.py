from django.db import migrations, models, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone


def reset_ai_usage(apps, schema_editor):
    """One requested reset; retain jobs, consumption, leases and token limits."""
    configuration_model = apps.get_model("portal", "PlatformSettings")
    job_model = apps.get_model("portal", "AnalysisJob")
    alias = schema_editor.connection.alias
    with transaction.atomic(using=alias):
        configurations = configuration_model.objects.using(alias)
        configuration = configurations.select_for_update().filter(pk=1).first()
        if configuration is None:
            # New installations use the new defaults when their singleton is
            # created normally; no historical quota exists to reset here.
            print("AI quota reset: no_existing_configuration user_default=50 global_default=50")
            return
        reset_at = timezone.now()
        configuration.ai_user_daily_limit = 50
        configuration.ai_global_daily_limit = 50
        configuration.ai_usage_reset_at = reset_at
        configuration.save(using=alias, update_fields=[
            "ai_user_daily_limit", "ai_global_daily_limit", "ai_usage_reset_at"])
        active = Q(status__in=["queued", "running"])
        # Historical migration models keep this independent of future runtime
        # helpers. In-flight work can finish during deployment and still counts.
        totals = job_model.objects.using(alias).filter(
            Q(created_at__gte=reset_at) | Q(finished_at__gte=reset_at) | active,
        ).aggregate(jobs_since_reset=Count("pk", filter=Q(created_at__gte=reset_at)),
                    active_jobs=Count("pk", filter=active),
                    used_in=Sum("input_tokens"), used_out=Sum("output_tokens"),
                    reserved=Sum("reserved_tokens"))
        used = (totals["used_in"] or 0) + (totals["used_out"] or 0)
        reserved = totals["reserved"] or 0
        print("AI quota reset: "
              f"at={reset_at.isoformat()} user_limit=50 global_limit=50 "
              f"token_limit={configuration.ai_daily_token_limit} "
              f"jobs_since_reset={totals['jobs_since_reset']} active_jobs={totals['active_jobs']} "
              f"used_tokens={used} reserved_tokens={reserved} "
              f"available_tokens={max(0, configuration.ai_daily_token_limit - used - reserved)}")


class Migration(migrations.Migration):
    dependencies = [("portal", "0021_ai_user_daily_limit_20")]

    operations = [
        migrations.AddField(
            model_name="platformsettings", name="ai_usage_reset_at",
            field=models.DateTimeField("reinicio de cuota IA", null=True, blank=True, editable=False),
        ),
        migrations.AlterField(
            model_name="platformsettings", name="ai_user_daily_limit",
            field=models.PositiveIntegerField(default=50, verbose_name="trabajos por usuario/día"),
        ),
        migrations.AlterField(
            model_name="platformsettings", name="ai_global_daily_limit",
            field=models.PositiveIntegerField(default=50, verbose_name="trabajos globales/día"),
        ),
        # Rolling back cannot identify later administrative changes. Preserve
        # stored limits and all usage rather than inventing a reverse reset.
        migrations.RunPython(reset_ai_usage, migrations.RunPython.noop),
    ]

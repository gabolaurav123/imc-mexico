"""Daily admission and token budgets without rewriting the usage history."""
from django.db.models import Q
from django.utils import timezone

from .models import AnalysisJob


def quota_window_start(limits, now=None):
    """Use the platform's local day, shortened by an explicit past reset."""
    now = now or timezone.now()
    local_now = timezone.localtime(now, timezone.get_default_timezone())
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    reset = limits.ai_usage_reset_at
    # A mistaken future timestamp must not hide current consumption.
    if reset is not None and start < reset <= now:
        return reset
    return start


def daily_quota_jobs(limits, now=None):
    """Count admissions in the current quota window, including preflights."""
    return AnalysisJob.objects.filter(created_at__gte=quota_window_start(limits, now))


def daily_budget_jobs(limits, now=None):
    """Keep active reservations and work finishing after a reset or midnight.

    A carried job remains charged in full: its cumulative measured consumption
    and reservations are never erased or presented as newly unused capacity.
    """
    start = quota_window_start(limits, now)
    return AnalysisJob.objects.filter(
        Q(created_at__gte=start) | Q(finished_at__gte=start) | Q(status__in=["queued", "running"]))

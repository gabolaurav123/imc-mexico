"""Recipient-only in-app inbox. Reading a page never acknowledges an alert."""
import re

from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .models import Notification


AUTH_KINDS = ("activation", "admin_activation", "verify", "recovery")


def visible_notifications(user):
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return Notification.objects.none()
    return Notification.objects.filter(user=user, channel="in_app", status="sent").exclude(
        kind__in=AUTH_KINDS).order_by("-created_at", "-pk")


def unread_state(user):
    unread = visible_notifications(user).filter(read_at__isnull=True)
    return unread.count(), unread.first()


def _excerpt(text, limit):
    # Payload is plain text; callers must render it as text, never as HTML.
    text = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", strip_tags(str(text or "")))).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def notification_summary(user):
    count, latest = unread_state(user)
    return {"viewer_id": str(user.pk), "unread_count": count, "latest": {
        "id": latest.pk,
        "subject": _excerpt(latest.subject, 180),
        "body": _excerpt(latest.body, 240),
        "url": reverse("notification_detail", args=[latest.pk]),
    } if latest else None}


def mark_notification_read(user, pk):
    visible = visible_notifications(user)
    notice = get_object_or_404(visible, pk=pk)
    # Preserve the first acknowledgment if another request already marked it.
    visible.filter(pk=notice.pk, read_at__isnull=True).update(read_at=timezone.now())
    return notice.pk


def mark_all_notifications_read(user):
    return visible_notifications(user).filter(read_at__isnull=True).update(read_at=timezone.now())


def notification_target(notice, user):
    machine = notice.machine
    if not machine or machine.owner_id != user.pk or machine.deleted_at is not None:
        return "", ""
    if notice.kind in {"reply", "review"}:
        return f"/panel/mensajes/?maquinaria={machine.pk}", "Ver conversación"
    return reverse("machine_wizard", args=[machine.pk]), "Ver maquinaria"

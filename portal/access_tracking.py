"""Minimal, expiring access history. Network headers never grant trust or access."""
import ipaddress
import logging

from django.contrib.auth.signals import user_logged_in
from django.db import DatabaseError, transaction
from django.dispatch import receiver
from django.utils import timezone

from .analytics import device_category
from .models import AccountAccess

log = logging.getLogger(__name__)
SESSION_MARKER = "imc_security_access_at"


def purge_expired_accesses():
    return AccountAccess.objects.filter(expires_at__lte=timezone.now()).delete()[0]


def _ip(value):
    try:
        text = str(value or "").strip()
        if len(text) > 45 or "%" in text:
            return None
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _forwarded_ip(value):
    """Only retain a syntactically valid candidate; it remains explicitly unverified."""
    text = str(value or "")
    if not text or len(text) > 512:
        return None
    parts = text.split(",")
    if len(parts) > 10:
        return None
    addresses = [_ip(part) for part in parts]
    return addresses[0] if all(addresses) else None


def record_access(request, user, event):
    if not request or not getattr(user, "is_authenticated", False) or not user.is_active:
        return None
    if event not in {"login", "session", "mfa_verified"}:
        raise ValueError("Unsupported account access event")
    try:
        # A savepoint prevents optional history failures from invalidating login.
        with transaction.atomic():
            now = timezone.now()
            purge_expired_accesses()
            entry = AccountAccess.objects.create(
                user=user, event=event,
                connection_ip=_ip(request.META.get("REMOTE_ADDR")),
                forwarded_ip=_forwarded_ip(request.META.get("HTTP_X_FORWARDED_FOR")),
                device=device_category(request.META.get("HTTP_USER_AGENT", "")),
            )
        request.session[SESSION_MARKER] = now.timestamp()
        return entry
    except DatabaseError:
        # Never log credentials, addresses, header text or the database error body.
        log.warning("No se pudo registrar el historial de acceso de la cuenta.")
        return None


@receiver(user_logged_in, dispatch_uid="imc.account_access.login")
def account_logged_in(sender, request, user, **kwargs):
    record_access(request, user, "login")


class AccountAccessMiddleware:
    """Observe existing authenticated sessions approximately once per day."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request.user, "is_authenticated", False) and request.user.is_active:
            last = request.session.get(SESSION_MARKER)
            now = timezone.now().timestamp()
            if not isinstance(last, (int, float)) or isinstance(last, bool) or not 0 <= now - last < 86400:
                record_access(request, request.user, "session")
        return self.get_response(request)

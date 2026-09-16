from datetime import timedelta
import hashlib
import logging
import re
from functools import wraps
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme


def is_management_user(user):
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


def management_home(user):
    if not is_management_user(user):
        return '/panel/'
    return '/operaciones/' if user.has_perm('portal.operate_platform') else '/admin/'


def needs_management_mfa(user):
    # A freshly authenticated User has not yet passed through OTPMiddleware.
    return (is_management_user(user) and settings.STAFF_MFA_REQUIRED
            and not getattr(user, 'is_verified', lambda: False)())


def safe_next_url(request, value, fallback=None):
    fallback = fallback or management_home(request.user)
    if not isinstance(value, str) or not value or len(value) > 2048:
        return fallback
    if not url_has_allowed_host_and_scheme(value, {request.get_host()}, require_https=not settings.DEBUG):
        return fallback
    parsed = urlsplit(value)
    if not parsed.path.startswith('/') or parsed.path.startswith('//'):
        return fallback
    # Normalize same-host absolute links to local paths; never return an origin.
    return urlunsplit(('', '', parsed.path, parsed.query, parsed.fragment))


def login_destination(request, requested=None):
    destination = safe_next_url(request, requested)
    parsed = urlsplit(destination)
    if parsed.path.startswith('/admin/') and not is_management_user(request.user):
        # Django admin sends non-staff sessions back to its login. Returning the
        # same next value from our authenticated login would create a loop.
        destination = '/panel/'
        parsed = urlsplit(destination)
    if parsed.path in {'/iniciar-sesion/', '/registro/'}:
        destination = management_home(request.user)
        parsed = urlsplit(destination)
    if (is_management_user(request.user) and parsed.path == '/panel/'
            and parse_qs(parsed.query).get('modo') != ['anunciante']):
        destination = management_home(request.user)
        parsed = urlsplit(destination)
    if needs_management_mfa(request.user) and parsed.path.startswith(('/admin/', '/operaciones/')):
        return '/panel/seguridad/?' + urlencode({'next': destination}, safe='/')
    return destination


def redact_sensitive_urls(value):
    text=str(value)
    text=re.sub(r'(/activar/)[^/\s?#]+/[^/\s?#]+/?',r'\1[redacted]/[redacted]/',text,flags=re.IGNORECASE)
    text=re.sub(r'([?&](?:token|reset_token|activation_token)=)[^&\s]+',r'\1[redacted]',text,flags=re.IGNORECASE)
    return text


class RedactingFormatter(logging.Formatter):
    """Sanitize the entire rendered log, including exception and stack information."""
    def format(self,record):
        return redact_sensitive_urls(super().format(record))

def throttle(request,scope,limit=10,seconds=900,identity=None):
    from .models import RateLimit
    identity = identity or request.META.get('REMOTE_ADDR','unknown')
    key=hashlib.sha256(f'{settings.SECRET_KEY}:{scope}:{identity}'.encode()).hexdigest()
    now=timezone.now()
    with transaction.atomic():
        row,_=RateLimit.objects.select_for_update().get_or_create(key=key,defaults={'window_start':now})
        if row.window_start < now-timedelta(seconds=seconds): row.count=0; row.window_start=now
        if row.count >= limit:return False
        row.count+=1
        row.save(update_fields=['count','window_start'])
    return True

def operator_required(permission='portal.operate_platform'):
    def decorator(fn):
        @wraps(fn)
        def wrapped(request,*args,**kwargs):
            if not request.user.is_authenticated or not request.user.is_staff or not request.user.has_perm(permission):raise PermissionDenied
            if settings.STAFF_MFA_REQUIRED and not request.user.is_verified():raise PermissionDenied
            return fn(request,*args,**kwargs)
        return wrapped
    return decorator

def staff_authorized(user):
    return user.is_authenticated and user.is_staff and user.has_perm('portal.operate_platform') and (not settings.STAFF_MFA_REQUIRED or user.is_verified())

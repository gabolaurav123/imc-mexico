from datetime import timedelta
import hashlib
from functools import wraps
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from .models import RateLimit

def throttle(request,scope,limit=10,seconds=900,identity=None):
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

from django.conf import settings
from django.db import OperationalError, ProgrammingError, transaction

def site_context(request):
    from .models import PlatformSettings
    from .security import is_management_user, management_home, needs_management_mfa
    try:
        platform_settings = PlatformSettings.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        platform_settings = None
    from .analytics import prepare_request
    prepare_request(request)
    management_user=is_management_user(request.user)
    from .notifications import unread_state
    try:
        with transaction.atomic():
            notification_unread_count,notification_latest_unread=unread_state(request.user)
    except (OperationalError,ProgrammingError):
        # During a rolling schema upgrade the rest of the page remains usable.
        notification_unread_count,notification_latest_unread=0,None
    advertiser_mode=management_user and (
        (request.path=='/panel/' and request.GET.get('modo')=='anunciante')
        or request.path.startswith(('/panel/maquinarias/','/panel/solicitudes/','/panel/mensajes/')))
    return {'settings_context':platform_settings,'public_url':settings.PUBLIC_URL,'debug':settings.DEBUG,'analytics_settings':request.analytics_settings,
            'is_management_user':management_user,'management_url':management_home(request.user),
            'needs_management_mfa':needs_management_mfa(request.user),'is_advertiser_mode':advertiser_mode,
            'notification_unread_count':notification_unread_count,'notification_latest_unread':notification_latest_unread}

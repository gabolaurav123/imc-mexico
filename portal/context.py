from django.conf import settings
from django.db import OperationalError, ProgrammingError

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
    advertiser_mode=management_user and (
        (request.path=='/panel/' and request.GET.get('modo')=='anunciante')
        or request.path.startswith(('/panel/maquinarias/','/panel/solicitudes/','/panel/mensajes/')))
    return {'settings_context':platform_settings,'public_url':settings.PUBLIC_URL,'debug':settings.DEBUG,'analytics_settings':request.analytics_settings,
            'is_management_user':management_user,'management_url':management_home(request.user),
            'needs_management_mfa':needs_management_mfa(request.user),'is_advertiser_mode':advertiser_mode}

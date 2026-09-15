from django.conf import settings
from django.db import OperationalError, ProgrammingError

def site_context(request):
    from .models import PlatformSettings
    try:
        platform_settings = PlatformSettings.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        platform_settings = None
    from .analytics import prepare_request
    prepare_request(request)
    return {'settings_context':platform_settings,'public_url':settings.PUBLIC_URL,'debug':settings.DEBUG,'analytics_settings':request.analytics_settings}

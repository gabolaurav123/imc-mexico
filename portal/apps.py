from django.apps import AppConfig


class PortalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "portal"
    verbose_name = "IMC · Maquinaria"

    def ready(self):
        from . import access_tracking  # noqa: F401 — registers successful-login signal

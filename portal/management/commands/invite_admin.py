from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from portal.models import User
from portal.auth_views import activation_email
from portal.services import audit


class Command(BaseCommand):
    help = "Crea la cuenta administrativa solicitada y encola su enlace privado de activación."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--resend", action="store_true", help="Volver a enviar la activación de una cuenta todavía sin contraseña.")

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("El correo no es válido.") from exc
        base_url = getattr(settings, "PUBLIC_URL", "").rstrip("/")
        parsed = urlsplit(base_url)
        if not parsed.netloc or (parsed.scheme != "https" and not settings.DEBUG):
            raise CommandError("Configura PUBLIC_URL con la dirección HTTPS publicada antes de invitar.")
        user, created = User.objects.get_or_create(email=email, defaults={"username": email, "is_staff": True, "is_superuser": True, "is_active": True})
        if not created and (not user.is_superuser or not user.is_staff):
            raise CommandError("El correo ya tiene una cuenta normal. No se eleva automáticamente: revisa la identidad y sus permisos.")
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            audit(None, "admin.invited", user)
        if user.has_usable_password():
            self.stdout.write("La cuenta administrativa ya está activada. No se modificó el acceso.")
            return
        if not created and not options["resend"]:
            self.stdout.write("La invitación ya existe. Usa --resend únicamente si necesitas otro correo de activación.")
            return
        activation_email(user, "admin_activation")
        self.stdout.write(self.style.SUCCESS("Cuenta preparada; correo de activación en cola. No se ha confirmado su recepción."))

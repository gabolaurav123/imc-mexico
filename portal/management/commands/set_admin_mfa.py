"""Audited, per-account MFA policy; never changes roles or authenticator keys."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from portal.models import User
from portal.services import audit


class Command(BaseCommand):
    help = "Activa o desactiva la exigencia de autenticador para una cuenta administrativa existente."

    def add_arguments(self, parser):
        parser.add_argument("email")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--enable", action="store_true")
        mode.add_argument("--disable", action="store_true")
        parser.add_argument("--reason", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        reason = options["reason"].strip()
        if not reason or len(reason) > 1000:
            raise CommandError("Indica un motivo de entre 1 y 1000 caracteres.")
        try:
            user = User.objects.select_for_update().get(email__iexact=options["email"].strip())
        except User.DoesNotExist as exc:
            raise CommandError("La cuenta no existe.") from exc
        if not user.is_active or not user.is_staff or user.is_guest:
            raise CommandError("Se requiere una cuenta administrativa activa; no se modificaron permisos.")
        required = bool(options["enable"])
        if user.management_mfa_required == required:
            self.stdout.write("La cuenta ya tiene esta configuración de autenticador.")
            return
        user.management_mfa_required = required
        user.save(update_fields=["management_mfa_required"])
        audit(None, "security.admin_mfa_policy_changed", user, {
            "required": required, "reason": reason, "source": "management_command",
        })
        self.stdout.write(self.style.SUCCESS(
            f"Autenticador {'obligatorio' if required else 'desactivado'} para {user.email}."
        ))

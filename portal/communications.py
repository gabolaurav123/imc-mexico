"""Individual administrative communication through the existing private outbox."""
import uuid

from django import forms
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import AuditEvent, Machine, Message, User
from .services import _notify, audit, require_operator

COMPOSE_SALT = "portal.manual-notification.v1"


def can_compose_notifications(user):
    return (user.has_perm("portal.add_notification")
            and (user.has_perm("portal.view_user") or user.has_perm("portal.change_user")))


def _staff_permission(actor, permission):
    require_operator(actor, permission)
    if settings.STAFF_MFA_REQUIRED and not getattr(actor, "is_verified", lambda: False)():
        raise PermissionDenied("Verifica el segundo factor para enviar comunicaciones.")


def _body(value):
    text = str(value or "").strip()
    if not text or len(text) > 5000:
        raise ValidationError("Escribe un mensaje de hasta 5 000 caracteres.")
    return text


class ManualNotificationForm(forms.Form):
    recipient = forms.ModelChoiceField(label="Destinatario", queryset=User.objects.none())
    subject = forms.CharField(label="Asunto", max_length=180)
    body = forms.CharField(label="Mensaje", max_length=5000, widget=forms.Textarea(attrs={"rows": 6}))
    request_token = forms.CharField(widget=forms.HiddenInput, max_length=300)

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.fields["recipient"].queryset = User.objects.filter(is_active=True, is_guest=False).order_by("email")
        if not self.is_bound:
            self.initial["request_token"] = signing.dumps(
                {"actor": actor.pk, "nonce": uuid.uuid4().hex}, salt=COMPOSE_SALT)

    def clean_subject(self):
        subject = self.cleaned_data["subject"].strip()
        if any(char in subject for char in ("\r", "\n", "\x00")):
            raise ValidationError("El asunto debe ocupar una sola línea.")
        return subject

    def clean_request_token(self):
        try:
            value = signing.loads(self.cleaned_data["request_token"], salt=COMPOSE_SALT, max_age=3600)
            if value.get("actor") != self.actor.pk:
                raise ValueError
            return uuid.UUID(hex=value["nonce"]).hex
        except (signing.BadSignature, ValueError, TypeError, KeyError, AttributeError):
            raise ValidationError("El formulario venció. Abre de nuevo la página para enviar el mensaje.")


@transaction.atomic
def queue_manual_notification(*, actor, recipient, subject, body, request_id):
    _staff_permission(actor, "portal.add_notification")
    if not can_compose_notifications(actor):
        raise PermissionDenied("No tienes permiso para consultar destinatarios.")
    subject = str(subject or "").strip()
    if not subject or len(subject) > 180 or any(char in subject for char in ("\r", "\n", "\x00")):
        raise ValidationError("Escribe un asunto de una sola línea y hasta 180 caracteres.")
    body = _body(body)
    try:
        request_id = uuid.UUID(hex=str(request_id)).hex
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("El identificador del envío no es válido.")
    # Lock the sender so a repeated POST cannot queue the same communication twice,
    # even when the two requests selected different recipients.
    User.objects.select_for_update().get(pk=actor.pk)
    if AuditEvent.objects.filter(actor=actor, action="notification.manual_queued",
                                 metadata__request_id=request_id).exists():
        return False
    recipient = User.objects.get(pk=recipient.pk)
    if not recipient.is_active or recipient.is_guest:
        raise ValidationError("La cuenta del destinatario está inactiva.")
    _notify(recipient, None, "manual", subject, body)
    audit(actor, "notification.manual_queued", recipient, {"request_id": request_id,
          "channels": ["in_app", "email"]})
    return True


@transaction.atomic
def save_staff_message(message, actor):
    """Save a new conversation entry; external entries also notify its owner."""
    _staff_permission(actor, "portal.add_message")
    if not (actor.has_perm("portal.view_machine") or actor.has_perm("portal.change_machine")):
        raise PermissionDenied("No tienes permiso para consultar fichas.")
    if message.pk:
        raise ValidationError("Los mensajes enviados se conservan sin cambios.")
    machine = Machine.objects.select_for_update().select_related("owner").filter(pk=message.machine_id).first()
    if machine is None:
        raise PermissionDenied("La ficha dejó de estar disponible para enviar mensajes.")
    message.body = _body(message.body)
    if not message.internal and not machine.owner.is_active:
        raise ValidationError("La cuenta del destinatario está inactiva.")
    message.machine = machine
    message.sender = actor
    message.save()
    if not message.internal:
        _notify(machine.owner, machine, "reply", f"{machine.folio}: tienes una respuesta", message.body)
    audit(actor, "message.internal" if message.internal else "message.reply", message)
    return message

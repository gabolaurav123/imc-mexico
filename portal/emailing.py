"""Render transactional mail at delivery time; never persist an extra token copy."""
from email.mime.image import MIMEImage
from email.utils import getaddresses
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode


AUTH_KINDS = {"activation", "admin_activation", "verify", "recovery"}
LOGO_CID = "imc-logo"
MAIL_CONTENT = {
    "activation": ("SEGURIDAD DE TU CUENTA", "Tu acceso a IMC México está listo para activarse.", "Establecer mi contraseña"),
    "admin_activation": ("ACCESO DEL EQUIPO", "Activa tu acceso y configura la verificación en dos pasos.", "Activar mi acceso"),
    "verify": ("SEGURIDAD DE TU CUENTA", "Completa la verificación de tu correo y tu contraseña.", "Verificar mi acceso"),
    "recovery": ("SEGURIDAD DE TU CUENTA", "Usa este enlace privado para elegir una nueva contraseña.", "Crear una nueva contraseña"),
    "submission": ("TU SOLICITUD", "Recibimos tu ficha. Puedes seguir su revisión desde el panel.", "Ver mis solicitudes"),
    "review": ("REVISIÓN DE TU FICHA", "Tienes una actualización del equipo de IMC México.", "Consultar la revisión"),
    "reply": ("UN MENSAJE DEL EQUIPO", "Tienes una respuesta de IMC México en tu panel.", "Leer y responder"),
    "advertiser": ("TU CUENTA", "Consulta la actualización de tu permiso de anunciante.", "Ir a mi panel"),
    "reminder": ("SEGUIMIENTO DE TU FICHA", "El equipo tiene un recordatorio sobre tu maquinaria.", "Abrir mi borrador"),
    "reassignment": ("TU MAQUINARIA", "Consulta una actualización administrativa de tu maquinaria.", "Ver mis maquinarias"),
}


class NotificationNotSendable(ValueError):
    """A terminal, safe-to-display delivery error without private URL details."""


def _public_base_url():
    base = settings.PUBLIC_URL.rstrip("/")
    try:
        parsed = urlsplit(base)
        if (parsed.scheme not in ({"http", "https"} if settings.DEBUG else {"https"})
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path
                or any(ord(char) < 33 for char in base)):
            raise ValueError
        parsed.port  # Validate malformed ports without exposing their input.
    except (ValueError, TypeError):
        raise NotificationNotSendable("La dirección pública del portal no está configurada correctamente.") from None
    return base, parsed


def _activation_url(notice, base, origin):
    urls = re.findall(r'https?://[^\s<>"\']+', notice.body)
    if len(urls) != 1:
        raise NotificationNotSendable("El enlace de acceso no es válido. Solicita otro enlace.")
    url = urls[0]
    try:
        parsed = urlsplit(url)
        match = re.fullmatch(r"/activar/([A-Za-z0-9_-]+)/([A-Za-z0-9]+-[A-Za-z0-9]+)/", parsed.path)
        if (parsed.scheme != origin.scheme or parsed.netloc != origin.netloc or parsed.query
                or parsed.fragment or not match or not url.startswith(base + "/activar/")
                or urlsafe_base64_decode(match[1]).decode() != str(notice.user_id)):
            raise ValueError
    except (ValueError, TypeError, UnicodeDecodeError):
        raise NotificationNotSendable("El enlace de acceso no es válido. Solicita otro enlace.") from None
    if (not notice.user.is_active or not default_token_generator.check_token(notice.user, match[2])
            or (timezone.now() - notice.created_at).total_seconds() >= settings.PASSWORD_RESET_TIMEOUT):
        raise NotificationNotSendable("El enlace de acceso venció o ya se utilizó. Solicita otro enlace.")
    return url


def _reply_to():
    configured = getattr(settings, "EMAIL_REPLY_TO", "")
    if not configured:
        return []
    values = [configured] if isinstance(configured, str) else list(configured or [])
    if any("\r" in value or "\n" in value for value in values):
        raise NotificationNotSendable("El correo de respuesta no está configurado correctamente.")
    parsed = getaddresses(values)
    if len(parsed) != 1:
        raise NotificationNotSendable("El correo de respuesta no está configurado correctamente.")
    addresses = []
    for name, address in parsed:
        try:
            validate_email(address)
        except ValidationError:
            raise NotificationNotSendable("El correo de respuesta no está configurado correctamente.") from None
        if any(char in name + address for char in "\r\n"):
            raise NotificationNotSendable("El correo de respuesta no está configurado correctamente.")
        addresses.append(address)
    return addresses


@lru_cache(maxsize=1)
def _logo_bytes():
    # Local static artwork only: no tracking pixel, remote fetch or token in an image URL.
    logo = Path(__file__).resolve().parent / "static" / "portal" / "imc-logo.png"
    return logo.read_bytes() if logo.is_file() else None


def notification_context(notice):
    base, origin = _public_base_url()
    is_auth = notice.kind in AUTH_KINDS
    eyebrow, preheader, cta_label = MAIL_CONTENT.get(notice.kind,
        ("ACTUALIZACIÓN DE IMC MÉXICO", "Tienes una actualización en tu panel.", "Ir a mi panel"))
    body = notice.body
    if is_auth:
        cta_url = _activation_url(notice, base, origin)
        body = body.replace(cta_url, "").strip()
    else:
        path = "/panel/"
        machine = notice.machine if notice.machine_id else None
        active_owned = machine is not None and machine.owner_id == notice.user_id and machine.deleted_at is None
        if notice.kind in {"submission", "review"}:
            path = "/panel/solicitudes/"
        elif notice.kind == "reply":
            path = "/panel/mensajes/"
            if active_owned:
                path += f"?maquinaria={machine.pk}"
        elif notice.kind == "reminder":
            path = f"/panel/maquinarias/{machine.pk}/" if active_owned else "/panel/maquinarias/"
            if not active_owned:
                cta_label = "Ver mis maquinarias"
        elif notice.kind == "reassignment":
            path = "/panel/maquinarias/"
        elif notice.kind == "manual":
            path = "/panel/notificaciones/"
            cta_label = "Ver mi notificación"
        cta_url = base + path
    reply_to = _reply_to()
    return {
        "subject": re.sub(r"[\r\n\x00-\x1f\x7f]+", " ", notice.subject).strip()[:180],
        "eyebrow": eyebrow, "preheader": preheader,
        "greeting": f"Hola, {notice.user.first_name.strip()}." if notice.user.first_name.strip() else "Hola.",
        "paragraphs": [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()],
        "cta_url": cta_url, "cta_label": cta_label, "is_auth": is_auth,
        "is_admin_activation": notice.kind == "admin_activation",
        "portal_url": base, "portal_host": origin.netloc,
        "contact_url": base + "/contacto/", "reply_to": reply_to,
        "logo_cid": LOGO_CID if _logo_bytes() else "",
    }


def build_notification_email(notice):
    context = notification_context(notice)
    message = EmailMultiAlternatives(
        subject=context["subject"],
        body=render_to_string("portal/emails/transactional.txt", context).strip(),
        from_email=settings.DEFAULT_FROM_EMAIL, to=[notice.user.email],
        reply_to=context["reply_to"],
        headers={"Auto-Submitted": "auto-generated",
                 "Message-ID": f"<imc-notification-{notice.pk}@{urlsplit(context['portal_url']).hostname}>"},
    )
    message.attach_alternative(render_to_string("portal/emails/transactional.html", context), "text/html")
    logo = _logo_bytes()
    if logo:
        message.mixed_subtype = "related"
        image = MIMEImage(logo, _subtype="png")
        image.add_header("Content-ID", f"<{LOGO_CID}>")
        image.add_header("Content-Disposition", "inline", filename="imc-mexico.png")
        message.attach(image)
    return message


def send_notification_email(notice):
    return build_notification_email(notice).send(fail_silently=False)

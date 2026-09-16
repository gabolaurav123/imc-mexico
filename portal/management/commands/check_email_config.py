"""Configuration-only email diagnostics: no DB, DNS, network, login or send."""
from email.utils import getaddresses
import ipaddress
import json
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


SMTP = "django.core.mail.backends.smtp.EmailBackend"
LOCAL_BACKENDS = {"django.core.mail.backends." + name + ".EmailBackend"
                  for name in ("console", "dummy", "locmem", "filebased")}


def _mailbox(value):
    if not isinstance(value, str) or not value or len(value) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    try:
        addresses = getaddresses([value])
        if len(addresses) != 1:
            return None
        address = addresses[0][1]
        validate_email(address)
        return address
    except (ValidationError, ValueError, TypeError):
        return None


def _public_domain(domain):
    domain = domain.casefold().rstrip(".")
    try:
        return ipaddress.ip_address(domain).is_global
    except ValueError:
        pass
    return bool("." in domain and not domain.startswith("[")
                and not domain.endswith((".invalid", ".localhost", ".local", ".test", ".example"))
                and domain not in {"localhost", "invalid", "test", "example"})


def configuration_report():
    issues = []
    production = not settings.DEBUG

    def issue(code, message, level="error"):
        issues.append({"code": code, "level": level, "message": message})

    backend = getattr(settings, "EMAIL_BACKEND", "")
    valid_backend = isinstance(backend, str) and bool(re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", backend))
    if not valid_backend:
        issue("backend_invalid", "EMAIL_BACKEND debe ser una ruta de clase válida.")
    elif backend in LOCAL_BACKENDS:
        issue("backend_local_only", "Este backend no entrega correo SMTP; console/filebased pueden conservar enlaces privados en registros o archivos.",
              "error" if production else "warning")
    elif backend != SMTP:
        issue("backend_custom", "Backend personalizado: sus requisitos y capacidad de entrega no se comprueban aquí.", "warning")

    host = getattr(settings, "EMAIL_HOST", "")
    valid_host = isinstance(host, str) and bool(re.fullmatch(r"[A-Za-z0-9.:\[\]-]{1,253}", host))
    port = getattr(settings, "EMAIL_PORT", None)
    valid_port = type(port) is int and 1 <= port <= 65535
    username_set = bool(getattr(settings, "EMAIL_HOST_USER", ""))
    password_set = bool(getattr(settings, "EMAIL_HOST_PASSWORD", ""))
    tls, ssl = getattr(settings, "EMAIL_USE_TLS", False), getattr(settings, "EMAIL_USE_SSL", False)
    timeout = getattr(settings, "EMAIL_TIMEOUT", None)
    if backend == SMTP:
        if not valid_host:
            issue("smtp_host_invalid", "Configura EMAIL_HOST como nombre o dirección del servidor, sin URL ni credenciales.")
        if not valid_port:
            issue("smtp_port_invalid", "EMAIL_PORT debe ser un entero entre 1 y 65535.")
        if type(tls) is not bool or type(ssl) is not bool:
            issue("smtp_security_flags_invalid", "EMAIL_USE_TLS y EMAIL_USE_SSL deben ser booleanos.")
        elif tls and ssl:
            issue("smtp_tls_ssl_conflict", "Selecciona STARTTLS o SSL directo; ambas opciones no pueden estar activadas.")
        elif not tls and not ssl:
            issue("smtp_unencrypted", "SMTP no tiene cifrado configurado.", "error" if production else "warning")
        elif (port == 465 and not ssl) or (port == 587 and ssl):
            issue("smtp_port_security_mismatch", "Comprueba puerto y modalidad con el proveedor: normalmente 465 usa SSL directo y 587 STARTTLS.", "warning")
        if username_set != password_set:
            issue("smtp_credentials_incomplete", "La configuración tiene sólo una parte de las credenciales SMTP.")
        elif not username_set:
            issue("smtp_credentials_missing", "No hay credenciales SMTP configuradas; sólo es válido si el relay autoriza envío sin autenticación.",
                  "error" if host == "smtp.resend.com" else "warning")
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            issue("smtp_timeout_invalid", "Configura un timeout SMTP positivo y acotado, de hasta 300 segundos.")

    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    address = _mailbox(sender)
    sender_domain = address.rsplit("@", 1)[-1].casefold() if address else ""
    sender_scope = "unverified"
    if not address:
        issue("sender_invalid", "DEFAULT_FROM_EMAIL debe contener un único buzón válido, sin saltos de línea.")
    elif not _public_domain(sender_domain):
        issue("sender_not_public", "El remitente usa un dominio local o reservado; no sirve como remitente público de producción.",
              "error" if production else "warning")
    elif sender_domain == "resend.dev" or sender_domain.endswith(".resend.dev"):
        sender_scope = "test_only"
        issue("sender_resend_test_only", "El dominio resend.dev está restringido a pruebas para el correo de la cuenta Resend. Para destinatarios generales verifica un dominio propio y cambia el remitente.", "warning")

    reply_to = getattr(settings, "EMAIL_REPLY_TO", "")
    reply_address = _mailbox(reply_to) if reply_to else None
    if reply_to and not reply_address:
        issue("reply_to_invalid", "EMAIL_REPLY_TO debe ser un único buzón válido; no admite listas ni saltos de línea.")
    elif reply_address and not _public_domain(reply_address.rsplit("@", 1)[-1]):
        issue("reply_to_not_public", "EMAIL_REPLY_TO usa un dominio local o reservado.", "error" if production else "warning")

    public_url_valid = False
    try:
        public_url = getattr(settings, "PUBLIC_URL", "")
        parsed = urlsplit(public_url)
        public_url_valid = (parsed.scheme in ({"https"} if production else {"http", "https"})
                            and bool(parsed.hostname) and not parsed.username and not parsed.password
                            and not parsed.query and not parsed.fragment and parsed.path in ("", "/")
                            and not any(ord(c) < 32 or ord(c) == 127 for c in public_url)
                            and (not production or _public_domain(parsed.hostname)))
        # Accessing .port also validates malformed port syntax without connecting.
        parsed.port
    except (ValueError, TypeError):
        public_url_valid = False
    if not public_url_valid:
        issue("public_url_invalid", "PUBLIC_URL debe ser el origen del portal, HTTPS en producción, sin credenciales, ruta privada, parámetros ni fragmentos.")

    return {"status": "errors" if any(item["level"] == "error" for item in issues) else "warnings" if issues else "ok",
            "scope": "configuration_only", "production_mode": production,
            "configuration": {"backend": backend if valid_backend else "(invalid)",
                "smtp_host": host if valid_host else "(missing_or_invalid)", "smtp_port": port if valid_port else None,
                "smtp_username_configured": username_set, "smtp_password_configured": password_set,
                "smtp_starttls": tls is True, "smtp_ssl": ssl is True,
                "from_email": sender if address else "(missing_or_invalid)",
                "reply_to": reply_to if reply_address else "" if not reply_to else "(invalid)",
                "sender_scope": sender_scope, "public_url_valid": bool(public_url_valid)},
            "verification": {"database_accessed": False, "network_accessed": False, "dns_verified": False,
                "smtp_authentication_verified": False, "sender_domain_verified": False, "delivery_verified": False},
            "issues": issues}


class Command(BaseCommand):
    help = "Diagnostica configuración de correo sin red, DNS, base de datos ni envíos; nunca muestra credenciales ni enlaces privados."
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json", help="Informe JSON apto para comprobaciones automáticas.")

    def handle(self, *args, **options):
        report = configuration_report()
        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write("Diagnóstico de configuración: " + report["status"])
            for key, value in report["configuration"].items():
                self.stdout.write(f"  {key}: {value}")
            for item in report["issues"]:
                self.stdout.write(f"{item['level'].upper()} [{item['code']}]: {item['message']}")
            self.stdout.write("Sin conexión ni envío: DNS, autenticación SMTP, dominio remitente y recepción no verificados.")
        if report["status"] == "errors":
            raise CommandError("La configuración de correo tiene errores; consulta el informe sin compartir credenciales.")

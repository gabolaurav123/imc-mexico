"""One password-length policy for registration, recovery and account changes."""
from django.contrib.auth.password_validation import MinimumLengthValidator


def minimum_password_length(user=None):
    return 12 if user and (user.is_staff or user.is_superuser) else 8


class AccountMinimumLengthValidator(MinimumLengthValidator):
    def __init__(self):
        super().__init__(min_length=8)

    def validate(self, password, user=None):
        MinimumLengthValidator(min_length=minimum_password_length(user)).validate(password, user)


def configure_password_fields(form, user=None):
    """Keep browser hints consistent with server validation for this account."""
    minimum = minimum_password_length(user)
    for name in ("password1", "password2", "new_password1", "new_password2"):
        if name in form.fields:
            form.fields[name].widget.attrs["minlength"] = minimum
    first = form.fields.get("password1") or form.fields.get("new_password1")
    if first is not None:
        first.help_text = (
            f"Mínimo {minimum} caracteres. Puedes usar una frase; no necesitas mayúsculas ni símbolos. "
            "Evita contraseñas comunes, sólo números o tus datos personales. "
            "Podrás cambiarla después desde Mi cuenta."
        )

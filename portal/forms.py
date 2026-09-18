import re
from django import forms
from django.utils.html import format_html, format_html_join
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from .models import User, Lead

# Known country calling codes shown in the form's datalist.  Keeping this list in
# the form also lets us split existing E.164 values without guessing a code.
# Checked against Google libphonenumber countryCode metadata, 2026-09-18:
# https://github.com/google/libphonenumber/blob/master/resources/PhoneNumberMetadata.xml
COUNTRY_PREFIXES = {
    "+1", "+7", "+20", "+27", "+30", "+31", "+32", "+33", "+34", "+36", "+39",
    "+40", "+41", "+43", "+44", "+45", "+46", "+47", "+48", "+49", "+51", "+52",
    "+53", "+54", "+55", "+56", "+57", "+58", "+60", "+61", "+62", "+63",
    "+64", "+65", "+66", "+81", "+82", "+84", "+86", "+90", "+91", "+92",
    "+93", "+94", "+95", "+98", "+211", "+212", "+213", "+216", "+218", "+220",
    "+221", "+222", "+223", "+224", "+225", "+226", "+227", "+228", "+229",
    "+230", "+231", "+232", "+233", "+234", "+235", "+236", "+237", "+238",
    "+239", "+240", "+241", "+242", "+243", "+244", "+245", "+246", "+247", "+248",
    "+249", "+250", "+251", "+252", "+253", "+254", "+255", "+256", "+257",
    "+258", "+260", "+261", "+262", "+263", "+264", "+265", "+266", "+267",
    "+268", "+269", "+290", "+291", "+297", "+298", "+299", "+350", "+351",
    "+352", "+353", "+354", "+355", "+356", "+357", "+358", "+359", "+370",
    "+371", "+372", "+373", "+374", "+375", "+376", "+377", "+378", "+380",
    "+381", "+382", "+383", "+385", "+386", "+387", "+389", "+420", "+421",
    "+423", "+500", "+501", "+502", "+503", "+504", "+505", "+506", "+507",
    "+508", "+509", "+590", "+591", "+592", "+593", "+594", "+595", "+596",
    "+597", "+598", "+599", "+670", "+672", "+673", "+674", "+675", "+676",
    "+677", "+678", "+679", "+680", "+681", "+682", "+683", "+685", "+686",
    "+687", "+688", "+689", "+690", "+691", "+692", "+850", "+852", "+853",
    "+855", "+856", "+880", "+886", "+960", "+961", "+962", "+963", "+964",
    "+965", "+966", "+967", "+968", "+970", "+971", "+972", "+973", "+974",
    "+975", "+976", "+977", "+992", "+993", "+994", "+995", "+996", "+998",
}
COUNTRY_PREFIX_LABELS = {"+1": "EE. UU. o Canadá", "+34": "España", "+52": "México", "+591": "Bolivia"}

class CountryPrefixWidget(forms.TextInput):
    def render(self, name, value, attrs=None, renderer=None):
        field = super().render(name, value, attrs, renderer)
        ordered = sorted(COUNTRY_PREFIXES, key=lambda code: (0, ("+52", "+591", "+1", "+34").index(code)) if code in ("+52", "+591", "+1", "+34") else (1, len(code), code))
        options = format_html_join("", "<option value=\"{}\" label=\"{}\"></option>", ((code, COUNTRY_PREFIX_LABELS.get(code, "Código internacional " + code)) for code in ordered))
        return format_html("{}<datalist id=\"country-phone-prefixes\">{}</datalist>", field, options)

def _split_phone(value):
    """Return (prefix, national) for a stored E.164 value."""
    compact = re.sub(r"[\s()-]", "", str(value or ""))
    if not compact.startswith("+"):
        return "", compact
    for prefix in sorted(COUNTRY_PREFIXES, key=len, reverse=True):
        if compact.startswith(prefix) and len(compact) > len(prefix):
            return prefix, compact[len(prefix):]
    return "", compact

class PhoneFieldsMixin:
    phone_prefix = forms.CharField(label="Código de país", required=False,
        help_text="Ejemplo: +52 (México), +591 (Bolivia), +1 (EE. UU. o Canadá).",
        widget=CountryPrefixWidget(attrs={"type": "text", "inputmode": "tel", "list": "country-phone-prefixes", "autocomplete": "tel-country-code", "placeholder": "+52", "maxlength": "4"}))
    phone_national = forms.CharField(label="Número nacional", required=False,
        help_text="Escribe el número sin el código de país.",
        widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel-national", "placeholder": "55 1234 5678", "maxlength": "30"}))
    phone = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = getattr(self.instance, "phone", "") if getattr(self, "instance", None) else ""
        self.fields["phone_prefix"].required = True
        self.fields["phone_national"].required = True
        if self.is_bound and self.data.get("phone") and not (self.data.get("phone_prefix") or self.data.get("phone_national")):
            # Compatibility for clients that still submit one full phone value.
            self.fields["phone_prefix"].required = self.fields["phone_national"].required = False
        if current and not self.is_bound:
            prefix, national = _split_phone(current)
            self.initial.setdefault("phone_prefix", prefix)
            self.initial.setdefault("phone_national", national)
        elif not self.is_bound and not current:
            self.initial.setdefault("phone_prefix", "+52")

    def clean(self):
        cleaned = super().clean()
        prefix = re.sub(r"[\s()-]", "", cleaned.get("phone_prefix") or "")
        if re.fullmatch(r"[1-9][0-9]{0,2}", prefix):
            prefix = "+" + prefix
        national = re.sub(r"[\s()-]", "", cleaned.get("phone_national") or "")
        legacy = re.sub(r"[\s()-]", "", cleaned.get("phone") or "")
        if not prefix and not national and legacy:
            prefix, national = _split_phone(legacy)
        elif national.startswith("+"):
            pasted_prefix, pasted_national = _split_phone(national)
            if prefix and pasted_prefix and prefix != pasted_prefix:
                self.add_error("phone_national", "El código de país no coincide con el número pegado.")
            prefix, national = pasted_prefix, pasted_national
        if not re.fullmatch(r"\+[1-9]\d{0,2}", prefix or "") or prefix not in COUNTRY_PREFIXES:
            self.add_error("phone_prefix", "Elige un código de país válido de 1 a 3 dígitos.")
        if not re.fullmatch(r"[0-9]+", national or ""):
            self.add_error("phone_national", "Escribe sólo los dígitos del número nacional.")
        elif not 4 <= len(national) <= 14:
            self.add_error("phone_national", "El número nacional debe tener entre 4 y 14 dígitos.")
        full = (prefix or "") + (national or "")
        if prefix in COUNTRY_PREFIXES and national and len(full) - 1 > 15:
            self.add_error("phone_national", "El teléfono no puede superar 15 dígitos en formato internacional.")
        if not self.errors.get("phone_prefix") and not self.errors.get("phone_national"):
            cleaned["phone"] = full
        return cleaned

class RegisterForm(PhoneFieldsMixin, UserCreationForm):
    phone_prefix = PhoneFieldsMixin.phone_prefix
    phone_national = PhoneFieldsMixin.phone_national
    phone = PhoneFieldsMixin.phone
    first_name = forms.CharField(label='Nombre',max_length=150,widget=forms.TextInput(attrs={'autocomplete':'given-name'}))
    last_name = forms.CharField(label='Apellidos',max_length=150,widget=forms.TextInput(attrs={'autocomplete':'family-name'}))
    email = forms.EmailField(label='Correo electrónico',widget=forms.EmailInput(attrs={'autocomplete':'email'}))
    company = forms.CharField(label='Empresa (opcional)', required=False, max_length=180,widget=forms.TextInput(attrs={'autocomplete':'organization'}))
    contact_preference = forms.ChoiceField(label='Prefiero que me contacten por',choices=[('whatsapp','WhatsApp'),('call','Llamada'),('email','Correo')])
    terms = forms.BooleanField(label='Acepto los términos y el aviso de privacidad')
    class Meta:
        model=User
        fields=('first_name','last_name','email','phone_prefix','phone_national','phone','company','contact_preference','password1','password2','terms')
    def clean_email(self):
        email=self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists(): raise forms.ValidationError('Ya existe una cuenta con este correo. Inicia sesión o recupera el acceso.')
        return email
    def save(self,commit=True):
        user=super().save(commit=False)
        user.username=user.email=self.cleaned_data['email']
        if commit:user.save()
        return user

class LoginForm(AuthenticationForm):
    username=forms.EmailField(label='Correo electrónico',widget=forms.EmailInput(attrs={'autocomplete':'username'}))
    password=forms.CharField(label='Contraseña',widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}))
    def clean_username(self): return self.cleaned_data['username'].strip().lower()

class ProfileForm(PhoneFieldsMixin, forms.ModelForm):
    phone_prefix = PhoneFieldsMixin.phone_prefix
    phone_national = PhoneFieldsMixin.phone_national
    phone = PhoneFieldsMixin.phone
    class Meta:
        model=User
        fields=('first_name','last_name','phone_prefix','phone_national','phone','company','contact_preference','marketing_consent')
        labels={'first_name':'Nombre','last_name':'Apellidos','phone':'Celular','company':'Empresa (opcional)','contact_preference':'Preferencia de contacto','marketing_consent':'Deseo recibir información comercial'}

class ContactForm(forms.ModelForm):
    privacy=forms.BooleanField(label='He leído el aviso de privacidad y autorizo que respondan mi consulta')
    website=forms.CharField(required=False,widget=forms.HiddenInput)
    class Meta:
        model=Lead
        fields=('name','email','phone','message')
        labels={'name':'Nombre','email':'Correo electrónico','phone':'Celular (opcional)','message':'¿Cómo podemos ayudarte?'}
        widgets={'message':forms.Textarea(attrs={'rows':4})}
    def clean_website(self):
        if self.cleaned_data.get('website'):raise forms.ValidationError('Solicitud no válida.')
        return ''

class RecoveryForm(forms.Form):
    email=forms.EmailField(label='Correo electrónico')

class OTPForm(forms.Form):
    token=forms.RegexField(r'^\d{6}$',label='Código de tu aplicación autenticadora',widget=forms.TextInput(attrs={'inputmode':'numeric','autocomplete':'one-time-code','maxlength':'6'}))

class AccountRequestForm(forms.Form):
    kind=forms.ChoiceField(label='Solicitud',choices=[('export','Acceso y copia de mis datos'),('correction','Corrección de datos'),('delete','Eliminar mi cuenta y datos')])
    detail=forms.CharField(label='Detalles (opcional)',required=False,max_length=2000,widget=forms.Textarea(attrs={'rows':3}))

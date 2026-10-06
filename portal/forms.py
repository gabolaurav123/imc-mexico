import re
from django import forms
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
# One name per calling code keeps a compact native selector.  Some codes are
# shared by several territories, so those labels deliberately name the region.
COUNTRY_PREFIX_LABELS = {
    "+1": "Estados Unidos, Canadá y Caribe", "+7": "Rusia y Kazajistán", "+20": "Egipto", "+27": "Sudáfrica", "+30": "Grecia", "+31": "Países Bajos", "+32": "Bélgica", "+33": "Francia", "+34": "España", "+36": "Hungría", "+39": "Italia", "+40": "Rumania", "+41": "Suiza", "+43": "Austria", "+44": "Reino Unido, Guernsey, Isla de Man y Jersey", "+45": "Dinamarca", "+46": "Suecia", "+47": "Noruega y Svalbard", "+48": "Polonia", "+49": "Alemania", "+51": "Perú", "+52": "México", "+53": "Cuba", "+54": "Argentina", "+55": "Brasil", "+56": "Chile", "+57": "Colombia", "+58": "Venezuela", "+60": "Malasia", "+61": "Australia", "+62": "Indonesia", "+63": "Filipinas", "+64": "Nueva Zelanda", "+65": "Singapur", "+66": "Tailandia", "+81": "Japón", "+82": "Corea del Sur", "+84": "Vietnam", "+86": "China", "+90": "Turquía", "+91": "India", "+92": "Pakistán", "+93": "Afganistán", "+94": "Sri Lanka", "+95": "Myanmar", "+98": "Irán",
    "+211": "Sudán del Sur", "+212": "Marruecos y Sáhara Occidental", "+213": "Argelia", "+216": "Túnez", "+218": "Libia", "+220": "Gambia", "+221": "Senegal", "+222": "Mauritania", "+223": "Malí", "+224": "Guinea", "+225": "Costa de Marfil", "+226": "Burkina Faso", "+227": "Níger", "+228": "Togo", "+229": "Benín", "+230": "Mauricio", "+231": "Liberia", "+232": "Sierra Leona", "+233": "Ghana", "+234": "Nigeria", "+235": "Chad", "+236": "República Centroafricana", "+237": "Camerún", "+238": "Cabo Verde", "+239": "Santo Tomé y Príncipe", "+240": "Guinea Ecuatorial", "+241": "Gabón", "+242": "República del Congo", "+243": "República Democrática del Congo", "+244": "Angola", "+245": "Guinea-Bisáu", "+246": "Territorio Británico del Océano Índico", "+247": "Ascensión", "+248": "Seychelles", "+249": "Sudán", "+250": "Ruanda", "+251": "Etiopía", "+252": "Somalia", "+253": "Yibuti", "+254": "Kenia", "+255": "Tanzania", "+256": "Uganda", "+257": "Burundi", "+258": "Mozambique", "+260": "Zambia", "+261": "Madagascar", "+262": "Reunión y Mayotte", "+263": "Zimbabue", "+264": "Namibia", "+265": "Malaui", "+266": "Lesoto", "+267": "Botsuana", "+268": "Esuatini", "+269": "Comoras", "+290": "Santa Elena, Tristán de Acuña", "+291": "Eritrea", "+297": "Aruba", "+298": "Islas Feroe", "+299": "Groenlandia",
    "+350": "Gibraltar", "+351": "Portugal", "+352": "Luxemburgo", "+353": "Irlanda", "+354": "Islandia", "+355": "Albania", "+356": "Malta", "+357": "Chipre", "+358": "Finlandia y Åland", "+359": "Bulgaria", "+370": "Lituania", "+371": "Letonia", "+372": "Estonia", "+373": "Moldavia", "+374": "Armenia", "+375": "Bielorrusia", "+376": "Andorra", "+377": "Mónaco", "+378": "San Marino", "+380": "Ucrania", "+381": "Serbia", "+382": "Montenegro", "+383": "Kosovo", "+385": "Croacia", "+386": "Eslovenia", "+387": "Bosnia y Herzegovina", "+389": "Macedonia del Norte", "+420": "Chequia", "+421": "Eslovaquia", "+423": "Liechtenstein", "+500": "Islas Malvinas", "+501": "Belice", "+502": "Guatemala", "+503": "El Salvador", "+504": "Honduras", "+505": "Nicaragua", "+506": "Costa Rica", "+507": "Panamá", "+508": "San Pedro y Miquelón", "+509": "Haití", "+590": "Guadalupe, San Bartolomé y San Martín", "+591": "Bolivia", "+592": "Guyana", "+593": "Ecuador", "+594": "Guayana Francesa", "+595": "Paraguay", "+596": "Martinica", "+597": "Surinam", "+598": "Uruguay", "+599": "Curazao y Caribe Neerlandés",
    "+670": "Timor-Leste", "+672": "Territorios australianos externos", "+673": "Brunéi", "+674": "Nauru", "+675": "Papúa Nueva Guinea", "+676": "Tonga", "+677": "Islas Salomón", "+678": "Vanuatu", "+679": "Fiyi", "+680": "Palaos", "+681": "Wallis y Futuna", "+682": "Islas Cook", "+683": "Niue", "+685": "Samoa", "+686": "Kiribati", "+687": "Nueva Caledonia", "+688": "Tuvalu", "+689": "Polinesia Francesa", "+690": "Tokelau", "+691": "Micronesia", "+692": "Islas Marshall", "+850": "Corea del Norte", "+852": "Hong Kong", "+853": "Macao", "+855": "Camboya", "+856": "Laos", "+880": "Bangladés", "+886": "Taiwán", "+960": "Maldivas", "+961": "Líbano", "+962": "Jordania", "+963": "Siria", "+964": "Irak", "+965": "Kuwait", "+966": "Arabia Saudita", "+967": "Yemen", "+968": "Omán", "+970": "Palestina", "+971": "Emiratos Árabes Unidos", "+972": "Israel", "+973": "Baréin", "+974": "Catar", "+975": "Bután", "+976": "Mongolia", "+977": "Nepal", "+992": "Tayikistán", "+993": "Turkmenistán", "+994": "Azerbaiyán", "+995": "Georgia", "+996": "Kirguistán", "+998": "Uzbekistán",
}

assert COUNTRY_PREFIXES == set(COUNTRY_PREFIX_LABELS), "Every supported country code needs a label."


def country_prefix_choices():
    preferred = ("+52", "+591", "+1", "+34")
    ordered = (*preferred, *(code for code in sorted(COUNTRY_PREFIXES, key=lambda code: (len(code), code)) if code not in preferred))
    return [(code, f"{COUNTRY_PREFIX_LABELS[code]} ({code})") for code in ordered]


class CountryPrefixChoiceField(forms.ChoiceField):
    """Accept legacy typed country codes while rendering a safe select menu."""

    def clean(self, value):
        compact = re.sub(r"[\s()-]", "", str(value or ""))
        if re.fullmatch(r"[1-9][0-9]{0,2}", compact):
            compact = "+" + compact
        return super().clean(compact)


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
    phone_prefix = CountryPrefixChoiceField(label="País y código", required=False,
        help_text="Elige el país del número. Si pegas el número completo, verificaremos que coincida.",
        choices=country_prefix_choices(),
        widget=forms.Select(attrs={"autocomplete": "tel-country-code"}))
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
    email = forms.EmailField(label='Correo de contacto y acceso', disabled=True,
        help_text='Usaremos este correo para dar seguimiento a tus fichas.')
    phone_prefix = PhoneFieldsMixin.phone_prefix
    phone_national = PhoneFieldsMixin.phone_national
    phone = PhoneFieldsMixin.phone
    class Meta:
        model=User
        fields=('first_name','last_name','email','phone_prefix','phone_national','phone','company','contact_preference','marketing_consent')
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

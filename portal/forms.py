import re
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from .models import User, Lead

class RegisterForm(UserCreationForm):
    first_name = forms.CharField(label='Nombre',max_length=150)
    email = forms.EmailField(label='Correo electrónico')
    phone = forms.CharField(label='Celular con código internacional',help_text='Por ejemplo: +52 55 1234 5678',max_length=30)
    contact_preference = forms.ChoiceField(label='Prefiero que me contacten por',choices=[('whatsapp','WhatsApp'),('call','Llamada'),('email','Correo')])
    terms = forms.BooleanField(label='Acepto los términos y el aviso de privacidad')
    class Meta:
        model=User
        fields=('first_name','email','phone','contact_preference','password1','password2','terms')
    def clean_email(self):
        email=self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists(): raise forms.ValidationError('Ya existe una cuenta con este correo. Inicia sesión o recupera el acceso.')
        return email
    def clean_phone(self):
        phone=re.sub(r'[\s()-]','',self.cleaned_data['phone'])
        if not re.fullmatch(r'\+[1-9]\d{7,14}',phone): raise forms.ValidationError('Incluye + y el código de país, seguido del número.')
        return phone
    def save(self,commit=True):
        user=super().save(commit=False)
        user.username=user.email=self.cleaned_data['email']
        if commit:user.save()
        return user

class LoginForm(AuthenticationForm):
    username=forms.EmailField(label='Correo electrónico',widget=forms.EmailInput(attrs={'autocomplete':'username'}))
    password=forms.CharField(label='Contraseña',widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}))
    def clean_username(self): return self.cleaned_data['username'].strip().lower()

class ProfileForm(forms.ModelForm):
    class Meta:
        model=User
        fields=('first_name','last_name','phone','company','contact_preference','marketing_consent')
        labels={'first_name':'Nombre','last_name':'Apellidos','phone':'Celular','company':'Empresa (opcional)','contact_preference':'Preferencia de contacto','marketing_consent':'Deseo recibir información comercial'}
    clean_phone=RegisterForm.clean_phone

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

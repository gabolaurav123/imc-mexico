import base64
from io import BytesIO
import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm, PasswordChangeForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from .forms import RegisterForm, LoginForm, RecoveryForm, ProfileForm, OTPForm, AccountRequestForm
from .models import User, Consent, Notification, AccountRequest, PlatformSettings
from .security import throttle, login_destination, safe_next_url, management_home, is_management_user
from .services import audit
from .analytics import attach_consent_to_account,record_event

def auth_render(request,form,title,submit_label,**extra):
    publication_flow=(request.POST.get('next') or request.GET.get('next'))=='/panel/maquinarias/nueva/'
    return render(request,'portal/auth.html',{'form':form,'title':title,'submit_label':submit_label,'publication_flow':publication_flow,**extra})

def activation_email(user,kind='activation'):
    uid=urlsafe_base64_encode(force_bytes(user.pk))
    token=default_token_generator.make_token(user)
    url=f'{settings.PUBLIC_URL}/activar/{uid}/{token}/'
    subject,intro={
        'recovery':('Recupera tu acceso a IMC México','Recibimos una solicitud para recuperar el acceso a tu cuenta. Abre el enlace y elige una nueva contraseña.'),
        'verify':('Confirma tu correo en IMC México','Tu cuenta está lista para preparar tus fichas. Abre el enlace para establecer o confirmar tu contraseña y verificar tu correo.'),
        'admin_activation':('Activa tu acceso administrativo a IMC México','Tu cuenta administrativa está preparada. Establece tu contraseña y después configura la verificación en dos pasos.'),
    }.get(kind,('Activa tu acceso a IMC México','Tu cuenta está preparada. Abre el enlace para establecer tu contraseña y verificar tu correo.'))
    minutes=max(1,settings.PASSWORD_RESET_TIMEOUT//60)
    return Notification.objects.create(user=user,channel='email',kind=kind,subject=subject,body=f'{intro}\n\n{url}\n\nEl enlace caduca en {minutes} minutos desde la solicitud y sólo puede usarse una vez.')

def register(request):
    publication_flow=(request.POST.get('next') or request.GET.get('next'))=='/panel/maquinarias/nueva/'
    destination='/panel/maquinarias/nueva/' if publication_flow else '/panel/'
    if request.user.is_authenticated:return redirect(destination)
    configuration=PlatformSettings.load()
    if not configuration.registration_open:
        return auth_render(request,None,'Próximamente podrás anunciar tu maquinaria','',intro='El registro de nuevos anunciantes todavía no está abierto. Puedes consultar cómo funciona el portal o comunicarte con el equipo desde Contacto.')
    form=RegisterForm(request.POST or None)
    if request.method=='POST':
        if not throttle(request,'register',5,3600):form.add_error(None,'Demasiados intentos. Espera un momento para volver a intentarlo.')
        elif form.is_valid():
            with transaction.atomic():
                user=form.save()
                Consent.objects.bulk_create([Consent(user=user,kind=k,granted=True) for k in ('terms','privacy')])
                audit(user,'account.register',user)
                # Tokens include last_login: create the verification link only
                # after login has updated it, otherwise it is invalid on arrival.
                login(request,user)
                activation_email(user,'verify')
            attach_consent_to_account(request,user)
            record_event(request,'register_completed',page='register')
            messages.success(request,'Tu cuenta está lista para preparar borradores. Te enviaremos un enlace para verificar el correo; tu celular sigue siendo un contacto declarado.')
            return redirect(destination)
    return auth_render(request,form,'Crea tu cuenta para publicar maquinaria','Crear mi cuenta y continuar' if publication_flow else 'Crear mi cuenta')

def sign_in(request,management_only=False):
    if request.user.is_authenticated and request.method=='GET' and (not management_only or is_management_user(request.user)):
        return redirect(login_destination(request,None if management_only else request.GET.get('next')))
    form=LoginForm(request,data=request.POST or None)
    if request.method=='POST':
        if not throttle(request,'login',15,900) or not throttle(request,'login-account',12,900,request.POST.get('username','').strip().lower()):
            form.add_error(None,'Se alcanzó el límite de intentos. Inténtalo de nuevo en 15 minutos.')
        elif form.is_valid():
            if management_only and not is_management_user(form.get_user()):
                form.add_error(None,'Esta cuenta no tiene acceso administrativo. Usa el correo de tu cuenta del equipo IMC México o entra al acceso general para anunciantes.')
            else:
                login(request,form.get_user())
                audit(request.user,'account.login',request.user)
                return redirect(login_destination(request,None if management_only else (request.POST.get('next') or request.GET.get('next'))))
    if management_only:
        intro='Ingresa con el correo de tu cuenta administrativa. Después verificarás tu acceso en dos pasos.'
        if request.user.is_authenticated and not is_management_user(request.user):
            intro='Tu sesión actual no tiene permisos administrativos. Ingresa con una cuenta del equipo IMC México para continuar; el nombre mostrado no determina tus permisos.'
        return auth_render(request,form,'Acceso administrativo','Entrar a administración',admin_access=True,intro=intro)
    return auth_render(request,form,'Qué bueno verte de nuevo','Entrar a mi cuenta')


def administration_sign_in(request):
    return sign_in(request,management_only=True)

@require_POST
def sign_out(request):
    logout(request)
    return redirect('/')

def recover(request):
    form=RecoveryForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if throttle(request,'recover',5,3600):
            user=User.objects.filter(email__iexact=form.cleaned_data['email'],is_active=True).first()
            if user:activation_email(user,'recovery')
        messages.success(request,'Si existe una cuenta con ese correo, recibirás un enlace para recuperar el acceso. Revisa también la carpeta de spam.')
        return redirect('/recuperar-acceso/?solicitado=1')
    return auth_render(request,form,'Recupera tu acceso','Enviar enlace de recuperación')

def activate(request,uidb64,token):
    try:user=User.objects.get(pk=urlsafe_base64_decode(uidb64).decode(),is_active=True)
    except (User.DoesNotExist,ValueError,TypeError,UnicodeDecodeError):user=None
    if user is None or not default_token_generator.check_token(user,token):
        return auth_render(request,None,'Este enlace venció o ya se utilizó','',intro='Solicita un nuevo enlace en Recuperar acceso.')
    form=SetPasswordForm(user,request.POST or None)
    if request.method=='POST' and throttle(request,'activate',10,3600) and form.is_valid():
        with transaction.atomic():
            user=User.objects.select_for_update().get(pk=user.pk)
            if not default_token_generator.check_token(user,token):return redirect('/recuperar-acceso/')
            form.user=user
            form.save()
            user.email_verified=True
            user.save(update_fields=['email_verified'])
            audit(user,'account.activated',user)
        login(request,user)
        return redirect('/panel/seguridad/' if user.is_staff else '/panel/')
    response=auth_render(request,form,'Establece tu contraseña','Guardar y entrar',
        intro='Elige una contraseña que recuerdes. Después continuarás con la verificación de tu acceso administrativo.' if user.is_staff else 'Elige la contraseña que usarás para entrar a tu cuenta.')
    response['Referrer-Policy']='same-origin'
    return response

@login_required
def profile(request):
    form=ProfileForm(request.POST or None,instance=request.user)
    if request.method=='POST' and form.is_valid():
        old_marketing=User.objects.get(pk=request.user.pk).marketing_consent
        user=form.save()
        if old_marketing!=user.marketing_consent:Consent.objects.create(user=user,kind='marketing',granted=user.marketing_consent)
        audit(user,'profile.updated',user)
        messages.success(request,'Guardamos tus datos de contacto.')
        return redirect('/panel/perfil/')
    return render(request,'portal/profile.html',{'form':form})

@login_required
def security(request):
    next_url=safe_next_url(request,request.GET.get('next'))
    if next_url.split('?',1)[0].split('#',1)[0] in {'/panel/seguridad/','/iniciar-sesion/'}:
        next_url=management_home(request.user)
    device=TOTPDevice.objects.filter(user=request.user,name='IMC').first()
    if request.user.is_staff and device is None:device=TOTPDevice.objects.create(user=request.user,name='IMC',confirmed=False)
    action=request.POST.get('action','otp')
    otp_form=OTPForm(request.POST if request.method=='POST' and action=='otp' else None)
    password_form=PasswordChangeForm(request.user,request.POST if request.method=='POST' and action=='password' else None)
    # Keep the account identity and recovery action visible on entry rather
    # than scrolling into the OTP field or a collapsed password form.
    password_form.fields['old_password'].widget.attrs.pop('autofocus',None)
    account_form=AccountRequestForm(request.POST if request.method=='POST' and action=='account_request' else None)
    if request.method=='POST':
        if action=='recover_password':
            # The existing authenticated session can request a link, but it
            # cannot select a password or verify MFA on the user's behalf.
            if throttle(request,'authenticated-recovery',3,3600,str(request.user.pk)):
                activation_email(request.user,'recovery')
                audit(request.user,'password.recovery_requested',request.user)
                messages.success(request,f'Te enviaremos a {request.user.email} un enlace para elegir una nueva contraseña. No necesitas escribir la anterior.')
            else:
                messages.error(request,'Ya solicitaste varios enlaces. Usa el último correo recibido o vuelve a intentarlo dentro de una hora.')
            return redirect(request.get_full_path())
        elif action=='otp' and device and otp_form.is_valid() and throttle(request,'otp',10,600,str(request.user.pk)):
            with transaction.atomic():
                device=TOTPDevice.objects.select_for_update().get(pk=device.pk)
                valid=device.verify_token(otp_form.cleaned_data['token'])
                if valid:
                    device.confirmed=True;device.save(update_fields=['confirmed'])
            if valid:
                otp_login(request,device)
                from .access_tracking import record_access
                record_access(request,request.user,'mfa_verified')
                messages.success(request,'Segundo factor verificado. Ya puedes acceder a la administración.')
                return redirect(login_destination(request,next_url))
            otp_form.add_error('token','El código no es válido o ya fue utilizado.')
        elif action=='password' and password_form.is_valid():
            user=password_form.save();update_session_auth_hash(request,user)
            audit(user,'password.changed',user)
            messages.success(request,'Contraseña actualizada. Las otras sesiones dejan de ser válidas.')
            return redirect('/panel/seguridad/')
        elif action=='sessions':
            for session in Session.objects.filter(expire_date__gt=timezone.now()).exclude(session_key=request.session.session_key).iterator():
                if str(session.get_decoded().get('_auth_user_id'))==str(request.user.pk):session.delete()
            messages.success(request,'Cerramos tus otras sesiones.')
            return redirect('/panel/seguridad/')
        elif action=='account_request' and account_form.is_valid():
            AccountRequest.objects.create(user=request.user,**account_form.cleaned_data)
            audit(request.user,'account.requested',request.user,{'kind':account_form.cleaned_data['kind']})
            messages.success(request,'Recibimos tu solicitud. El equipo podrá darle seguimiento de forma privada.')
            return redirect('/panel/seguridad/')
    qr=None
    if device and not device.confirmed:
        buffer=BytesIO();qrcode.make(device.config_url).save(buffer,format='PNG');qr=base64.b64encode(buffer.getvalue()).decode()
    return render(request,'portal/security.html',{'form':otp_form,'otp_form':otp_form,'password_form':password_form,'account_form':account_form,'device':device,'qr':qr,'verified':request.user.is_verified(),'next_url':next_url})

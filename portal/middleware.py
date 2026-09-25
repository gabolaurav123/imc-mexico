from django.conf import settings
from django.http import JsonResponse
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from .security import login_destination


class GuestPrincipalMiddleware:
    """Technical visitor principals can never behave like user sessions.

    Guest browser work is authorized by the short-lived draft capability, not
    by logging in as its internal owner.  Keep an explicit allowlist so an
    accidental password or staff action cannot expose panel, sharing, submit,
    export, or ordinary machine API routes.
    """
    allowed_prefixes = ("/api/invitados/", "/salud/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and getattr(user, "is_guest", False):
            if request.path.startswith(self.allowed_prefixes):
                return self.get_response(request)
            if request.path.startswith("/api/"):
                return JsonResponse({"error": "El borrador temporal requiere su capacidad de sesión."}, status=403)
            return HttpResponseForbidden("El borrador temporal requiere su capacidad de sesión.")
        return self.get_response(request)

class StaffMFAMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        protected = request.path.startswith(('/admin/', '/operaciones/'))
        if protected and request.user.is_authenticated and request.user.is_staff and settings.STAFF_MFA_REQUIRED and not request.user.is_verified():
            return redirect(login_destination(request, request.get_full_path()))
        return self.get_response(request)

class SecurityHeadersMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        response['Permissions-Policy']='camera=(self), microphone=(), geolocation=()'
        response['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; media-src 'self' blob:; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith(('/panel/','/admin/','/administracion/','/operaciones/','/api/','/archivos/','/activar/','/recuperar-acceso/','/iniciar-sesion/')):
            response['Cache-Control']='private, no-store'
            response['X-Robots-Tag']='noindex, nofollow'
        if request.path.startswith(('/activar/','/recuperar-acceso/')):
            # Native form POSTs need their same-origin Origin/Referer for CSRF.
            # Cross-origin navigations still receive no Referer (including tokens).
            response['Referrer-Policy']='same-origin'
        return response

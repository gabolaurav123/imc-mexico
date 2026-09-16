from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

class StaffMFAMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        protected = request.path.startswith(('/admin/', '/operaciones/'))
        if protected and request.user.is_authenticated and request.user.is_staff and settings.STAFF_MFA_REQUIRED and not request.user.is_verified():
            return redirect('/panel/seguridad/?next=' + request.path)
        return self.get_response(request)

class SecurityHeadersMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        response['Permissions-Policy']='camera=(self), microphone=(), geolocation=()'
        response['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; media-src 'self' blob:; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith(('/panel/','/admin/','/operaciones/','/api/','/archivos/','/activar/','/recuperar-acceso/','/iniciar-sesion/')):
            response['Cache-Control']='private, no-store'
            response['X-Robots-Tag']='noindex, nofollow'
        if request.path.startswith(('/activar/','/recuperar-acceso/')):
            # Native form POSTs need their same-origin Origin/Referer for CSRF.
            # Cross-origin navigations still receive no Referer (including tokens).
            response['Referrer-Policy']='same-origin'
        return response

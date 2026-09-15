"""Optional, first-party acquisition metrics; never a contact/visitor identity store."""
from datetime import timedelta,timezone as dt_timezone
import json
import logging
import re
import secrets

from django.conf import settings
from django.db import DatabaseError,transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_POST

from .models import AnalysisJob,AnalyticsEvent,Consent,PlatformSettings

CONSENT_COOKIE="imc_analytics_consent"
SESSION_COOKIE="imc_analytics_session"
CONSENT_AGE=180*24*60*60
SESSION_AGE=30*60
COOKIE_SALT="imc.analytics.v1"
SAFE_SLUG=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
SAFE_NONCE=re.compile(r"^[A-Za-z0-9_-]{24,60}$")
EVENTS={"page_view","register_started","register_completed","draft_started","upload_started","file_received","analysis_completed","sheet_reviewed","submission_sent"}
PAGES={"/":"home","/como-funciona/":"how_it_works","/guia-de-fotos/":"photo_guide","/ejemplo-de-ficha/":"example_sheet","/preguntas-frecuentes/":"faq","/contacto/":"contact","/registro/":"register","/iniciar-sesion/":"login","/privacidad/":"privacy","/terminos/":"terms","/panel/":"dashboard","/panel/maquinarias/":"machines","/panel/maquinarias/nueva/":"new_machine","/panel/solicitudes/":"requests","/panel/mensajes/":"messages","/panel/perfil/":"profile"}
PAGE_VALUES=set(PAGES.values())|{"wizard","internal_sheet","shared_sheet","operations","upload","analysis"}
log=logging.getLogger(__name__)


def safe_slug(value):
    value=str(value or "")
    if value.isdigit() or re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",value):return ""
    return value.lower() if SAFE_SLUG.fullmatch(value) else ""


def page_category(path):
    if path in PAGES:return PAGES[path]
    if re.fullmatch(r"/panel/maquinarias/[0-9a-f-]{36}/",path):return "wizard"
    if re.fullmatch(r"/panel/maquinarias/[0-9a-f-]{36}/ficha/",path):return "internal_sheet"
    if re.fullmatch(r"/ficha/[0-9a-f-]{36}/",path):return "shared_sheet"
    if path.startswith("/operaciones/"):return "operations"
    return ""


def device_category(user_agent):
    agent=str(user_agent or "").lower()
    if any(value in agent for value in ("ipad","tablet")):return "tablet"
    if any(value in agent for value in ("mobile","iphone","android")):return "mobile"
    return "desktop" if agent else "unknown"


def actor_category(user):
    if not getattr(user,"is_authenticated",False):return "anonymous"
    if user.is_test or user.email.rsplit("@",1)[-1].lower().endswith(".invalid"):return "test"
    return "staff" if user.is_staff else "registered"


def session_hash(nonce,at=None):
    day=(at or timezone.now()).astimezone(dt_timezone.utc).strftime("%Y-%m-%d")
    return salted_hmac("imc.analytics.session."+day,nonce,algorithm="sha256").hexdigest()


def _session_cookie(request):
    try:
        data=json.loads(request.get_signed_cookie(SESSION_COOKIE,default="{}",salt=COOKIE_SALT,max_age=SESSION_AGE))
        if not isinstance(data,dict) or not SAFE_NONCE.fullmatch(str(data.get("nonce",""))):return None
        expires=data.get("expires")
        if not isinstance(expires,(int,float)) or isinstance(expires,bool) or expires<=timezone.now().timestamp():return None
        return {"nonce":data["nonce"],"expires":expires,"source":safe_slug(data.get("source")),"campaign":safe_slug(data.get("campaign"))}
    except (TypeError,ValueError):return None


def prepare_request(request):
    if hasattr(request,"analytics_settings"):return
    try:configuration=PlatformSettings.objects.filter(pk=1).first()
    except DatabaseError:configuration=None
    request._analytics_platform=configuration
    enabled=bool(configuration and configuration.analytics_enabled)
    require_consent=bool(not configuration or configuration.analytics_require_consent)
    consent=request.get_signed_cookie(CONSENT_COOKIE,default="",salt=COOKIE_SALT,max_age=CONSENT_AGE) if enabled else ""
    if consent not in {"granted","denied"}:consent=""
    request.analytics_settings={"enabled":enabled,"requires_consent":require_consent,"consent":consent}


def capture_context(request,page=None):
    prepare_request(request)
    configuration=request.analytics_settings
    if not configuration["enabled"] or configuration["consent"]=="denied":return {}
    granted=configuration["consent"]=="granted"
    if configuration["requires_consent"] and not granted:return {}
    current_page=page if page in PAGE_VALUES else page_category(request.path)
    context={"source":safe_slug(request.GET.get("utm_source")) or "direct","campaign":safe_slug(request.GET.get("utm_campaign")),
             "device":device_category(request.META.get("HTTP_USER_AGENT")),"page":current_page,
             "actor_type":actor_category(request.user),"session_hash":"","_consent":granted,
             "_expires_at":timezone.now().timestamp()+SESSION_AGE}
    if granted:
        data=getattr(request,"_analytics_session_data",None) or _session_cookie(request)
        if not data:
            data={"nonce":secrets.token_urlsafe(24),"expires":context["_expires_at"],"source":context["source"],"campaign":context["campaign"]}
            request._analytics_cookie_to_set=data
        request._analytics_session_data=data
        context.update(source=data["source"] or "direct",campaign=data["campaign"],session_hash=session_hash(data["nonce"]),_expires_at=data["expires"])
    context["is_test"]=context["actor_type"]=="test"
    return context


def _write_event(name,context):
    if name not in EVENTS or not context:return None
    return AnalyticsEvent.objects.create(event=name,source=safe_slug(context.get("source")),campaign=safe_slug(context.get("campaign")),
        device=context.get("device") if context.get("device") in {"mobile","tablet","desktop","unknown"} else "unknown",
        page=context.get("page") if context.get("page") in PAGE_VALUES else "",actor_type=context.get("actor_type") if context.get("actor_type") in {"anonymous","registered","staff","test"} else "anonymous",
        session_hash=context.get("session_hash","") if context.get("_consent") and re.fullmatch(r"[0-9a-f]{64}",str(context.get("session_hash",""))) else "",is_test=context.get("actor_type")=="test")


def record_event(request,name,machine=None,page=None):
    # machine is accepted for legacy call sites, but its identifier and owner are never persisted here.
    try:
        with transaction.atomic():return _write_event(name,capture_context(request,page))
    except (DatabaseError,ValueError,TypeError):
        log.warning("No se pudo registrar una métrica opcional.")
        return None


def record_job_completion(job):
    """Called from the completion transaction; a revoked or expired context is ignored."""
    try:
        with transaction.atomic():
            job=AnalysisJob.objects.select_for_update().get(pk=job.pk)
            context=job.analytics_context
            if job.status!="completed" or not isinstance(context,dict) or not context or context.get("_recorded"):return
            configuration=PlatformSettings.objects.filter(pk=1).first()
            if configuration and configuration.analytics_enabled and (context.get("_consent") or not configuration.analytics_require_consent) and float(context.get("_expires_at",0))>timezone.now().timestamp():
                _write_event("analysis_completed",{**context,"page":"analysis"})
            job.analytics_context={"_recorded":True}
            job.save(update_fields=["analytics_context"])
    except (DatabaseError,ValueError,TypeError):
        log.warning("No se pudo registrar la métrica opcional de análisis.")


def attach_consent_to_account(request,user):
    prepare_request(request)
    choice=request.analytics_settings["consent"]
    if not request.analytics_settings["enabled"] or choice not in {"granted","denied"}:return
    latest=Consent.objects.filter(user=user,kind="analytics",machine__isnull=True).order_by("-created_at","-pk").first()
    granted=choice=="granted"
    if not latest or latest.granted!=granted:Consent.objects.create(user=user,kind="analytics",granted=granted)


@require_POST
def preferences(request):
    prepare_request(request)
    try:
        data=json.loads(request.body or "{}")
        if not isinstance(data,dict) or set(data)!={"consent"} or not isinstance(data["consent"],bool):raise ValueError
    except (ValueError,UnicodeDecodeError):return JsonResponse({"error":"Indica si permites o rechazas la analítica opcional."},status=400)
    granted=data["consent"]
    if granted and not request.analytics_settings["enabled"]:
        return JsonResponse({"error":"La analítica está desactivada."},status=400)
    choice="granted" if granted else "denied"
    previous_session=_session_cookie(request)
    with transaction.atomic():
        if not granted and request.user.is_authenticated:
            # Jobs already belong to the account. Clearing its pending context also
            # stops a cookie-free aggregate job; no visitor identifier is added.
            AnalysisJob.objects.filter(requested_by=request.user,status__in=['queued','running']).exclude(analytics_context={}).update(analytics_context={})
        if not granted and previous_session:
            hashes=[session_hash(previous_session["nonce"]),session_hash(previous_session["nonce"],timezone.now()-timedelta(days=1))]
            # Withdraw identifiers from this browser's current ephemeral window and queued work.
            for value in hashes:AnalysisJob.objects.filter(analytics_context__session_hash=value).update(analytics_context={})
            AnalyticsEvent.objects.filter(session_hash__in=hashes).update(session_hash="")
        request.analytics_settings["consent"]=choice
        if request.user.is_authenticated:attach_consent_to_account(request,request.user)
    response=JsonResponse({"consent":choice,"enabled":request.analytics_settings["enabled"]})
    if request.analytics_settings["enabled"]:
        response.set_signed_cookie(CONSENT_COOKIE,choice,salt=COOKIE_SALT,max_age=CONSENT_AGE,secure=settings.SESSION_COOKIE_SECURE,httponly=True,samesite="Lax")
    else:response.delete_cookie(CONSENT_COOKIE,samesite="Lax")
    response.delete_cookie(SESSION_COOKIE,samesite="Lax")
    request._analytics_preferences_response=True
    response["Cache-Control"]="private, no-store"
    return response


class AnalyticsMiddleware:
    def __init__(self,get_response):self.get_response=get_response

    def __call__(self,request):
        prepare_request(request)
        response=self.get_response(request)
        if not request.analytics_settings["enabled"]:
            for name in (SESSION_COOKIE,CONSENT_COOKIE):
                if name in request.COOKIES:response.delete_cookie(name,samesite="Lax")
            return response
        if getattr(request,"_analytics_preferences_response",False):return response
        page=page_category(request.path)
        if request.method=="GET" and response.status_code==200 and "text/html" in response.get("Content-Type","") and page:
            record_event(request,"page_view",page=page)
            platform=request._analytics_platform
            if page=="register" and platform.registration_open and platform.legal_validated:
                record_event(request,"register_started",page=page)
        cookie=getattr(request,"_analytics_cookie_to_set",None)
        if cookie:
            response.set_signed_cookie(SESSION_COOKIE,json.dumps(cookie,separators=(",",":")),salt=COOKIE_SALT,max_age=SESSION_AGE,secure=settings.SESSION_COOKIE_SECURE,httponly=True,samesite="Lax")
        return response

import uuid
from string import Template
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from .storage import PrivateStorage


class UserManager(DjangoUserManager):
    def _create_user(self, username=None, email=None, password=None, **extra_fields):
        email = (email or username or "").strip().lower()
        if not email:
            raise ValueError("El correo es obligatorio.")
        return super()._create_user(email, email, password, **extra_fields)

    def create_user(self, username=None, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("El superadministrador requiere is_staff e is_superuser.")
        return self._create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    class AdvertiserStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobado"
        REJECTED = "rejected", "Rechazado"
        SUSPENDED = "suspended", "Suspendido"

    email = models.EmailField("correo", unique=True)
    phone = models.CharField("celular", max_length=32, blank=True)
    contact_preference = models.CharField("contacto preferido", max_length=12, choices=[("whatsapp", "WhatsApp"), ("call", "Llamada"), ("email", "Correo")], default="email")
    advertiser_status = models.CharField("permiso de anunciante", max_length=16, choices=AdvertiserStatus.choices, default=AdvertiserStatus.PENDING)
    email_verified = models.BooleanField("correo verificado", default=False)
    company = models.CharField("empresa", max_length=180, blank=True)
    marketing_consent = models.BooleanField("comunicaciones comerciales", default=False)
    is_test = models.BooleanField("cuenta de prueba", default=False)
    objects = UserManager()
    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        constraints = [models.UniqueConstraint(Lower("email"), name="user_email_case_insensitive")]
        permissions = [("manage_advertisers", "Puede aprobar o suspender anunciantes"), ("operate_platform", "Puede acceder al centro de operaciones")]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        self.username = self.email
        if not self._state.adding and self.pk:
            old_email=type(self).objects.filter(pk=self.pk).values_list("email",flat=True).first()
            if old_email is not None and old_email!=self.email:
                self.email_verified=False
                if kwargs.get("update_fields") and "email" in kwargs["update_fields"]:
                    kwargs["update_fields"]=set(kwargs["update_fields"])|{"email_verified"}
        if kwargs.get("update_fields") and "email" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"username"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.email


class Category(models.Model):
    name = models.CharField("nombre", max_length=100)
    slug = models.SlugField(unique=True)
    fields = models.JSONField("campos específicos", default=list, blank=True)
    active = models.BooleanField("activa", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "categoría"
        verbose_name_plural = "categorías"

    def __str__(self):
        return self.name


class Brand(models.Model):
    name=models.CharField("nombre",max_length=100,unique=True)
    active=models.BooleanField("activa",default=True)

    class Meta:
        ordering=["name"]
        verbose_name="marca"
        verbose_name_plural="marcas"

    def __str__(self):
        return self.name


class EquipmentModel(models.Model):
    brand=models.ForeignKey(Brand,on_delete=models.PROTECT,related_name="equipment_models",verbose_name="marca")
    name=models.CharField("modelo",max_length=100)
    category=models.ForeignKey(Category,on_delete=models.PROTECT,null=True,blank=True,verbose_name="categoría")
    active=models.BooleanField("activo",default=True)

    class Meta:
        ordering=["brand__name","name"]
        verbose_name="modelo de equipo"
        verbose_name_plural="modelos de equipo"
        constraints=[models.UniqueConstraint(fields=["brand","name"],name="unique_brand_equipment_model")]

    def __str__(self):
        return f"{self.brand.name} {self.name}"


class Unit(models.Model):
    name=models.CharField("nombre",max_length=80)
    symbol=models.CharField("símbolo",max_length=20,unique=True)
    dimension=models.CharField("magnitud",max_length=60,blank=True)
    active=models.BooleanField("activa",default=True)

    class Meta:
        ordering=["dimension","name"]
        verbose_name="unidad de medida"
        verbose_name_plural="unidades de medida"

    def __str__(self):
        return f"{self.name} ({self.symbol})"


class WorkflowStatus(models.TextChoices):
    DRAFT = "draft", "Borrador"
    SUBMITTED = "submitted", "Enviada a revisión"
    IN_REVIEW = "in_review", "En revisión"
    CHANGES_REQUESTED = "changes_requested", "Cambios solicitados"
    APPROVED = "approved", "Aprobada"
    REJECTED = "rejected", "Rechazada"
    CANCELLED = "cancelled", "Cancelada"


class Machine(models.Model):
    Status = WorkflowStatus

    class Availability(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        RESERVED = "reserved", "Reservada"
        SOLD = "sold", "Vendida"
        WITHDRAWN = "withdrawn", "Retirada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="machines", verbose_name="propietario")
    title = models.CharField("título", max_length=180, default="Mi maquinaria")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True, verbose_name="categoría")
    data = models.JSONField("datos", default=dict, blank=True)
    provenance = models.JSONField("procedencia y revisión", default=dict, blank=True)
    revision = models.PositiveIntegerField("revisión", default=1)
    status = models.CharField("estado", max_length=24, choices=WorkflowStatus.choices, default=WorkflowStatus.DRAFT, db_index=True)
    availability = models.CharField("disponibilidad", max_length=16, choices=Availability.choices, default=Availability.AVAILABLE)
    approved_version = models.ForeignKey("MachineVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="approved_machines", verbose_name="versión aprobada")
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "maquinaria"
        verbose_name_plural = "maquinarias"
        permissions = [("review_submission", "Puede resolver solicitudes"), ("publish_machine", "Puede habilitar fichas y exportar publicaciones"), ("reassign_machine", "Puede reasignar maquinaria")]
        indexes = [models.Index(fields=["owner", "status"])]

    @property
    def folio(self):
        return f"IMC-{str(self.pk).split('-')[0].upper()}"

    @property
    def editable(self):
        return self.status in {WorkflowStatus.DRAFT, WorkflowStatus.CHANGES_REQUESTED, WorkflowStatus.REJECTED, WorkflowStatus.CANCELLED, WorkflowStatus.APPROVED}

    def __str__(self):
        return f"{self.folio} · {self.title}"


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("El registro histórico es inmutable.")

    def delete(self):
        raise ValidationError("El registro histórico es inmutable.")


class ImmutableModel(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El registro histórico es inmutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El registro histórico es inmutable.")


class MachineVersion(ImmutableModel):
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField("número")
    data = models.JSONField("instantánea", default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["machine", "number"], name="unique_machine_version")]
        ordering = ["-number"]
        verbose_name = "versión de maquinaria"
        verbose_name_plural = "versiones de maquinaria"

    def __str__(self):
        return f"{self.machine.folio} · v{self.number}"


def private_asset_path(instance, filename):
    extension = Path(filename).suffix.lower()[:12]
    return f"machines/{instance.machine_id}/{instance.id}/{uuid.uuid4().hex}{extension}"


class Asset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="assets")
    revision = models.PositiveIntegerField(default=1)
    original = models.FileField("original privado", storage=PrivateStorage(), upload_to=private_asset_path, max_length=500)
    preview = models.FileField("vista optimizada privada", storage=PrivateStorage(), upload_to=private_asset_path, max_length=500, blank=True, null=True)
    kind = models.CharField("tipo", max_length=8, choices=[("image", "Imagen"), ("video", "Video")])
    purpose = models.CharField("contenido", max_length=12, choices=[("general", "Vista general"), ("plate", "Placa"), ("detail", "Detalle"), ("document", "Documento privado")], default="general")
    mime_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    position = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField("portada", default=False)
    public_authorized = models.BooleanField("difusión autorizada", default=False)
    processing_status = models.CharField("procesamiento", max_length=12, choices=[("ready", "Listo"), ("pending", "Pendiente"), ("failed", "Fallido")], default="pending")
    error = models.TextField("error", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "created_at"]
        verbose_name = "archivo privado"
        verbose_name_plural = "archivos privados"

    def __str__(self):
        return f"{self.machine.folio} · {self.get_purpose_display()}"


class Submission(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="submissions")
    version = models.ForeignKey(MachineVersion, on_delete=models.PROTECT)
    status = models.CharField("estado", max_length=24, choices=WorkflowStatus.choices, default=WorkflowStatus.SUBMITTED, db_index=True)
    message = models.TextField("observaciones", blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="decisions")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "solicitud"
        verbose_name_plural = "solicitudes"

    def __str__(self):
        return f"{self.machine.folio} · {self.get_status_display()}"


class Publication(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="publications")
    version = models.ForeignKey(MachineVersion, on_delete=models.PROTECT, null=True, blank=True)
    destination = models.CharField("destino", max_length=8, choices=[("share", "Ficha compartible"), ("main", "Portal principal")], default="share")
    status = models.CharField("estado", max_length=16, choices=[("unpublished", "Sin publicar"), ("approved", "Aprobada"), ("exported", "Exportada"), ("published", "Publicada"), ("failed", "Error"), ("disabled", "Deshabilitada")], default="unpublished")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    enabled = models.BooleanField("habilitada", default=False)
    external_id = models.CharField("identificador externo", max_length=200, blank=True)
    external_url = models.URLField("enlace externo", blank=True)
    last_error = models.TextField("último error", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["machine", "destination"], name="unique_publication_destination")]
        verbose_name = "publicación"
        verbose_name_plural = "publicaciones"

    def clean(self):
        if self.version_id and self.version.machine_id != self.machine_id:
            raise ValidationError("La versión no pertenece a esta maquinaria.")
        if self.enabled and (not self.version_id or self.machine.approved_version_id != self.version_id or self.machine.owner.advertiser_status != "approved"):
            raise ValidationError("Se requiere una versión y un anunciante aprobados.")

    def __str__(self):
        return f"{self.machine.folio} · {self.get_destination_display()}"


class Message(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField("mensaje")
    internal = models.BooleanField("nota interna", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "mensaje"
        verbose_name_plural = "mensajes"


class Consent(ImmutableModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="consents")
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, null=True, blank=True, related_name="consents")
    kind = models.CharField("tipo", max_length=12, choices=[("terms", "Términos"), ("privacy", "Privacidad"), ("ai", "Análisis IA"), ("advertise", "Difusión"), ("contact", "Contacto público"), ("marketing", "Marketing")])
    version = models.CharField(max_length=32, default="2026-09")
    granted = models.BooleanField("otorgado", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "consentimiento"
        verbose_name_plural = "consentimientos"


class AnalysisJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="analysis_jobs")
    revision = models.PositiveIntegerField()
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="analysis_jobs")
    asset_ids = models.JSONField(default=list)
    mode = models.CharField(max_length=12, choices=[("analysis", "Análisis"), ("description", "Descripción")], default="analysis")
    fingerprint = models.CharField(max_length=64, unique=True)
    status = models.CharField("estado", max_length=12, choices=[("queued", "En cola"), ("running", "En curso"), ("completed", "Completado"), ("failed", "Fallido")], default="queued", db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    model = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=40, default="2026-09-01")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    reserved_tokens = models.PositiveIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "trabajo de IA"
        verbose_name_plural = "trabajos de IA"
        indexes = [models.Index(fields=["status", "created_at"])]


class AuditEvent(ImmutableModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    action = models.CharField("acción", max_length=100, db_index=True)
    object_type = models.CharField("tipo", max_length=100)
    object_id = models.CharField("identificador", max_length=100)
    metadata = models.JSONField("detalle", default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "evento de auditoría"
        verbose_name_plural = "auditoría"


class Lead(models.Model):
    name = models.CharField("nombre", max_length=180)
    email = models.EmailField("correo")
    phone = models.CharField("teléfono", max_length=32, blank=True)
    message = models.TextField("mensaje")
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="leads")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="assigned_leads")
    priority = models.CharField("prioridad", max_length=8, choices=[("low", "Baja"), ("normal", "Normal"), ("high", "Alta")], default="normal")
    status = models.CharField("estado", max_length=12, choices=[("new", "Nuevo"), ("contacted", "Contactado"), ("qualified", "Calificado"), ("closed", "Cerrado")], default="new")
    next_action_at = models.DateTimeField("próximo seguimiento", null=True, blank=True)
    internal_notes = models.TextField("notas internas", blank=True)
    is_test = models.BooleanField("prueba", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "contacto comercial"
        verbose_name_plural = "contactos comerciales"


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notifications")
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, null=True, blank=True)
    kind = models.CharField(max_length=60)
    subject = models.CharField("asunto", max_length=180)
    body = models.TextField("contenido")
    channel = models.CharField("canal", max_length=8, choices=[("in_app", "En plataforma"), ("email", "Correo")], default="in_app")
    status = models.CharField("estado", max_length=8, choices=[("pending", "Pendiente"), ("sent", "Enviada"), ("failed", "Fallida")], default="pending")
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"


class NotificationTemplate(models.Model):
    key=models.SlugField("clave",unique=True,choices=[("submission","Solicitud recibida"),("review_in_review","Revisión iniciada"),("review_changes_requested","Correcciones solicitadas"),("review_approved","Ficha aprobada"),("review_rejected","Ficha rechazada"),("review_cancelled","Solicitud cancelada"),("advertiser","Permiso de anunciante"),("reminder","Recordatorio"),("reassignment","Reasignación")])
    subject=models.CharField("asunto",max_length=180)
    body=models.TextField("contenido en texto plano",help_text="Variables admitidas: $folio, $status, $reason, $title, $name y $portal_url. Usa $$ para un signo de dólar literal.")
    active=models.BooleanField("activa",default=True)

    class Meta:
        ordering=["key"]
        verbose_name="plantilla de notificación"
        verbose_name_plural="plantillas de notificaciones"

    def clean(self):
        allowed={"folio","status","reason","title","name","portal_url"}
        for field in ("subject","body"):
            text=getattr(self,field)
            template=Template(text)
            if not template.is_valid() or set(template.get_identifiers())-allowed:
                raise ValidationError({field:"Usa únicamente las variables indicadas; no se ejecutan expresiones ni HTML."})
        if len(self.body)>12000:
            raise ValidationError({"body":"La plantilla admite hasta 12000 caracteres."})

    def __str__(self):
        return self.get_key_display()


class SiteContent(models.Model):
    key = models.SlugField("clave", unique=True)
    title = models.CharField("título", max_length=180)
    body = models.TextField("contenido en texto plano")
    active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "contenido público"
        verbose_name_plural = "contenidos públicos"

    def __str__(self):
        return self.title


class PlatformSettings(models.Model):
    registration_open=models.BooleanField("registro público abierto",default=False,help_text="Sólo abre registros cuando los documentos legales también estén validados.")
    ai_enabled = models.BooleanField("IA habilitada", default=False)
    max_images = models.PositiveSmallIntegerField("máximo de fotografías", default=20, validators=[MinValueValidator(1), MaxValueValidator(100)])
    max_image_mb = models.PositiveSmallIntegerField("MB por imagen", default=20, validators=[MinValueValidator(1), MaxValueValidator(100)])
    max_video_mb = models.PositiveSmallIntegerField("MB por video", default=100, validators=[MinValueValidator(1), MaxValueValidator(1000)])
    max_video_seconds = models.PositiveIntegerField("segundos por video", default=120, validators=[MinValueValidator(1), MaxValueValidator(1800)])
    ai_user_daily_limit = models.PositiveIntegerField("trabajos por usuario/día", default=10)
    ai_global_daily_limit = models.PositiveIntegerField("trabajos globales/día", default=100)
    ai_daily_token_limit = models.PositiveIntegerField("límite global tokens/día", default=200000)
    ai_max_attempts = models.PositiveSmallIntegerField("intentos IA", default=2, validators=[MinValueValidator(1), MaxValueValidator(5)])
    legal_validated = models.BooleanField("documentos legales validados por IMC", default=False)
    contact_email = models.EmailField("correo comercial", blank=True)
    contact_phone = models.CharField("teléfono comercial", max_length=32, blank=True)
    retention_days = models.PositiveIntegerField("días de conservación", default=365, validators=[MinValueValidator(30)])

    class Meta:
        verbose_name = "configuración"
        verbose_name_plural = "configuración de la plataforma"

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

    get_solo = load

    def __str__(self):
        return "Configuración de IMC"


class AnalyticsEvent(models.Model):
    event = models.CharField("evento", max_length=80, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True)
    session_hash = models.CharField(max_length=64, blank=True)
    source = models.CharField("origen", max_length=100, blank=True)
    campaign = models.CharField("campaña", max_length=100, blank=True)
    device = models.CharField("dispositivo", max_length=30, blank=True)
    is_test = models.BooleanField("prueba", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "evento de analítica"
        verbose_name_plural = "analítica"
        permissions=[("export_analytics","Puede exportar eventos de analítica")]


class RateLimit(models.Model):
    key = models.CharField(max_length=128, unique=True)
    count = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()


class AccountRequest(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="account_requests")
    kind = models.CharField("solicitud", max_length=12, choices=[("export", "Exportar mis datos"), ("delete", "Eliminar mi cuenta"), ("correction", "Corregir mis datos")])
    detail = models.TextField("detalle", blank=True)
    status = models.CharField("estado", max_length=16, choices=[("pending", "Pendiente"), ("in_progress", "En proceso"), ("completed", "Completada")], default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "solicitud sobre datos personales"
        verbose_name_plural = "solicitudes sobre datos personales"

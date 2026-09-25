import uuid
import secrets
from datetime import timedelta
from decimal import Decimal
from string import Template
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

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
    # This is a technical principal for a short-lived visitor capability.  It
    # is never a person, advertiser, login or contact record.
    is_guest = models.BooleanField("principal técnico temporal", default=False, db_index=True)
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


class ActiveMachineManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


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
    deleted_at = models.DateTimeField("en papelera desde", null=True, blank=True, db_index=True, editable=False)
    objects = ActiveMachineManager()
    all_objects = models.Manager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
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
        return self.deleted_at is None and self.status in {WorkflowStatus.DRAFT, WorkflowStatus.CHANGES_REQUESTED, WorkflowStatus.REJECTED, WorkflowStatus.CANCELLED, WorkflowStatus.APPROVED}

    @property
    def can_delete_draft(self):
        return (self.deleted_at is None and self.status == WorkflowStatus.DRAFT
                and self.approved_version_id is None
                and not self.publications.filter(models.Q(enabled=True) | models.Q(status="published")).exists())

    def __str__(self):
        return f"{self.folio} · {self.title}"


def guest_draft_expiry():
    return timezone.now() + timedelta(hours=24)


class GuestDraft(models.Model):
    """A session-capability wrapper around one normal private Machine.

    The temporary owner is a non-login technical User so Asset and AnalysisJob
    keep their normal foreign keys.  Claiming changes that Machine's owner;
    no files, analysis jobs, or second machine are copied.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                 related_name="guest_draft")
    machine = models.OneToOneField(Machine, on_delete=models.PROTECT, related_name="guest_draft")
    secret_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(default=guest_draft_expiry, db_index=True)
    claimed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="claimed_guest_drafts")
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "borrador temporal"
        verbose_name_plural = "borradores temporales"

    @property
    def expired(self):
        return self.expires_at <= timezone.now()

    @property
    def claimable(self):
        return self.claimed_by_id is None and not self.expired


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
    # These are a materialized, immutable projection of ``data`` at version
    # creation. They are intentionally not editable listing fields.
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="machine_versions", verbose_name="categoría indexada")
    brand = models.CharField("marca indexada", max_length=100, blank=True)
    model = models.CharField("modelo indexado", max_length=100, blank=True)
    variant = models.CharField("variante indexada", max_length=180, blank=True)
    undercarriage = models.CharField("rodamiento indexado", max_length=32, blank=True)
    hours = models.DecimalField("horas indexadas", max_digits=14, decimal_places=2, null=True, blank=True,
                                validators=[MinValueValidator(0)])
    year = models.PositiveSmallIntegerField("año exacto indexado", null=True, blank=True,
                                            validators=[MinValueValidator(1800), MaxValueValidator(2200)])
    estimated_year_from = models.PositiveSmallIntegerField("año estimado desde", null=True, blank=True,
                                                           validators=[MinValueValidator(1800), MaxValueValidator(2200)])
    estimated_year_to = models.PositiveSmallIntegerField("año estimado hasta", null=True, blank=True,
                                                         validators=[MinValueValidator(1800), MaxValueValidator(2200)])
    price = models.DecimalField("precio indexado", max_digits=16, decimal_places=2, null=True, blank=True,
                                validators=[MinValueValidator(0)])
    currency = models.CharField("moneda indexada", max_length=3, blank=True)
    weight_kg = models.DecimalField("peso kg indexado", max_digits=14, decimal_places=3, null=True, blank=True,
                                    validators=[MinValueValidator(0)])
    digging_depth_m = models.DecimalField("profundidad m indexada", max_digits=12, decimal_places=3, null=True, blank=True,
                                          validators=[MinValueValidator(0)])
    location_country = models.CharField("país indexado", max_length=80, blank=True)
    location_region = models.CharField("estado o provincia indexado", max_length=120, blank=True)
    location_city = models.CharField("ciudad indexada", max_length=120, blank=True)
    preservation_condition = models.CharField("conservación indexada", max_length=16, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["machine", "number"], name="unique_machine_version")]
        indexes = [
            models.Index(fields=["category", "brand", "model", "variant", "undercarriage"], name="version_identity_search"),
            models.Index(fields=["category", "year", "estimated_year_from", "estimated_year_to"], name="version_year_search"),
            models.Index(fields=["category", "currency", "price"], name="version_price_search"),
            models.Index(fields=["category", "location_country", "location_region", "location_city"], name="version_location_search"),
            models.Index(fields=["category", "weight_kg", "digging_depth_m", "hours"], name="version_specs_search"),
        ]
        ordering = ["-number"]
        verbose_name = "versión de maquinaria"
        verbose_name_plural = "versiones de maquinaria"

    def __str__(self):
        return f"{self.machine.folio} · v{self.number}"

    def clean(self):
        errors = {}
        if self.estimated_year_from and self.estimated_year_to and self.estimated_year_from > self.estimated_year_to:
            errors["estimated_year_to"] = "El final del intervalo no puede ser anterior al inicio."
        if self.currency and len(self.currency) != 3:
            errors["currency"] = "La moneda debe usar el código ISO de tres letras."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:
            from .structured_data import version_search_fields
            values = version_search_fields(self.data, self.machine.category, self.data.get("provenance") if isinstance(self.data, dict) else None)
            for name, value in values.items():
                setattr(self, name, value)
            self.clean()
        return super().save(*args, **kwargs)


class TechnicalReference(models.Model):
    """Reviewed manufacturer documentation for a model, never unit evidence."""
    class Review(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobada"
        REJECTED = "rejected", "Rechazada"

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="technical_references",
                                 verbose_name="categoría")
    equipment_model = models.ForeignKey(EquipmentModel, on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="technical_references", verbose_name="modelo del catálogo")
    brand = models.CharField("marca", max_length=100)
    model = models.CharField("modelo", max_length=100)
    variant = models.CharField("variante", max_length=180, blank=True)
    generation = models.CharField("generación", max_length=120, blank=True)
    market = models.CharField("mercado", max_length=80, blank=True)
    period_from = models.PositiveSmallIntegerField("periodo desde", null=True, blank=True,
                                                   validators=[MinValueValidator(1800), MaxValueValidator(2200)])
    period_to = models.PositiveSmallIntegerField("periodo hasta", null=True, blank=True,
                                                 validators=[MinValueValidator(1800), MaxValueValidator(2200)])
    specs = models.JSONField("especificaciones documentadas", default=dict, blank=True)
    provenance = models.JSONField("procedencia", default=dict, blank=True)
    source = models.URLField("fuente primaria", max_length=1000)
    source_title = models.CharField("título de fuente", max_length=300)
    source_version = models.CharField("versión de fuente", max_length=100, blank=True)
    retrieved_at = models.DateField("consultada el")
    review = models.CharField("revisión", max_length=12, choices=Review.choices, default=Review.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="reviewed_technical_references", verbose_name="revisada por")
    reviewed_at = models.DateTimeField("revisada el", null=True, blank=True)
    active = models.BooleanField("activa", default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__name", "brand", "model", "variant", "market"]
        verbose_name = "referencia técnica"
        verbose_name_plural = "referencias técnicas"
        indexes = [models.Index(fields=["category", "brand", "model", "variant", "market", "active"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(active=False) | models.Q(review="approved"),
                name="technical_active_requires_approval",
            ),
            models.CheckConstraint(
                condition=(models.Q(period_from__isnull=True) | models.Q(period_to__isnull=True)
                           | models.Q(period_from__lte=models.F("period_to"))),
                name="technical_period_is_ordered",
            ),
        ]

    def clean(self):
        errors = {}
        if self.equipment_model_id:
            from .research import identifier_key, _brand_key
            catalogue = self.equipment_model
            if (catalogue.category_id != self.category_id or
                    _brand_key(catalogue.brand.name) != _brand_key(self.brand) or
                    identifier_key(catalogue.name) != identifier_key(self.model)):
                errors["equipment_model"] = "El modelo del catálogo debe coincidir con la categoría, marca y modelo de la referencia."
        if self.period_from and self.period_to and self.period_from > self.period_to:
            errors["period_to"] = "El final del periodo no puede ser anterior al inicio."
        maximum_year = timezone.localdate().year + 1
        for field in ("period_from", "period_to"):
            if getattr(self, field) and getattr(self, field) > maximum_year:
                errors[field] = f"El año no puede ser posterior a {maximum_year}."
        if self.retrieved_at and self.retrieved_at > timezone.localdate():
            errors["retrieved_at"] = "La fecha de consulta no puede estar en el futuro."
        if self.active and self.review != self.Review.APPROVED:
            errors["active"] = "Sólo una referencia aprobada puede activarse."
        if not isinstance(self.specs, dict):
            errors["specs"] = "Las especificaciones deben ser un objeto estructurado."
        if not isinstance(self.provenance, dict):
            errors["provenance"] = "La procedencia debe ser un objeto estructurado."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        label = " ".join(part for part in (self.brand, self.model, self.variant) if part)
        return f"{self.category.name} · {label}"


class MarketReference(models.Model):
    """A dated market listing. It is never a technical specification source."""
    class Review(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobada"
        REJECTED = "rejected", "Rechazada"

    class PriceType(models.TextChoices):
        ASKING = "asking", "Precio anunciado"
        SOLD = "sold", "Precio de venta"

    class Condition(models.TextChoices):
        NEW = "new", "Nueva"
        USED = "used", "Usada"
        REFURBISHED = "refurbished", "Reacondicionada"
        FOR_REPAIR = "for_repair", "Para reparación"
        UNKNOWN = "unknown", "Sin confirmar"

    equipment_model = models.ForeignKey(EquipmentModel, on_delete=models.PROTECT, related_name="market_references",
                                        verbose_name="modelo del catálogo")
    source = models.URLField("URL de fuente", max_length=1000, unique=True)
    source_title = models.CharField("título de fuente", max_length=300)
    price = models.DecimalField("precio", max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField("moneda", max_length=3, choices=[("USD", "USD"), ("MXN", "MXN"), ("EUR", "EUR")])
    market = models.CharField("mercado", max_length=2)
    price_type = models.CharField("tipo de precio", max_length=10, choices=PriceType.choices, default=PriceType.ASKING)
    condition = models.CharField("condición", max_length=16, choices=Condition.choices, default=Condition.UNKNOWN)
    year = models.PositiveSmallIntegerField("año", null=True, blank=True, validators=[MinValueValidator(1800), MaxValueValidator(2200)])
    hours = models.DecimalField("horas", max_digits=12, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(0)])
    retrieved_at = models.DateField("consultada el")
    evidence = models.TextField("evidencia")
    configurations = models.JSONField("configuración", default=dict, blank=True)
    unit_key = models.CharField("clave de unidad", max_length=128, blank=True)
    review = models.CharField("revisión", max_length=12, choices=Review.choices, default=Review.PENDING, db_index=True)
    active = models.BooleanField("activa", default=False, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="reviewed_market_references", verbose_name="revisada por")
    reviewed_at = models.DateTimeField("revisada el", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["equipment_model__brand__name", "equipment_model__name", "-retrieved_at"]
        verbose_name = "referencia de mercado"
        verbose_name_plural = "referencias de mercado"
        indexes = [models.Index(fields=["equipment_model", "market", "currency", "price_type", "condition", "active"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(active=False) | models.Q(review="approved"),
                name="market_active_requires_approval",
            ),
            models.CheckConstraint(condition=models.Q(price__gt=0), name="market_price_is_positive"),
        ]

    def clean(self):
        errors = {}
        if self.active and self.review != self.Review.APPROVED:
            errors["active"] = "Sólo una referencia aprobada puede activarse."
        if self.market and (len(self.market) != 2 or not self.market.isalpha()):
            errors["market"] = "El mercado debe usar un código de país ISO de dos letras."
        if self.year and self.year > timezone.localdate().year + 1:
            errors["year"] = f"El año no puede ser posterior a {timezone.localdate().year + 1}."
        if self.retrieved_at and self.retrieved_at > timezone.localdate():
            errors["retrieved_at"] = "La fecha de consulta no puede estar en el futuro."
        if not isinstance(self.configurations, dict):
            errors["configurations"] = "La configuración debe ser un objeto estructurado."
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            errors["evidence"] = "Registra la evidencia del anuncio fechado."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.equipment_model} · {self.price} {self.currency} · {self.market}"


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


def prepared_share_code():
    # 96 random bits, short enough to copy without exposing sequential IDs.
    return secrets.token_urlsafe(12)


class PreparedShare(models.Model):
    """Owner-authorized web snapshot; never an approved catalogue publication."""
    machine = models.OneToOneField(Machine, on_delete=models.PROTECT, related_name="prepared_share")
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    code = models.CharField(max_length=20, unique=True, default=prepared_share_code, editable=False)
    enabled = models.BooleanField(default=False)
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    include_serial = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "enlace de ficha preparada"
        verbose_name_plural = "enlaces de fichas preparadas"


class Publication(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="publications")
    version = models.ForeignKey(MachineVersion, on_delete=models.PROTECT, null=True, blank=True)
    destination = models.CharField("destino", max_length=8, choices=[("share", "Ficha compartible"), ("main", "Portal principal")], default="share")
    status = models.CharField("estado", max_length=16, choices=[("unpublished", "Sin publicar"), ("approved", "Aprobada"), ("exported", "Exportada"), ("published", "Publicada"), ("failed", "Error"), ("disabled", "Deshabilitada")], default="unpublished")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    enabled = models.BooleanField("habilitada", default=False)
    external_id = models.CharField("identificador externo", max_length=200, blank=True)
    external_reference = models.CharField("referencia visible externa", max_length=200, blank=True)
    external_url = models.URLField("enlace externo", blank=True)
    imc_asset_ids = models.JSONField("medios seleccionados para IMC", default=list, blank=True)
    imc_selection_version = models.ForeignKey(MachineVersion, on_delete=models.PROTECT, null=True, blank=True,
                                              related_name="imc_media_selections", verbose_name="versión de medios IMC")
    integration_state = models.CharField("estado de integración", max_length=16,
                                         choices=[("pending", "Pendiente"), ("acknowledged", "Acusada")],
                                         default="pending")
    acknowledged_at = models.DateTimeField("acuse registrado", null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                        null=True, blank=True, related_name="acknowledged_publications",
                                        verbose_name="acuse registrado por")
    current_delivery = models.ForeignKey("IntegrationDelivery", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="+", verbose_name="entrega activa")
    last_error = models.TextField("último error", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["machine", "destination"], name="unique_publication_destination"),
            models.UniqueConstraint(fields=["destination", "external_id"],
                                    condition=models.Q(destination="main") & ~models.Q(external_id=""),
                                    name="unique_main_external_id"),
        ]
        verbose_name = "publicación"
        verbose_name_plural = "publicaciones"

    def clean(self):
        if self.machine_id and self.machine.deleted_at is not None:
            raise ValidationError("La maquinaria está en la papelera.")
        if self.version_id and self.version.machine_id != self.machine_id:
            raise ValidationError("La versión no pertenece a esta maquinaria.")
        if self.enabled and (not self.version_id or self.machine.approved_version_id != self.version_id or self.machine.owner.advertiser_status != "approved"):
            raise ValidationError("Se requiere una versión y un anunciante aprobados.")
        if self.current_delivery_id and self.current_delivery.publication_id != self.pk:
            raise ValidationError("La entrega activa no pertenece a esta publicación.")
        if self.imc_selection_version_id and self.imc_selection_version.machine_id != self.machine_id:
            raise ValidationError("La selección de medios no pertenece a esta maquinaria.")

    def __str__(self):
        return f"{self.machine.folio} · {self.get_destination_display()}"


class IntegrationDelivery(models.Model):
    """Local, auditable handoff record. It never performs a remote request."""
    class State(models.TextChoices):
        PREPARED = "prepared", "Preparada"
        ACKNOWLEDGED = "acknowledged", "Acusada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT, related_name="deliveries")
    version = models.ForeignKey(MachineVersion, on_delete=models.PROTECT, related_name="integration_deliveries")
    source_machine_id = models.UUIDField("identificador estable de maquinaria", editable=False)
    payload = models.JSONField("carga preparada", default=dict)
    payload_sha256 = models.CharField("huella de carga", max_length=64)
    state = models.CharField("estado", max_length=16, choices=State.choices, default=State.PREPARED, db_index=True)
    receipt = models.JSONField("acuse remoto declarado", default=dict, blank=True)
    evidence = models.TextField("evidencia independiente", blank=True)
    manual_metadata = models.JSONField("bitácora manual de preparación", default=dict, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="acknowledged_deliveries")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["publication", "version", "payload_sha256"],
                                               name="unique_delivery_payload_version")]
        verbose_name = "entrega de integración"
        verbose_name_plural = "entregas de integración"

    def clean(self):
        if self.publication_id and self.version_id and self.publication.machine_id != self.version.machine_id:
            raise ValidationError("La versión de la entrega no pertenece a la publicación.")
        if self.publication_id and self.source_machine_id and self.publication.machine_id != self.source_machine_id:
            raise ValidationError("La correlación estable no corresponde a la publicación.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values(
                "publication_id", "version_id", "source_machine_id", "payload", "payload_sha256", "state",
                "receipt", "evidence").first()
            if previous:
                immutable = ("publication_id", "version_id", "source_machine_id", "payload", "payload_sha256")
                if any(previous[name] != getattr(self, name) for name in immutable):
                    raise ValidationError("La carga y los vínculos de una entrega son inmutables.")
                if previous["state"] == self.State.ACKNOWLEDGED and (
                        previous["receipt"] != self.receipt or previous["evidence"] != self.evidence):
                    raise ValidationError("El acuse de una entrega ya confirmada es inmutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.publication} · {self.get_state_display()}"


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
    kind = models.CharField("tipo", max_length=12, choices=[("terms", "Términos"), ("privacy", "Privacidad"), ("ai", "Análisis IA"), ("advertise", "Difusión"), ("contact", "Contacto público"), ("marketing", "Marketing"), ("analytics", "Analítica opcional")])
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
    auto_apply = models.BooleanField("completar huecos del borrador automáticamente", default=False)
    application_snapshot = models.JSONField("base para completar el borrador", default=dict, blank=True)
    application_result = models.JSONField("resultado del completado automático", default=dict, blank=True)
    analytics_context=models.JSONField("contexto de analítica opcional",default=dict,blank=True)
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


def account_access_expiry():
    return timezone.now() + timedelta(days=90)


class AccountAccess(models.Model):
    """Short-lived security history for authenticated accounts, not analytics."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_history", verbose_name="cuenta")
    event = models.CharField("evento", max_length=20, choices=[("login", "Inicio de sesión"), ("session", "Sesión activa"), ("mfa_verified", "Segundo factor verificado")])
    connection_ip = models.GenericIPAddressField("IP de conexión", null=True, blank=True, help_text="Dirección observada por el servidor; puede corresponder al proxy del alojamiento.")
    forwarded_ip = models.GenericIPAddressField("IP declarada por la cabecera de red", null=True, blank=True, help_text="Dato no verificado de X-Forwarded-For. No se usa para autorizar ni identifica una ubicación física.")
    device = models.CharField("tipo de dispositivo", max_length=10, choices=[("desktop", "Computadora"), ("mobile", "Celular"), ("tablet", "Tableta"), ("unknown", "Sin identificar")], default="unknown")
    created_at = models.DateTimeField("fecha", auto_now_add=True)
    expires_at = models.DateTimeField("eliminar después de", default=account_access_expiry, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "acceso de cuenta"
        verbose_name_plural = "accesos e IP de cuentas"
        default_permissions = ("view",)
        indexes = [models.Index(fields=["user", "created_at"], name="account_access_user_date")]

    def __str__(self):
        return f"{self.user.email} · {self.get_event_display()}"


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
    read_at = models.DateTimeField("leída el", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"
        indexes = [models.Index(fields=["user", "channel", "status", "read_at"], name="notification_inbox_unread")]


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
    registration_open=models.BooleanField("registro público abierto",default=True,help_text="Permite crear cuentas y preparar borradores. Puedes desactivarlo para pausar nuevos registros; no concede permisos de anunciante ni de administración.")
    analytics_enabled=models.BooleanField("analítica de adquisición habilitada",default=False)
    analytics_require_consent=models.BooleanField("analítica sólo con consentimiento",default=True,help_text="Si se desactiva este requisito, sólo se recogen contadores agregados sin cookies ni identificadores hasta una aceptación expresa. Un rechazo siempre detiene la captura.")
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
    actor_type=models.CharField("tipo de visitante",max_length=12,choices=[("anonymous","Anónimo"),("registered","Registrado sin identificar"),("staff","Equipo interno"),("test","Prueba")],default="anonymous",db_index=True)
    page=models.CharField("área de navegación",max_length=40,blank=True)
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

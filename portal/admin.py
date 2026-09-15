from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.utils.html import format_html
import json

from .models import (AccountRequest, AnalyticsEvent, AnalysisJob, Asset, AuditEvent, Category,
                     Consent, Lead, Machine, MachineVersion, Message, Notification,
                     PlatformSettings, Publication, SiteContent, Submission, User)
from .services import audit, review_submission, save_draft, set_advertiser_status, set_availability, set_publication


admin.site.site_header = "IMC México · Administración"
admin.site.site_title = "IMC México"
admin.site.index_title = "Operación de la plataforma"


class ReasonActionForm(ActionForm):
    reason = forms.CharField(label="Motivo de la decisión", required=False, max_length=2000)


class AuditedAdmin(admin.ModelAdmin):
    list_per_page = 30
    save_on_top = True

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit(request.user, "admin.changed" if change else "admin.created", obj, {"fields": form.changed_data})

    def has_delete_permission(self, request, obj=None):
        return False


class HistoricalAdmin(AuditedAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class SafeUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name")


class SafeUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = SafeUserChangeForm
    add_form = SafeUserCreationForm
    list_display = ("email", "first_name", "phone", "advertiser_status", "email_verified", "is_active", "is_staff", "is_test")
    list_filter = ("advertiser_status", "email_verified", "is_staff", "is_active", "is_test")
    search_fields = ("email", "first_name", "last_name", "phone", "company")
    ordering = ("-date_joined",)
    list_per_page = 30
    action_form = ReasonActionForm
    actions = ("approve_advertisers", "reject_advertisers", "suspend_advertisers")
    readonly_fields = ("username", "advertiser_status", "email_verified", "last_login", "date_joined")
    fieldsets = (
        ("Identidad", {"fields": ("email", "username", "password", "first_name", "last_name", "phone", "company", "contact_preference")}),
        ("Cuenta y anuncio", {"fields": ("is_active", "advertiser_status", "email_verified", "marketing_consent", "is_test")}),
        ("Permisos", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Actividad", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "first_name", "last_name", "password1", "password2")}),)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser or (obj and request.user.pk == obj.pk):
            fields.extend(["is_staff", "is_superuser", "groups", "user_permissions"])
        if obj and (obj.is_superuser or obj.is_staff) and not request.user.is_superuser:
            fields.extend(["email", "password", "is_active"])
        return fields

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj and (obj.is_staff or obj.is_superuser) and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        permission_fields = {"is_staff", "is_superuser", "groups", "user_permissions"}
        if permission_fields.intersection(form.changed_data) and (not request.user.is_superuser or request.user.pk == obj.pk):
            raise PermissionDenied("No puedes modificar tus propios roles ni elevar permisos.")
        super().save_model(request, obj, form, change)
        audit(request.user, "user.admin_changed" if change else "user.admin_created", obj,
              {"fields": [name for name in form.changed_data if not name.startswith("password")]})

    def _status_action(self, request, queryset, status):
        reason = request.POST.get("reason", "")
        for obj in queryset:
            try:
                set_advertiser_status(obj, request.user, status, reason)
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f"{obj.email}: {exc}", messages.ERROR)
            else:
                self.message_user(request, f"{obj.email}: permiso actualizado.", messages.SUCCESS)

    @admin.action(description="Aprobar anunciantes (indica motivo)")
    def approve_advertisers(self, request, queryset):
        self._status_action(request, queryset, "approved")

    @admin.action(description="Rechazar anunciantes (indica motivo)")
    def reject_advertisers(self, request, queryset):
        self._status_action(request, queryset, "rejected")

    @admin.action(description="Suspender anunciantes (indica motivo)")
    def suspend_advertisers(self, request, queryset):
        self._status_action(request, queryset, "suspended")


@admin.register(Category)
class CategoryAdmin(AuditedAdmin):
    list_display = ("name", "slug", "active")
    list_filter = ("active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class AssetInline(admin.TabularInline):
    model = Asset
    fields = ("private_link", "purpose", "public_authorized", "is_cover", "processing_status")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Archivo")
    def private_link(self, obj):
        return format_html('<a href="/archivos/{}/" target="_blank" rel="noopener">Ver archivo privado</a>', obj.pk)


class MachineForm(forms.ModelForm):
    class Meta:
        model = Machine
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and not self.instance.editable:
            editable_fields = {"title", "category", "data", "provenance"}
            if editable_fields.intersection(self.changed_data):
                raise ValidationError("Solicita cambios antes de editar una maquinaria en revisión.")
        return cleaned


@admin.register(Machine)
class MachineAdmin(AuditedAdmin):
    form = MachineForm
    list_display = ("folio", "title", "owner", "category", "status", "availability", "revision", "updated_at")
    list_filter = ("status", "availability", "category", "owner__is_test")
    search_fields = ("id", "title", "owner__email", "data__brand", "data__model", "data__location")
    readonly_fields = ("id", "folio", "owner", "status", "availability", "revision", "approved_version", "created_at", "updated_at")
    list_select_related = ("owner", "category")
    inlines = (AssetInline,)
    actions = ("mark_sold", "mark_withdrawn", "enable_share", "disable_share")

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        saved = save_draft(obj, request.user, {"title": obj.title, "category": obj.category_id,
                          "data": obj.data, "provenance": obj.provenance}, obj.revision)
        obj.revision = saved.revision
        obj.status = saved.status

    def _availability(self, request, queryset, value):
        for obj in queryset:
            set_availability(obj, request.user, value)
        self.message_user(request, "Disponibilidad actualizada.")

    @admin.action(description="Marcar como vendida")
    def mark_sold(self, request, queryset):
        self._availability(request, queryset, "sold")

    @admin.action(description="Retirar y deshabilitar fichas públicas")
    def mark_withdrawn(self, request, queryset):
        self._availability(request, queryset, "withdrawn")

    def _share(self, request, queryset, enabled):
        for obj in queryset:
            try:
                set_publication(obj, request.user, enabled)
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f"{obj.folio}: {exc}", messages.ERROR)
            else:
                self.message_user(request, f"{obj.folio}: ficha {'habilitada' if enabled else 'deshabilitada'}.")

    @admin.action(description="Habilitar ficha de versión aprobada")
    def enable_share(self, request, queryset):
        self._share(request, queryset, True)

    @admin.action(description="Deshabilitar ficha pública")
    def disable_share(self, request, queryset):
        self._share(request, queryset, False)


@admin.register(Asset)
class AssetAdmin(AuditedAdmin):
    list_display = ("id", "machine", "purpose", "kind", "public_authorized", "processing_status", "size")
    list_filter = ("purpose", "kind", "public_authorized", "processing_status")
    search_fields = ("machine__title", "machine__owner__email", "sha256")
    readonly_fields = ("id", "machine", "revision", "private_link", "kind", "mime_type", "size", "sha256", "processing_status", "error", "created_at")
    exclude = ("original", "preview")

    @admin.display(description="Archivo privado")
    def private_link(self, obj):
        return format_html('<a href="/archivos/{}/" target="_blank" rel="noopener">Abrir archivo</a>', obj.pk)

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        if obj.purpose in {"plate", "document"}:
            obj.public_authorized = False
        super().save_model(request, obj, form, change)


@admin.register(Submission)
class SubmissionAdmin(HistoricalAdmin):
    list_display = ("machine", "status", "version", "created_at", "decided_by", "review_link")
    list_filter = ("status", "created_at")
    search_fields = ("machine__title", "machine__owner__email", "machine__id")
    action_form = ReasonActionForm
    actions = ("start_review", "request_changes", "approve", "reject", "cancel")

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("portal.review_submission")

    @admin.display(description="Revisión")
    def review_link(self, obj):
        return format_html('<a href="/operaciones/solicitudes/{}/">Abrir revisión</a>', obj.pk)

    def _review(self, request, queryset, decision):
        for obj in queryset:
            try:
                review_submission(obj, request.user, decision, request.POST.get("reason", ""))
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f"{obj.machine.folio}: {exc}", messages.ERROR)
            else:
                self.message_user(request, f"{obj.machine.folio}: revisión registrada.")

    @admin.action(description="Comenzar revisión")
    def start_review(self, request, queryset):
        self._review(request, queryset, "in_review")

    @admin.action(description="Solicitar cambios (indica motivo)")
    def request_changes(self, request, queryset):
        self._review(request, queryset, "changes_requested")

    @admin.action(description="Aprobar solicitud; no publica automáticamente")
    def approve(self, request, queryset):
        self._review(request, queryset, "approved")

    @admin.action(description="Rechazar solicitud (indica motivo)")
    def reject(self, request, queryset):
        self._review(request, queryset, "rejected")

    @admin.action(description="Cancelar solicitud (indica motivo)")
    def cancel(self, request, queryset):
        self._review(request, queryset, "cancelled")


@admin.register(MachineVersion)
class VersionAdmin(HistoricalAdmin):
    list_display = ("machine", "number", "created_by", "created_at")
    search_fields = ("machine__title", "machine__owner__email")


@admin.register(Publication)
class PublicationAdmin(AuditedAdmin):
    list_display = ("machine", "destination", "status", "enabled", "updated_at")
    list_filter = ("destination", "status", "enabled")
    search_fields = ("machine__title", "external_id")
    readonly_fields = ("machine", "version", "destination", "status", "enabled", "token", "last_error", "updated_at")
    actions = ("export_main", "disable")

    def has_add_permission(self, request):
        return False

    @admin.action(description="Deshabilitar publicaciones seleccionadas")
    def disable(self, request, queryset):
        for obj in queryset:
            set_publication(obj.machine, request.user, False, obj.destination)

    @admin.action(description="Exportar fichas aprobadas para el portal principal (JSON)")
    def export_main(self, request, queryset):
        if not request.user.has_perm("portal.publish_machine"):
            raise PermissionDenied
        records = []
        for obj in queryset.select_related("machine__owner", "version"):
            if not obj.version_id or obj.machine.owner.advertiser_status != "approved" or obj.version_id != obj.machine.approved_version_id:
                continue
            snapshot_data = obj.version.data
            data = dict(snapshot_data.get("data", {}))
            for key in ("serial", "plate_transcription", "notes"):
                data.pop(key, None)
            if not snapshot_data.get("contact_authorized"):
                data.pop("contact_public", None)
            records.append({"folio": obj.machine.folio, "version": obj.version.number,
                "title": snapshot_data.get("title"), "category": snapshot_data.get("category_name"),
                "data": data, "asset_ids": snapshot_data.get("public_asset_ids", []),
                "availability": obj.machine.availability})
            if obj.destination == "main":
                obj.status = "exported"
                obj.save(update_fields=["status", "updated_at"])
            audit(request.user, "publication.exported", obj, {"version": obj.version.number})
        response = HttpResponse(json.dumps({"schema": "imc-export-v1", "records": records}, ensure_ascii=False, indent=2), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="imc-publicaciones.json"'
        return response


@admin.register(Message)
class MessageAdmin(AuditedAdmin):
    list_display = ("machine", "sender", "internal", "created_at")
    list_filter = ("internal", "created_at")
    search_fields = ("body", "machine__title", "sender__email")
    readonly_fields = ("sender", "created_at")

    def get_readonly_fields(self, request, obj=None):
        return ("sender", "created_at", "machine", "body", "internal") if obj else self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.sender = request.user
        super().save_model(request, obj, form, change)


@admin.register(Consent)
class ConsentAdmin(HistoricalAdmin):
    list_display = ("user", "machine", "kind", "granted", "version", "created_at")
    list_filter = ("kind", "granted", "version")
    search_fields = ("user__email",)


@admin.register(AnalysisJob)
class AnalysisAdmin(HistoricalAdmin):
    list_display = ("id", "machine", "status", "model", "attempts", "input_tokens", "output_tokens", "created_at")
    list_filter = ("status", "mode", "model", "created_at")
    search_fields = ("machine__title", "requested_by__email", "id")


@admin.register(AuditEvent)
class AuditAdmin(HistoricalAdmin):
    list_display = ("created_at", "actor", "action", "object_type", "object_id")
    list_filter = ("action", "object_type", "created_at")
    search_fields = ("actor__email", "object_id", "action")


@admin.register(Lead)
class LeadAdmin(AuditedAdmin):
    list_display = ("name", "email", "status", "priority", "assigned_to", "next_action_at", "is_test")
    list_filter = ("status", "priority", "assigned_to", "is_test")
    search_fields = ("name", "email", "phone", "message")
    readonly_fields = ("created_at",)


@admin.register(Notification)
class NotificationAdmin(HistoricalAdmin):
    list_display = ("user", "subject", "channel", "status", "attempts", "created_at", "sent_at")
    list_filter = ("channel", "status", "kind")
    search_fields = ("user__email", "subject")


@admin.register(SiteContent)
class ContentAdmin(AuditedAdmin):
    list_display = ("key", "title", "active")
    list_filter = ("active",)
    search_fields = ("key", "title", "body")


@admin.register(PlatformSettings)
class SettingsAdmin(AuditedAdmin):
    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists() and super().has_add_permission(request)


@admin.register(AnalyticsEvent)
class AnalyticsAdmin(HistoricalAdmin):
    list_display = ("event", "user", "source", "campaign", "device", "is_test", "created_at")
    list_filter = ("event", "source", "device", "is_test", "created_at")
    search_fields = ("campaign",)


@admin.register(AccountRequest)
class AccountRequestAdmin(AuditedAdmin):
    list_display = ("user", "kind", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("user__email", "detail")
    readonly_fields = ("user", "kind", "detail", "created_at")

    def has_add_permission(self, request):
        return False

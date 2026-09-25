from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from urllib.parse import urlencode
import json
import csv

from .models import (AccountRequest, AnalyticsEvent, AnalysisJob, Asset, AuditEvent, Brand, EquipmentModel, Unit, Category,
                     Consent, Lead, Machine, MachineVersion, Message, Notification,
                     PlatformSettings, Publication, SiteContent, Submission, User, NotificationTemplate, IntegrationDelivery)
from .services import audit, review_submission, save_draft, set_advertiser_status, set_availability, set_publication, reassign_machine, find_possible_duplicates, send_machine_reminder, _validate_payload
from . import knowledge_admin  # Register the reviewed technical-reference library.


admin.site.site_header = "IMC México · Administración"
admin.site.site_title = "IMC México"
admin.site.index_title = "Operación de la plataforma"


def central_admin_login(request,extra_context=None):
    # Keep all password checks behind the same account/IP throttle and audit trail.
    return redirect("/administracion/")


admin.site.login=central_admin_login


from .models import AccountAccess


class ReasonActionForm(ActionForm):
    reason = forms.CharField(label="Motivo de la decisión", required=False, max_length=2000)


class TransferActionForm(ReasonActionForm):
    new_owner_email=forms.EmailField(label="Correo de la nueva cuenta (sólo reasignación)",required=False)


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


@admin.register(AccountAccess)
class AccountAccessAdmin(HistoricalAdmin):
    change_list_template = "admin/portal/accountaccess/change_list.html"
    list_display = ("user", "event", "connection_ip", "forwarded_ip", "device", "created_at")
    list_filter = ("event", "device", "created_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "connection_ip", "forwarded_ip")
    list_select_related = ("user",)
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        from django.utils import timezone
        return super().get_queryset(request).filter(expires_at__gt=timezone.now())


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
    list_display = ("email", "first_name", "phone", "machine_count_link", "advertiser_status", "last_login", "email_verified", "is_active", "is_staff", "is_test")
    list_filter = ("advertiser_status", "email_verified", "is_staff", "is_active", "is_test")
    search_fields = ("email", "first_name", "last_name", "phone", "company")

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(is_guest=True).annotate(machine_count=Count("machines"))

    def lookup_allowed(self, lookup, value, request=None):
        # The count link narrows the existing machinery administration to one
        # owner.  It is intentionally precise rather than exposing a broad
        # staff-facing search parameter.
        return lookup == "owner__id__exact" or super().lookup_allowed(lookup, value, request)

    @admin.display(description="Fichas", ordering="machine_count")
    def machine_count_link(self, obj):
        count = getattr(obj, "machine_count", 0)
        href = reverse("admin:portal_machine_changelist") + "?" + urlencode({"owner__id__exact": obj.pk})
        label = f"{count} {'ficha' if count == 1 else 'fichas'}"
        return format_html('<a href="{}">{}</a>', href, label)
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


@admin.register(Brand)
class BrandAdmin(AuditedAdmin):
    list_display=("name","active")
    list_filter=("active",)
    search_fields=("name",)


@admin.register(EquipmentModel)
class EquipmentModelAdmin(AuditedAdmin):
    list_display=("name","brand","category","active")
    list_filter=("active","brand","category")
    search_fields=("name","brand__name")
    autocomplete_fields=("brand","category")


@admin.register(Unit)
class UnitAdmin(AuditedAdmin):
    list_display=("name","symbol","dimension","active")
    list_filter=("active","dimension")
    search_fields=("name","symbol")


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
    expected_revision = forms.IntegerField(widget=forms.HiddenInput)

    class Meta:
        model = Machine
        fields = "__all__"

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["expected_revision"].initial=self.instance.revision

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and not self.instance.editable:
            editable_fields = {"title", "category", "data", "provenance"}
            if editable_fields.intersection(self.changed_data):
                raise ValidationError("Solicita cambios antes de editar una maquinaria en revisión.")
        if self.instance.pk:
            current=Machine.all_objects.get(pk=self.instance.pk)
            if cleaned.get("expected_revision")!=current.revision:
                raise ValidationError("La maquinaria cambió desde que abriste esta página. Recarga para revisar la última versión.")
            _validate_payload(current,{"title":cleaned.get("title",current.title),"category":getattr(cleaned.get("category"),"pk",None),"data":cleaned.get("data",{}),"provenance":cleaned.get("provenance",{})})
        return cleaned


@admin.register(Machine)
class MachineAdmin(AuditedAdmin):
    form = MachineForm
    list_display = ("folio", "title", "owner", "category", "status", "availability", "revision", "deleted_at", "updated_at")
    list_filter = ("deleted_at", "status", "availability", "category", "owner__is_test")
    search_fields = ("id", "title", "owner__email", "data__brand", "data__model", "data__location")
    readonly_fields = ("id", "folio", "owner", "status", "availability", "revision", "approved_version", "deleted_at", "created_at", "updated_at", "possible_duplicates")
    list_select_related = ("owner", "category")
    inlines = (AssetInline,)
    action_form=TransferActionForm
    actions = ("mark_sold", "mark_withdrawn", "enable_share", "disable_share", "transfer_owner", "send_reminder")

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        queryset = Machine.all_objects.all()
        ordering = self.get_ordering(request)
        return queryset.order_by(*ordering) if ordering else queryset

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.deleted_at is None)

    def _active_queryset(self, request, queryset):
        if queryset.filter(deleted_at__isnull=False).exists():
            self.message_user(request, "Los borradores en la papelera se conservan sin cambios. Sólo su propietario puede restaurarlos.", messages.WARNING)
        return queryset.filter(deleted_at__isnull=True)

    def get_object(self,request,object_id,from_field=None):
        obj=super().get_object(request,object_id,from_field)
        if obj is not None:obj._imc_duplicate_actor=request.user
        return obj

    @admin.display(description="Posibles coincidencias · revisión manual, sin fusión automática")
    def possible_duplicates(self,obj):
        actor=getattr(obj,"_imc_duplicate_actor",None)
        if actor is None:return "Abre la ficha administrativa para consultar coincidencias."
        matches=find_possible_duplicates(obj,actor)
        if not matches:return "Sin coincidencias por serie, marca/modelo o archivos compartidos."
        return format_html_join(" · ",'<a href="/admin/portal/machine/{}/change/">{} · {}</a>',((item.pk,item.folio,item.title) for item in matches))

    @admin.action(description="Enviar recordatorio al anunciante (escribe el texto en Motivo)")
    def send_reminder(self,request,queryset):
        for machine in self._active_queryset(request, queryset):
            try:send_machine_reminder(machine,request.user,request.POST.get("reason",""))
            except (PermissionDenied,ValidationError) as exc:self.message_user(request,f"{machine.folio}: {exc}",messages.ERROR)
            else:self.message_user(request,f"{machine.folio}: recordatorio en cola.")

    @admin.action(description="Reasignar excepcionalmente (correo destino y motivo obligatorios)")
    def transfer_owner(self,request,queryset):
        if not request.user.has_perm("portal.reassign_machine"):
            raise PermissionDenied
        target=User.objects.filter(email__iexact=request.POST.get("new_owner_email","").strip(),is_guest=False).first()
        if not target:
            self.message_user(request,"Indica el correo de una cuenta de destino existente.",messages.ERROR)
            return
        for machine in self._active_queryset(request, queryset):
            try:
                reassign_machine(machine,request.user,target,request.POST.get("reason",""))
            except ValidationError as exc:
                self.message_user(request,f"{machine.folio}: {exc}",messages.ERROR)
            else:
                self.message_user(request,f"{machine.folio}: reasignada; requiere nueva autorización y revisión.")

    def save_model(self, request, obj, form, change):
        saved = save_draft(obj, request.user, {"title": obj.title, "category": obj.category_id,
                          "data": obj.data, "provenance": obj.provenance}, form.cleaned_data["expected_revision"])
        obj.revision = saved.revision
        obj.status = saved.status

    def _availability(self, request, queryset, value):
        for obj in self._active_queryset(request, queryset):
            set_availability(obj, request.user, value)
        self.message_user(request, "Disponibilidad actualizada.")

    @admin.action(description="Marcar como vendida")
    def mark_sold(self, request, queryset):
        self._availability(request, queryset, "sold")

    @admin.action(description="Retirar y deshabilitar fichas públicas")
    def mark_withdrawn(self, request, queryset):
        self._availability(request, queryset, "withdrawn")

    def _share(self, request, queryset, enabled):
        for obj in self._active_queryset(request, queryset):
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

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.machine.deleted_at is None)

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
        if queryset.filter(machine__deleted_at__isnull=False).exists():
            self.message_user(request, "Se omitieron las solicitudes de borradores en la papelera. Su historial se conserva sin modificar.", messages.WARNING)
        for obj in queryset.filter(machine__deleted_at__isnull=True):
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
    list_display = ("machine", "destination", "status", "integration_state", "enabled", "updated_at")
    list_filter = ("destination", "status", "integration_state", "enabled")
    search_fields = ("machine__title", "external_id")
    readonly_fields = ("machine", "version", "destination", "status", "enabled", "token", "last_error", "updated_at",
                       "external_id", "external_url", "external_reference", "integration_state", "acknowledged_at", "acknowledged_by", "current_delivery")
    actions = ("export_main", "confirm_main_publication", "disable")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request,obj) and request.user.has_perm("portal.publish_machine")

    @admin.action(description="Revisar acuse de integración en el panel IMC")
    def confirm_main_publication(self, request, queryset):
        if not request.user.has_perm("portal.publish_machine"):
            raise PermissionDenied
        records = queryset.filter(destination='main', machine__deleted_at__isnull=True)
        if records.count() == 1:
            return redirect('integration_detail', pk=records.get().machine_id)
        self.message_user(request, 'Selecciona una publicación principal para cotejar su acuse. No se modificó ningún estado.', messages.WARNING)

    @admin.action(description="Deshabilitar publicaciones seleccionadas")
    def disable(self, request, queryset):
        for obj in queryset.filter(machine__deleted_at__isnull=True):
            if obj.destination == 'main':
                self.message_user(request, f'{obj.machine.folio}: la baja en la web principal debe confirmarse en ese sistema. No se modificó su estado remoto.', messages.WARNING)
                continue
            set_publication(obj.machine, request.user, False, obj.destination)

    @admin.action(description="Exportar fichas aprobadas para el portal principal (JSON)")
    def export_main(self, request, queryset):
        if not request.user.has_perm("portal.publish_machine"):
            raise PermissionDenied
        records = []
        from .export_payload import build_export_payload
        from .integration import prepare_delivery, delivery_metadata
        for obj in queryset.filter(destination='main', machine__deleted_at__isnull=True).select_related("machine__owner", "version"):
            if not obj.version_id or obj.machine.owner.advertiser_status != "approved" or obj.version_id != obj.machine.approved_version_id:
                continue
            try:
                payload, _ = build_export_payload(obj.machine, obj.version)
                delivery = prepare_delivery(obj.machine, request.user, payload)
                from .integration import mark_delivery_exported
                mark_delivery_exported(delivery, request.user)
            except (ValidationError, OSError) as exc:
                self.message_user(request, f'{obj.machine.folio}: no se pudo preparar la entrega. Comprueba la versión y sus archivos.', messages.ERROR)
                continue
            records.append({**payload, 'asset_ids': [item['id'] for item in payload['assets']],
                            'integration': delivery_metadata(delivery)})
            audit(request.user, "publication.exported", obj, {"version": obj.version.number})
        response = HttpResponse(json.dumps({"schema": "imc-export-v1", "records": records}, ensure_ascii=False, indent=2), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="imc-publicaciones.json"'
        return response


@admin.register(IntegrationDelivery)
class IntegrationDeliveryAdmin(HistoricalAdmin):
    list_display = ('id', 'publication', 'version', 'state', 'created_at', 'acknowledged_at')
    list_filter = ('state',)
    search_fields = ('publication__machine__title', 'publication__external_id', 'payload_sha256')


class StaffMessageForm(forms.ModelForm):
    body = forms.CharField(label="Mensaje", max_length=5000, widget=forms.Textarea,
        help_text="Si es externo, el anunciante lo verá en Mensajes y recibirá un aviso en la plataforma y un correo en cola.")

    class Meta:
        model = Message
        fields = ("machine", "body", "internal")
        help_texts = {"internal": "Marca esta opción para una nota privada del equipo, sin avisar al anunciante."}

    def clean(self):
        data = super().clean()
        machine = data.get("machine")
        if machine and not data.get("internal") and not machine.owner.is_active:
            raise ValidationError("La cuenta del destinatario está inactiva.")
        return data


@admin.register(Message)
class MessageAdmin(AuditedAdmin):
    form = StaffMessageForm
    list_display = ("machine", "sender", "internal", "created_at")
    list_filter = ("internal", "created_at")
    search_fields = ("body", "machine__title", "sender__email")
    readonly_fields = ("sender", "created_at")

    def has_add_permission(self, request):
        return (super().has_add_permission(request) and
                (request.user.has_perm("portal.view_machine") or request.user.has_perm("portal.change_machine")))

    def get_readonly_fields(self, request, obj=None):
        return ("sender", "created_at", "machine", "body", "internal") if obj else self.readonly_fields

    def save_model(self, request, obj, form, change):
        if change:
            return
        from .communications import save_staff_message
        save_staff_message(obj, request.user)
        self.message_user(request, "Nota interna guardada sin notificar al anunciante." if obj.internal else
                          "Mensaje guardado, aviso disponible en la plataforma y correo en cola.", messages.SUCCESS)


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

    def get_queryset(self,request):
        return super().get_queryset(request).exclude(kind__in=["activation","admin_activation","verify","recovery"])


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(AuditedAdmin):
    list_display=("key","subject","active")
    list_filter=("active",)
    search_fields=("key","subject","body")


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
    list_display = ("event", "actor_type", "page", "source", "campaign", "device", "is_test", "created_at")
    list_filter = ("event", "actor_type", "page", "source", "device", "is_test", "created_at")
    search_fields = ("campaign",)
    actions=("export_events",)

    def has_export_permission(self,request):
        return request.user.has_perm("portal.export_analytics")

    @admin.action(description="Exportar eventos seleccionados (CSV)",permissions=["export"])
    def export_events(self,request,queryset):
        if not self.has_export_permission(request):raise PermissionDenied
        response=HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"]='attachment; filename="imc-eventos.csv"'
        response.write("\ufeff")
        writer=csv.writer(response)
        writer.writerow(["fecha","evento","tipo_actor","pagina","usuario_id_legado","maquinaria_legado","origen","campana","dispositivo","prueba"])
        def safe(value):
            text=str(value or "")
            return "'"+text if text.startswith(("=","+","-","@","\t","\r","\n")) else text
        count=0
        for item in queryset.select_related("user","machine").iterator(chunk_size=500):
            actor_type="prueba" if item.is_test else "equipo" if item.actor_type=="staff" or item.user_id and item.user.is_staff else "registrado" if item.actor_type=="registered" or item.user_id else "anonimo"
            writer.writerow([item.created_at.isoformat(),safe(item.event),actor_type,safe(item.page),item.user_id or "",item.machine.folio if item.machine_id else "",safe(item.source),safe(item.campaign),safe(item.device),int(item.is_test)])
            count+=1
        audit(request.user,"analytics.exported",request.user,{"records":count})
        return response


@admin.register(AccountRequest)
class AccountRequestAdmin(AuditedAdmin):
    list_display = ("user", "kind", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("user__email", "detail")
    readonly_fields = ("user", "kind", "detail", "created_at")

    def has_add_permission(self, request):
        return False

"""Admin registration kept separate so the existing admin root can import it."""
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, MarketReference, TechnicalReference


def _change_references(model_admin, request, queryset, *, approve):
    """Apply a whole selection or none; every reference retains an audit entry."""
    count = 0
    prefix = "technical_reference" if queryset.model is TechnicalReference else "market_reference"
    try:
        with transaction.atomic():
            for reference in queryset.select_for_update().order_by("pk"):
                reference.active = approve
                if approve:
                    reference.review = reference.Review.APPROVED
                    reference.reviewed_by = request.user
                    reference.reviewed_at = timezone.now()
                    reference.full_clean()
                    reference.save()
                else:
                    # Invalid legacy data must still be possible to deactivate.
                    reference.save(update_fields=["active", "updated_at"])
                AuditEvent.objects.create(actor=request.user,
                    action=f"{prefix}.{'approved' if approve else 'deactivated'}",
                    object_type=queryset.model.__name__, object_id=str(reference.pk), metadata={})
                count += 1
    except ValidationError as exc:
        model_admin.message_user(request, "No se aplicó ningún cambio. " + " ".join(exc.messages), messages.ERROR)
        return
    action = "aprobadas y activadas" if approve else "desactivadas; el historial se conserva"
    model_admin.message_user(request, f"{count} referencias {action}.", messages.SUCCESS)


@admin.register(TechnicalReference)
class TechnicalReferenceAdmin(admin.ModelAdmin):
    list_display = ("category", "brand", "model", "variant", "market", "review", "active", "retrieved_at", "updated_at")
    list_filter = ("category", "review", "active", "market")
    search_fields = ("brand", "model", "variant", "generation", "source", "source_title")
    readonly_fields = ("created_at", "updated_at", "reviewed_by", "reviewed_at")
    actions = ("approve_references", "deactivate_references")
    list_select_related = ("category", "equipment_model")

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if obj.review == TechnicalReference.Review.APPROVED and (not change or "review" in form.changed_data):
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        if obj.review != TechnicalReference.Review.APPROVED:
            obj.active = False
        obj.full_clean()
        super().save_model(request, obj, form, change)
        AuditEvent.objects.create(actor=request.user, action="technical_reference.saved",
                                  object_type="TechnicalReference", object_id=str(obj.pk),
                                  metadata={"review": obj.review, "active": obj.active})

    @admin.action(description="Aprobar y activar referencias seleccionadas", permissions=["change"])
    def approve_references(self, request, queryset):
        _change_references(self, request, queryset, approve=True)

    @admin.action(description="Desactivar referencias seleccionadas", permissions=["change"])
    def deactivate_references(self, request, queryset):
        _change_references(self, request, queryset, approve=False)


@admin.register(MarketReference)
class MarketReferenceAdmin(admin.ModelAdmin):
    list_display = ("equipment_model", "price", "currency", "market", "price_type", "condition", "review", "active", "retrieved_at")
    list_filter = ("review", "active", "currency", "market", "price_type", "condition")
    search_fields = ("equipment_model__brand__name", "equipment_model__name", "source", "source_title", "unit_key")
    readonly_fields = ("created_at", "updated_at", "reviewed_by", "reviewed_at")
    actions = ("approve_references", "deactivate_references")
    list_select_related = ("equipment_model__brand",)

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if obj.review == MarketReference.Review.APPROVED and (not change or "review" in form.changed_data):
            obj.reviewed_by, obj.reviewed_at = request.user, timezone.now()
        if obj.review != MarketReference.Review.APPROVED: obj.active = False
        obj.full_clean(); super().save_model(request, obj, form, change)
        AuditEvent.objects.create(actor=request.user, action="market_reference.saved", object_type="MarketReference", object_id=str(obj.pk), metadata={"review":obj.review,"active":obj.active})

    @admin.action(description="Aprobar y activar referencias seleccionadas", permissions=["change"])
    def approve_references(self, request, queryset):
        _change_references(self, request, queryset, approve=True)

    @admin.action(description="Desactivar referencias seleccionadas", permissions=["change"])
    def deactivate_references(self, request, queryset):
        _change_references(self, request, queryset, approve=False)

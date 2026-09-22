"""Admin registration kept separate so the existing admin root can import it."""
from django.contrib import admin, messages
from django.utils import timezone

from .models import AuditEvent, MarketReference, TechnicalReference


@admin.register(TechnicalReference)
class TechnicalReferenceAdmin(admin.ModelAdmin):
    list_display = ("category", "brand", "model", "variant", "market", "review", "active", "retrieved_at", "updated_at")
    list_filter = ("category", "review", "active", "market")
    search_fields = ("brand", "model", "variant", "generation", "source", "source_title")
    readonly_fields = ("created_at", "updated_at", "reviewed_by", "reviewed_at")
    actions = ("approve_references", "deactivate_references")

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

    @admin.action(description="Aprobar y activar referencias seleccionadas")
    def approve_references(self, request, queryset):
        for reference in queryset:
            reference.review = TechnicalReference.Review.APPROVED
            reference.active = True
            reference.reviewed_by = request.user
            reference.reviewed_at = timezone.now()
            reference.full_clean()
            reference.save()
            AuditEvent.objects.create(actor=request.user, action="technical_reference.approved",
                                      object_type="TechnicalReference", object_id=str(reference.pk), metadata={})
        self.message_user(request, "Referencias aprobadas y activadas.", messages.SUCCESS)

    @admin.action(description="Desactivar referencias seleccionadas")
    def deactivate_references(self, request, queryset):
        for reference in queryset:
            reference.active = False
            reference.save(update_fields=["active", "updated_at"])
            AuditEvent.objects.create(actor=request.user, action="technical_reference.deactivated",
                                      object_type="TechnicalReference", object_id=str(reference.pk), metadata={})
        self.message_user(request, "Referencias desactivadas; el historial se conserva.", messages.SUCCESS)


@admin.register(MarketReference)
class MarketReferenceAdmin(admin.ModelAdmin):
    list_display = ("equipment_model", "price", "currency", "market", "price_type", "condition", "review", "active", "retrieved_at")
    list_filter = ("review", "active", "currency", "market", "price_type", "condition")
    search_fields = ("equipment_model__brand__name", "equipment_model__name", "source", "source_title", "unit_key")
    readonly_fields = ("created_at", "updated_at", "reviewed_by", "reviewed_at")
    actions = ("approve_references", "deactivate_references")

    def save_model(self, request, obj, form, change):
        if obj.review == MarketReference.Review.APPROVED and (not change or "review" in form.changed_data):
            obj.reviewed_by, obj.reviewed_at = request.user, timezone.now()
        if obj.review != MarketReference.Review.APPROVED: obj.active = False
        obj.full_clean(); super().save_model(request, obj, form, change)
        AuditEvent.objects.create(actor=request.user, action="market_reference.saved", object_type="MarketReference", object_id=str(obj.pk), metadata={"review":obj.review,"active":obj.active})

    @admin.action(description="Aprobar y activar referencias seleccionadas")
    def approve_references(self, request, queryset):
        for reference in queryset:
            reference.review, reference.active = MarketReference.Review.APPROVED, True
            reference.reviewed_by, reference.reviewed_at = request.user, timezone.now()
            reference.full_clean(); reference.save()
        self.message_user(request, "Referencias de mercado aprobadas y activadas.", messages.SUCCESS)

    @admin.action(description="Desactivar referencias seleccionadas")
    def deactivate_references(self, request, queryset):
        queryset.update(active=False)
        self.message_user(request, "Referencias de mercado desactivadas; el historial se conserva.", messages.SUCCESS)

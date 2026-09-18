"""Admin registration kept separate so the existing admin root can import it."""
from django.contrib import admin, messages
from django.utils import timezone

from .models import AuditEvent, TechnicalReference


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

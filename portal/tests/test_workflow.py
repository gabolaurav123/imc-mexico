from copy import deepcopy
from io import StringIO
from tempfile import TemporaryDirectory

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings

from portal.admin import UserAdmin
from portal.models import (AnalysisJob, Asset, AuditEvent, Category, Consent, Machine, MachineVersion,
                           Notification, PlatformSettings, Publication, Submission, User)
from portal.services import (apply_analysis_suggestions, duplicate_machine, review_submission,
                             save_draft, set_advertiser_status, set_availability, set_publication,
                             snapshot, submit_machine, reassign_machine, record_local_duplicate_review)


class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="owner@example.com", password="A-long-example-password1")
        cls.other = User.objects.create_user(email="other@example.com", password="Another-long-password2")
        cls.admin = User.objects.create_superuser(email="admin@example.com", password="Third-long-password3")
        cls.category = Category.objects.create(name="Excavadoras", slug="excavadoras", fields=["power"])

    def setUp(self):
        self.machine = Machine.objects.create(owner=self.owner, title="Excavadora declarada", category=self.category,
                                              data={"location": "Querétaro", "year": None})
        self.photo = Asset.objects.create(machine=self.machine, kind="image", purpose="general", processing_status="ready",
                                         original="private/test.jpg", mime_type="image/jpeg", sha256="a" * 64, size=100)

    def approve(self):
        set_advertiser_status(self.owner, self.admin, "approved", "Datos revisados por operador")
        submission = submit_machine(self.machine, self.owner, True)
        self.photo.public_authorized = True
        self.photo.save()
        record_local_duplicate_review(self.machine, submission, self.admin, "no_match",
                                      "Se revisaron serie, marca, modelo y fotografía principal.")
        review_submission(submission, self.admin, "approved")
        self.machine.refresh_from_db()
        submission.refresh_from_db()
        return submission

    def test_email_normalization_and_private_defaults(self):
        user = User.objects.create_user(email="UPPER@EXAMPLE.COM", password="secret")
        self.assertEqual(user.email, "upper@example.com")
        self.assertEqual(user.username, user.email)
        self.assertEqual(user.advertiser_status, "pending")
        self.assertFalse(self.photo.public_authorized)
        self.assertFalse(Publication.objects.create(machine=self.machine).enabled)

    def test_missing_unknown_values_are_allowed(self):
        machine = save_draft(self.machine, self.owner, {"data": {"year": "", "serial": None, "hours": "", "no_plate": True}}, 1)
        self.assertEqual(machine.revision, 2)
        self.assertIsNone(machine.data["year"])
        submission = submit_machine(machine, self.owner, True)
        self.assertEqual(submission.status, "submitted")
        self.assertFalse(Publication.objects.filter(machine=machine, enabled=True).exists())

    def test_ownership_checked_at_service_boundary(self):
        for operation in (
            lambda: save_draft(self.machine, self.other, {"title": "Ajena"}, 1),
            lambda: submit_machine(self.machine, self.other, True),
            lambda: snapshot(self.machine, self.other),
            lambda: set_availability(self.machine, self.other, "sold"),
            lambda: duplicate_machine(self.machine, self.other),
        ):
            with self.assertRaises(PermissionDenied):
                operation()

    def test_revision_conflict_preserves_saved_data(self):
        save_draft(self.machine, self.owner, {"title": "Primera versión"}, 1)
        with self.assertRaises(ValidationError):
            save_draft(self.machine, self.owner, {"title": "Sobrescrita"}, 1)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.title, "Primera versión")

    def test_no_mass_assignment_or_unknown_fields(self):
        for payload in ({"status": "approved"}, {"owner": self.other.pk}, {"data": {"secret": "x"}}, {"data": {"price": "NaN"}}, {"data": {"year": "1800"}}):
            with self.assertRaises(ValidationError):
                save_draft(self.machine, self.owner, payload, 1)

    def test_browser_cannot_forge_source(self):
        changed = save_draft(self.machine, self.owner, {"data": {"brand": "Declarada"}, "provenance": {"brand": {"source": "plate", "review": "clear", "asset_id": str(self.photo.pk)}}}, 1)
        self.assertEqual(changed.provenance["brand"]["source"], "user")
        self.assertEqual(changed.provenance["brand"]["review"], "confirmed")
        self.assertEqual(changed.provenance["brand"]["confidence"], "owner_declared")
        self.assertTrue(changed.provenance["brand"]["source_date"])
        with self.assertRaises(ValidationError):
            save_draft(changed, self.owner, {"provenance": {"brand": {"source": "manufacturer"}}}, 2)

    def test_category_and_title_provenance_work_with_browser_payload(self):
        category=Category.objects.create(name="Otra",slug="otra")
        changed=save_draft(self.machine,self.owner,{"category":category.pk,"title":"Nuevo título","provenance":{"category":{"source":"user","review":"confirmed"},"title":{"source":"user","review":"confirmed"}}},1)
        self.assertEqual(changed.category_id,category.pk)
        self.assertEqual(changed.provenance["category"]["source"],"user")
        self.assertEqual(changed.provenance["title"]["source"],"user")

    def test_retyping_identical_ai_value_preserves_original_source(self):
        self.machine.data["brand"]="Marca visible"
        self.machine.provenance["brand"]={"source":"image","review":"needs_review","asset_id":str(self.photo.pk)}
        self.machine.save()
        changed=save_draft(self.machine,self.owner,{"data":{"brand":"Marca visible"},"provenance":{"brand":{"source":"user","review":"confirmed"}}},1)
        self.assertEqual(changed.provenance["brand"]["source"],"image")
        self.assertEqual(changed.provenance["brand"]["review"],"confirmed")

    def test_email_change_clears_old_verification(self):
        self.owner.email_verified=True;self.owner.save()
        self.owner.email="changed@example.com";self.owner.save(update_fields=["email"])
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.email_verified)
        self.assertEqual(self.owner.username,"changed@example.com")

    def test_useful_image_and_consent_required(self):
        with self.assertRaises(ValidationError):
            submit_machine(self.machine, self.owner, False)
        self.photo.purpose = "plate"
        self.photo.save()
        with self.assertRaises(ValidationError):
            submit_machine(self.machine, self.owner, True)
        self.assertEqual(Consent.objects.count(), 0)

    def test_staff_cannot_grant_advertiser_consent_on_behalf_of_owner(self):
        with self.assertRaises(PermissionDenied):submit_machine(self.machine,self.admin,True,True)
        self.assertFalse(Consent.objects.filter(machine=self.machine).exists())

    def test_edit_and_duplicate_submission_blocked_in_review(self):
        submit_machine(self.machine, self.owner, True)
        with self.assertRaises(ValidationError):
            submit_machine(self.machine, self.owner, True)
        with self.assertRaises(ValidationError):
            save_draft(self.machine, self.owner, {"title": "Cambio"}, 1)
        self.assertEqual(Submission.objects.count(), 1)

    def test_snapshot_is_immutable_even_queryset_update(self):
        version = snapshot(self.machine, self.owner)
        self.machine.data["location"] = "Cambio posterior"
        self.machine.save()
        version.refresh_from_db()
        self.assertEqual(version.data["data"]["location"], "Querétaro")
        for operation in (lambda: version.save(), lambda: version.delete(), lambda: MachineVersion.objects.filter(pk=version.pk).update(data={}), lambda: MachineVersion.objects.filter(pk=version.pk).delete()):
            with self.assertRaises(ValidationError):
                operation()

    def test_approval_requires_staff_permission_and_advertiser_approval(self):
        submission = submit_machine(self.machine, self.owner, True)
        with self.assertRaises(PermissionDenied):
            review_submission(submission, self.owner, "approved")
        with self.assertRaises(ValidationError):
            review_submission(submission, self.admin, "approved")
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.status, "submitted")

    def test_approval_requires_a_human_local_duplicate_decision_for_this_submission(self):
        set_advertiser_status(self.owner, self.admin, "approved", "Datos revisados por operador")
        submission = submit_machine(self.machine, self.owner, True)
        with self.assertRaises(ValidationError):
            review_submission(submission, self.admin, "approved")
        event = record_local_duplicate_review(self.machine, submission, self.admin, "legitimate",
                                              "La coincidencia comparte modelo, pero no serie ni archivos.")
        self.assertEqual(event.actor_id, self.admin.pk)
        review_submission(submission, self.admin, "approved")

    def test_approval_creates_separate_frozen_version_and_no_auto_publication(self):
        submission = self.approve()
        self.assertNotEqual(submission.version_id, self.machine.approved_version_id)
        self.assertEqual(submission.version.data["public_asset_ids"], [])
        self.assertEqual(self.machine.approved_version.data["public_asset_ids"], [str(self.photo.pk)])
        self.assertFalse(Publication.objects.filter(enabled=True).exists())
        publication = set_publication(self.machine, self.admin, True)
        self.assertTrue(publication.enabled)
        self.assertEqual(publication.version_id, self.machine.approved_version_id)

    def test_plates_never_enter_public_allowlist(self):
        Asset.objects.create(machine=self.machine, kind="image", purpose="plate", processing_status="ready",
                             original="private/plate.jpg", mime_type="image/jpeg", sha256="b" * 64,
                             public_authorized=True)
        self.approve()
        self.assertEqual(self.machine.approved_version.data["public_asset_ids"], [str(self.photo.pk)])

    def test_changes_require_reason_and_allow_resubmission(self):
        first = submit_machine(self.machine, self.owner, True)
        with self.assertRaises(ValidationError):
            review_submission(first, self.admin, "changes_requested")
        review_submission(first, self.admin, "changes_requested", "Indica el municipio.")
        self.machine.refresh_from_db()
        changed = save_draft(self.machine, self.owner, {"data": {"location": "Querétaro, municipio de Querétaro"}}, self.machine.revision)
        second = submit_machine(changed, self.owner, True)
        with self.assertRaises(ValidationError):
            review_submission(first, self.admin, "approved")
        self.assertNotEqual(first.version_id, second.version_id)
        self.assertEqual(self.machine.messages.get().body, "Indica el municipio.")

    def test_public_version_survives_new_draft_and_updates_availability(self):
        self.approve()
        publication = set_publication(self.machine, self.admin, True)
        changed = save_draft(self.machine, self.owner, {"title": "Borrador nuevo"}, self.machine.revision)
        self.assertEqual(changed.status, "draft")
        publication.refresh_from_db()
        self.assertEqual(publication.version.data["title"], "Excavadora declarada")
        self.assertTrue(publication.enabled)
        set_availability(changed, self.owner, "withdrawn")
        publication.refresh_from_db()
        self.assertFalse(publication.enabled)

    def test_suspension_disables_existing_publications(self):
        self.approve()
        publication = set_publication(self.machine, self.admin, True)
        set_advertiser_status(self.owner, self.admin, "suspended", "Solicitud de revisión de identidad.")
        publication.refresh_from_db()
        self.assertFalse(publication.enabled)
        with self.assertRaises(ValidationError):
            set_publication(self.machine, self.admin, True)

    def test_admin_cannot_approve_own_advertiser_status(self):
        with self.assertRaises(PermissionDenied):
            set_advertiser_status(self.admin, self.admin, "approved", "Autorización propia")

    def test_contact_snapshot_requires_two_explicit_permissions(self):
        self.machine.data["contact_public"] = True
        self.machine.save()
        version = snapshot(self.machine, self.owner)
        self.assertEqual(version.data["public_contact"], {})
        Consent.objects.create(user=self.owner, machine=self.machine, kind="contact", granted=True)
        version = snapshot(self.machine, self.owner)
        self.assertEqual(version.data["public_contact"]["email"], self.owner.email)
        self.owner.phone = "+520000000001"
        self.owner.save()
        self.assertNotEqual(version.data["public_contact"]["phone"], self.owner.phone)

    def test_contact_text_does_not_expand_to_full_profile(self):
        self.machine.data["contact_public"]="Sólo llamar al +52 55 1234 5678"
        self.machine.save()
        Consent.objects.create(user=self.owner,machine=self.machine,kind="contact",granted=True)
        version=snapshot(self.machine,self.owner)
        self.assertEqual(version.data["public_contact"],{"text":"Sólo llamar al +52 55 1234 5678"})
        self.assertNotIn(self.owner.email,str(version.data["public_contact"]))

    def test_exceptional_reassignment_revokes_approval_and_requires_new_consent(self):
        self.approve()
        publication=set_publication(self.machine,self.admin,True)
        Consent.objects.create(user=self.owner,machine=self.machine,kind="contact",granted=True)
        machine=reassign_machine(self.machine,self.admin,self.other,"Transferencia revisada y autorizada")
        self.assertEqual(machine.owner_id,self.other.pk)
        self.assertEqual(machine.status,"draft")
        self.assertIsNone(machine.approved_version_id)
        self.assertEqual(machine.data["contact_public"],"")
        publication.refresh_from_db()
        self.assertFalse(publication.enabled)
        self.photo.refresh_from_db()
        self.assertFalse(self.photo.public_authorized)
        self.assertFalse(snapshot(machine,self.other).data["contact_authorized"])
        with self.assertRaises(PermissionDenied):
            set_availability(machine,self.owner,"sold")
        with self.assertRaises(PermissionDenied):
            reassign_machine(machine,self.other,self.owner,"No autorizado")

    def test_ai_suggestions_use_saved_result_and_detect_stale_revision(self):
        job = AnalysisJob.objects.create(machine=self.machine, revision=1, requested_by=self.owner,
            fingerprint="c" * 64, status="completed", result={"data": {"brand": "Visible", "title": "Título propuesto"},
            "provenance": {"brand": {"source": "image", "review": "clear", "asset_id": str(self.photo.pk)}}})
        result = apply_analysis_suggestions(self.machine, self.owner, job, ["brand", "title"], 1)
        self.assertEqual(result.data["brand"], "Visible")
        self.assertEqual(result.title, "Título propuesto")
        self.assertEqual(result.provenance["brand"]["source"], "image")
        self.assertEqual(result.provenance["brand"]["review"], "confirmed")
        self.assertEqual(result.provenance["brand"]["analysis_id"], str(job.pk))
        with self.assertRaises(ValidationError):
            apply_analysis_suggestions(result, self.owner, job, ["brand"], 2)

    def test_audit_and_consent_cannot_be_rewritten(self):
        event = AuditEvent.objects.create(actor=self.owner, action="test", object_type="machine", object_id=str(self.machine.pk))
        with self.assertRaises(ValidationError):
            AuditEvent.objects.filter(pk=event.pk).update(action="changed")
        self.assertEqual(event.action, "test")

    def test_admin_roles_readonly_for_self(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        model_admin = UserAdmin(User, AdminSite())
        for field in ("is_staff", "is_superuser", "groups", "user_permissions"):
            self.assertIn(field, model_admin.get_readonly_fields(request, self.admin))

    def test_seed_idempotent_preserves_customization_and_has_no_inventory(self):
        count = Machine.objects.count()
        call_command("seed", stdout=StringIO())
        category = Category.objects.get(slug="excavadoras")
        category.name = "Nombre validado"
        category.save()
        call_command("seed", stdout=StringIO())
        self.assertEqual(Category.objects.get(slug="excavadoras").name, "Nombre validado")
        self.assertEqual(Machine.objects.count(), count)
        self.assertFalse(PlatformSettings.load().ai_enabled)
        self.assertFalse(PlatformSettings.load().legal_validated)
        configuration=PlatformSettings.load()
        self.assertTrue(configuration.registration_open)
        configuration.registration_open=False
        configuration.save(update_fields=["registration_open"])
        call_command("seed", stdout=StringIO())
        configuration.refresh_from_db()
        self.assertFalse(configuration.registration_open)
        review = Group.objects.get(name="Revisión IMC")
        self.assertTrue(review.permissions.filter(codename="review_submission").exists())
        self.assertFalse(review.permissions.filter(codename="change_group").exists())

    @override_settings(PUBLIC_URL="https://test.example.com", DEBUG=False)
    def test_admin_invitation_idempotent_unusable_password_and_no_auto_elevation(self):
        call_command("invite_admin", "invited@example.com", stdout=StringIO())
        call_command("invite_admin", "invited@example.com", stdout=StringIO())
        user = User.objects.get(email="invited@example.com")
        self.assertTrue(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(Notification.objects.filter(user=user, kind="admin_activation").count(), 1)
        self.assertIn("https://test.example.com/activar/", Notification.objects.get(user=user).body)

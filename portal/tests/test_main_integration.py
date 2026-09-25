from django.core.exceptions import ValidationError
from django.test import TestCase

from portal.integration import (ack_delivery, delivery_metadata, mark_delivery_exported,
                                prepare_delivery, record_manual_review)
from portal.models import IntegrationDelivery, Machine, MachineVersion, Publication, User


class MainIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="delivery-owner@example.com", password="Owner-password-long123",
                                             advertiser_status="approved")
        cls.publisher = User.objects.create_superuser(email="delivery-publisher@example.com", password="Publisher-password-long123")

    def setUp(self):
        self.machine = Machine.objects.create(owner=self.owner, title="Excavadora", data={"brand": "CAT", "model": "320D"})
        self.version = MachineVersion.objects.create(machine=self.machine, number=1, data={"title": "Excavadora", "data": {}}, created_by=self.publisher)
        self.machine.approved_version = self.version
        self.machine.status = "approved"
        self.machine.save(update_fields=["approved_version", "status", "updated_at"])
        self.payload = {"schema": "public-machine-v1", "machine_id": str(self.machine.pk), "version": 1, "availability": "available",
                        "listing": {"title": "Excavadora", "description": "Texto original aprobado"},
                        "catalog": {"model_id": "cat-320d"}}

    def receipt(self, delivery, **changes):
        value = {
            **delivery_metadata(delivery),
            "remote_id": "000042",
            "external_reference": "IMC-42",
            "remote_url": "https://imcmexico.com.mx/maquinaria/42/",
            "status": "published",
        }
        value.update(changes)
        return value

    def review_duplicates(self, delivery):
        return record_manual_review(delivery, self.publisher,
            imc_advertiser="Cuenta IMC de pruebas", duplicate_result="no_match",
            evidence="El operador revisó manualmente el catálogo autorizado de la cuenta IMC.")

    def test_prepare_is_idempotent_for_the_same_immutable_payload(self):
        first = prepare_delivery(self.machine, self.publisher, self.payload)
        second = prepare_delivery(self.machine, self.publisher, dict(self.payload))
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(IntegrationDelivery.objects.count(), 1)
        self.assertEqual(first.source_machine_id, self.machine.pk)
        self.assertEqual(first.version_id, self.version.pk)
        self.assertEqual(first.state, "prepared")

    def test_main_handoff_requires_a_complete_manual_duplicate_review_before_export_or_ack(self):
        delivery = prepare_delivery(self.machine, self.publisher, self.payload)
        with self.assertRaises(ValidationError):
            mark_delivery_exported(delivery, self.publisher)
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery), "Evidencia independiente suficiente.")
        record_manual_review(delivery, self.publisher, imc_advertiser="Cuenta IMC de pruebas",
                             duplicate_result="not_checked", evidence="La revisión aún no se ha completado en el catálogo.")
        with self.assertRaises(ValidationError):
            mark_delivery_exported(delivery, self.publisher)
        self.review_duplicates(delivery)
        self.assertEqual(mark_delivery_exported(delivery, self.publisher).status, "exported")
        record_manual_review(delivery, self.publisher, imc_advertiser="Cuenta IMC de pruebas",
                             duplicate_result="not_checked", evidence="La revisión quedó pendiente tras un cambio manual posterior.")
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery), "Evidencia independiente suficiente.")

    def test_acknowledgement_binds_all_correlations_and_is_idempotent(self):
        delivery = prepare_delivery(self.machine, self.publisher, self.payload)
        self.review_duplicates(delivery)
        receipt = self.receipt(delivery)
        acknowledged = ack_delivery(delivery, self.publisher, receipt, "Operador verificó el comprobante remoto en el panel principal.")
        self.assertEqual(acknowledged.state, "acknowledged")
        publication = Publication.objects.get(machine=self.machine, destination="main")
        self.assertEqual(publication.external_id, "000042")
        self.assertEqual(publication.external_reference, "IMC-42")
        self.assertEqual(publication.status, "published")
        self.assertEqual(publication.integration_state, "acknowledged")
        self.assertEqual(ack_delivery(delivery, self.publisher, receipt, "Operador verificó el comprobante remoto en el panel principal.").pk, delivery.pk)
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery, remote_id="43"), "Operador verificó el comprobante remoto en el panel principal.")

    def test_ack_rejects_mismatched_stale_or_untrusted_receipts(self):
        delivery = prepare_delivery(self.machine, self.publisher, self.payload)
        self.review_duplicates(delivery)
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery, source_machine_id="00000000-0000-0000-0000-000000000000"), "Evidencia independiente suficiente.")
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery, remote_url="http://imcmexico.com.mx/x"), "Evidencia independiente suficiente.")
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery, remote_url="https://imcmexico.com.mx:444/x"), "Evidencia independiente suficiente.")
        replacement = MachineVersion.objects.create(machine=self.machine, number=2, data={"title": "Nueva", "data": {}}, created_by=self.publisher)
        self.machine.approved_version = replacement
        self.machine.save(update_fields=["approved_version", "updated_at"])
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery), "Evidencia independiente suficiente.")

    def test_ack_requires_current_availability_and_active_approved_owner(self):
        delivery = prepare_delivery(self.machine, self.publisher, self.payload)
        self.review_duplicates(delivery)
        self.machine.availability = "reserved"
        self.machine.save(update_fields=["availability", "updated_at"])
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery), "Evidencia independiente suficiente.")
        refreshed = {**self.payload, "availability": "reserved"}
        replacement = prepare_delivery(self.machine, self.publisher, refreshed)
        self.review_duplicates(replacement)
        self.owner.advertiser_status = "suspended"
        self.owner.save(update_fields=["advertiser_status"])
        with self.assertRaises(ValidationError):
            ack_delivery(replacement, self.publisher, self.receipt(replacement), "Evidencia independiente suficiente.")

    def test_older_different_preparation_cannot_be_acknowledged(self):
        old = prepare_delivery(self.machine, self.publisher, self.payload)
        newer = prepare_delivery(self.machine, self.publisher, {**self.payload, "listing": {"title": "Corrección"}})
        self.review_duplicates(old)
        self.review_duplicates(newer)
        self.assertNotEqual(old.pk, newer.pk)
        with self.assertRaises(ValidationError):
            ack_delivery(old, self.publisher, self.receipt(old), "Evidencia independiente suficiente.")

    def test_reselecting_an_acknowledged_payload_is_safe_unless_a_newer_receipt_exists(self):
        first = prepare_delivery(self.machine, self.publisher, self.payload)
        self.review_duplicates(first)
        ack_delivery(first, self.publisher, self.receipt(first), "Operador verificó el comprobante remoto en el panel principal.")
        changed = prepare_delivery(self.machine, self.publisher, {**self.payload, "listing": {"title": "B"}})
        self.review_duplicates(changed)
        self.assertNotEqual(first.pk, changed.pk)
        again = prepare_delivery(self.machine, self.publisher, self.payload)
        self.review_duplicates(again)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(ack_delivery(again, self.publisher, self.receipt(again), "Operador verificó el comprobante remoto en el panel principal.").pk, first.pk)

    def test_model_rejects_cross_machine_links_and_mutable_payload(self):
        delivery = prepare_delivery(self.machine, self.publisher, self.payload)
        other = Machine.objects.create(owner=self.owner, title="Ajena")
        other_version = MachineVersion.objects.create(machine=other, number=1, data={"title": "Ajena", "data": {}}, created_by=self.publisher)
        with self.assertRaises(ValidationError):
            IntegrationDelivery.objects.create(publication=delivery.publication, version=other_version,
                                               source_machine_id=self.machine.pk, payload=self.payload, payload_sha256="b" * 64)
        delivery.payload = {"altered": True}
        with self.assertRaises(ValidationError):
            delivery.save()

    def test_prepare_rejects_inactive_owner(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            prepare_delivery(self.machine, self.publisher, self.payload)

    def test_ack_rejects_duplicate_remote_id_and_preserves_leading_zeroes(self):
        delivery = prepare_delivery(self.machine, self.publisher, self.payload)
        self.review_duplicates(delivery)
        other = Machine.objects.create(owner=self.owner, title="Otra")
        other_version = MachineVersion.objects.create(machine=other, number=1, data={"title": "Otra", "data": {}}, created_by=self.publisher)
        other.approved_version = other_version
        other.save(update_fields=["approved_version", "updated_at"])
        other_delivery = prepare_delivery(other, self.publisher, {"schema": "public-machine-v1", "machine_id": str(other.pk),
                                                                   "version": 1, "availability": "available", "listing": {"title": "Otra"}})
        self.review_duplicates(other_delivery)
        ack_delivery(other_delivery, self.publisher, self.receipt(other_delivery), "Operador verificó el comprobante remoto en el panel principal.")
        with self.assertRaises(ValidationError):
            ack_delivery(delivery, self.publisher, self.receipt(delivery), "Operador verificó el comprobante remoto en el panel principal.")
        self.assertEqual(Publication.objects.get(machine=other, destination="main").external_id, "000042")

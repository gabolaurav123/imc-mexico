"""Commercial suggestions cannot overwrite declarations or cross currencies."""
from copy import deepcopy
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase

from portal.commercial import ESTIMATE_LABELS, VISUAL_LABELS
from portal.models import AnalysisJob, Asset, Category, Consent, Machine, User
from portal.services import (apply_analysis_automatically, apply_analysis_suggestions,
                             automatic_application_snapshot, public_valuation, save_draft, snapshot)
from portal.tests.test_visual_assessment import visual, normalize, assessment
from portal.valuation import LABEL, VALUATION_VERSION, _seal


class CommercialAutofillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="commercial-autofill@example.invalid", is_test=True)
        self.category = Category.objects.create(name="Montacargas", slug="montacargas")
        self.machine = Machine.objects.create(owner=self.user, category=self.category,
            data={"brand": "Caterpillar", "model": "2EC25"},
            provenance={key: {"source": "user", "review": "confirmed"} for key in ("brand", "model")})
        self.asset = Asset.objects.create(machine=self.machine, kind="image", processing_status="ready",
            purpose="general", original="synthetic/photo.jpg", size=1, mime_type="image/jpeg", sha256="a" * 64)
        Consent.objects.create(user=self.user, machine=self.machine, kind="ai", granted=True)

    def visual_result(self, **changes):
        asset = str(self.asset.pk)
        return normalize(visual(asset, value=assessment(**changes)), [asset])

    def estimate_result(self, minimum="10000", maximum="20000", currency="USD"):
        fields = {"estimate_min": minimum, "estimate_max": maximum, "estimate_currency": currency,
                  "estimate_market": "Estados Unidos", "estimate_date": "2026-09-18",
                  "estimate_basis": "Anuncios comparables del modelo",
                  "estimate_missing_info": "Confirmar conservación y funcionamiento"}
        valuation = {"version": VALUATION_VERSION, "status": "estimated", "identity": {"brand": "Caterpillar", "model": "2EC25"},
                     "fields": fields, "suggested_price": "15000", "label": LABEL,
                     "comparables": [dict(url="https://example.com/model/caterpillar-2ec25",
                        title="Caterpillar 2EC25", price="15000", currency=currency, market="Estados Unidos",
                        condition="Usada", price_type="asking", retrieved_at="2026-09-17")]}
        _seal(valuation)
        # A valuation suggests a price for the owner to choose; it cannot publish an asking price.
        data = {**fields, "estimate_suggested_price": valuation["suggested_price"]}
        return {"data": data, "provenance": {key: {"source": "valuation", "review": "needs_review",
                "component": "machine", "asset_id": None, "evidence": "Comparables públicos"} for key in data},
                "valuation": valuation, "fields": [], "plates": [], "warnings": [], "category": None}

    def job(self, result):
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.user, status="completed",
            revision=self.machine.revision, auto_apply=True, application_snapshot=automatic_application_snapshot(self.machine),
            asset_ids=[str(self.asset.pk)], fingerprint=uuid.uuid4().hex, result=deepcopy(result))

    def apply(self, job):
        self.machine, outcome = apply_analysis_automatically(self.machine, self.user, job, self.machine.revision)
        return outcome

    def edit(self, **data):
        self.machine = save_draft(self.machine, self.user, {"data": data}, self.machine.revision)

    def test_visual_proposals_apply_as_unconfirmed_and_never_confirm_operation(self):
        self.apply(self.job(self.visual_result()))
        self.assertEqual(self.machine.data["operating_status"], "Pendiente de confirmar")
        self.assertEqual(self.machine.data["preservation_condition"], "Aceptable")
        for key in VISUAL_LABELS:
            self.assertEqual(self.machine.provenance[key]["review"], "needs_review")
        self.assertEqual(self.machine.status, "draft")

    def test_human_edits_and_deliberate_clears_survive_reanalysis(self):
        self.apply(self.job(self.visual_result()))
        self.edit(preservation_notes="Inspección realizada por el propietario.", attachments="",
                  operating_status="Confirmado por el propietario")
        job = self.job(self.visual_result(preservation_notes="Óxido visible en la carrocería."))
        outcome = self.apply(job)
        self.assertEqual(self.machine.data["preservation_notes"], "Inspección realizada por el propietario.")
        self.assertEqual(self.machine.data["attachments"], "")
        self.assertEqual(self.machine.data["operating_status"], "Confirmado por el propietario")
        self.assertFalse({"preservation_notes", "attachments", "operating_status"} & set(outcome["applied_fields"]))

    def test_concurrent_human_clear_beats_a_pending_visual_refresh(self):
        self.apply(self.job(self.visual_result()))
        job = self.job(self.visual_result())
        self.edit(visible_components="")
        self.apply(job)
        self.assertEqual(self.machine.data["visible_components"], "")
        self.assertEqual(self.machine.provenance["visible_components"]["source"], "user")
        self.assertEqual(self.machine.provenance["visible_components"]["review"], "confirmed")
        self.assertEqual(self.machine.provenance["visible_components"]["confidence"], "owner_declared")

    def test_plate_only_does_not_assess_preservation(self):
        asset = str(self.asset.pk)
        result = normalize(visual(asset, kind="plate", relevance="related"), [asset])
        self.apply(self.job(result))
        self.assertFalse(set(self.machine.data) & set(VISUAL_LABELS))

    def test_forged_visual_source_and_flat_value_cannot_certify_operation(self):
        for source in ("visual_proposal", "image", "plate"):
            with self.subTest(source=source):
                result = self.visual_result()
                result["data"]["operating_status"] = "Confirmado por el propietario"
                result["provenance"]["operating_status"].update(source=source, review="clear")
                self.apply(self.job(result))
                self.assertNotEqual(self.machine.data.get("operating_status"), "Confirmado por el propietario")

    def test_manual_apply_also_rejects_forged_visual_status(self):
        result = self.visual_result()
        result["data"]["operating_status"] = "Confirmado por el propietario"
        job = self.job(result)
        with self.assertRaises(ValidationError):
            apply_analysis_suggestions(self.machine, self.user, job, ["operating_status"], self.machine.revision)

    def test_price_currency_human_change_does_not_receive_foreign_amount(self):
        job = self.job(self.estimate_result())
        self.edit(currency="MXN")
        self.apply(job)
        self.assertEqual(self.machine.data["currency"], "MXN")
        self.assertNotIn("price", self.machine.data)

    def test_human_price_or_clear_survives_new_estimate(self):
        for value in ("8500", ""):
            with self.subTest(value=value):
                self.edit(price=value, currency="USD")
                self.apply(self.job(self.estimate_result()))
                self.assertEqual(self.machine.data["price"], 8500 if value else None)
                self.assertEqual(self.machine.provenance["price"]["source"], "user")
                self.assertEqual(self.machine.provenance["price"]["review"], "confirmed")
                self.assertEqual(self.machine.provenance["price"]["confidence"], "owner_declared")

    def test_estimate_range_currency_concurrency_cannot_relabel_usd_as_mxn(self):
        job = self.job(self.estimate_result())
        self.edit(estimate_currency="MXN")
        self.apply(job)
        self.assertEqual(self.machine.data["estimate_currency"], "MXN")
        self.assertNotIn("estimate_min", self.machine.data)
        self.assertNotIn("estimate_max", self.machine.data)

    def test_unchanged_automatic_range_refreshes_both_endpoints(self):
        self.apply(self.job(self.estimate_result()))
        self.apply(self.job(self.estimate_result("25000", "30000")))
        self.assertEqual(self.machine.data["estimate_min"], 25000)
        self.assertEqual(self.machine.data["estimate_max"], 30000)
        self.assertEqual(self.machine.data["estimate_currency"], "USD")

    def test_changed_identity_blocks_pending_estimate_and_removes_only_automatic_old_range(self):
        self.apply(self.job(self.estimate_result()))
        job = self.job(self.estimate_result())
        self.edit(model="DIFFERENT", price="1234")
        self.apply(job)
        self.assertEqual(self.machine.data["price"], 1234)
        self.assertNotIn("estimate_min", self.machine.data)
        self.assertNotIn("estimate_max", self.machine.data)

    def test_invalid_manifest_and_tampered_field_are_not_applied(self):
        for mutation in ("proof", "field"):
            with self.subTest(mutation=mutation):
                result = self.estimate_result()
                if mutation == "proof":
                    result["valuation"]["proof"] = "forged"
                else:
                    result["data"]["estimate_suggested_price"] = "1"
                self.apply(self.job(result))
                self.assertNotIn("price", self.machine.data)

    def test_public_sources_filter_private_serial_in_url_title_and_query(self):
        self.edit(serial="PRIVATE123")
        result = self.estimate_result()
        valuation = result["valuation"]
        source = valuation["comparables"][0]
        valuation["comparables"].extend([
            {**source, "url": "https://example.com/PRIVATE123"},
            {**source, "title": "Caterpillar PRIVATE123"},
            {**source, "url": "https://example.com/item?serial=OTHER"}])
        valuation.pop("proof")
        _seal(valuation)
        self.apply(self.job(result))
        version = snapshot(self.machine, self.user)
        public = public_valuation(version.data)
        self.assertEqual(len(public["comparables"]), 1)
        self.assertNotIn("PRIVATE123", str(public))

    def test_public_estimate_fields_respect_edited_snapshot_values(self):
        self.apply(self.job(self.estimate_result()))
        self.edit(estimate_min="11000", estimate_max="19000")
        version = snapshot(self.machine, self.user)
        public = public_valuation(version.data)
        self.assertEqual(public["fields"]["estimate_min"], 11000)
        self.assertEqual(public["fields"]["estimate_max"], 19000)
        self.assertTrue(public["edited"])

    def test_suggested_price_is_not_replaced_by_owner_asking_price_or_currency(self):
        self.apply(self.job(self.estimate_result()))
        self.edit(price="99000", currency="MXN")
        public = public_valuation(snapshot(self.machine, self.user).data)
        self.assertEqual(str(public["suggested_price"]), "15000")
        self.assertEqual(public["fields"]["estimate_currency"], "USD")

    def test_new_insufficient_estimate_clears_old_ai_range_but_preserves_owner_price(self):
        self.machine.data.update(brand="Caterpillar", model="2EC25")
        self.machine.save()
        self.apply(self.job(self.estimate_result()))
        self.edit(price="19000", currency="MXN")
        from portal.valuation import _seal
        result = self.estimate_result()
        valuation = result["valuation"]
        valuation["status"] = "insufficient"
        valuation["suggested_price"] = None
        valuation["fields"] = {"estimate_basis": "No hay comparables suficientes.", "estimate_missing_info": "Falta otra unidad verificable."}
        result["valuation"] = _seal(valuation)
        result["data"] = dict(valuation["fields"])
        result["provenance"] = {key: {"source": "valuation", "review": "needs_review", "component": "machine"} for key in result["data"]}
        self.apply(self.job(result))
        self.assertNotIn("estimate_min", self.machine.data)
        self.assertNotIn("estimate_max", self.machine.data)
        self.assertNotIn("estimate_currency", self.machine.data)
        self.assertEqual(self.machine.data["price"], 19000)
        self.assertEqual(self.machine.data["currency"], "MXN")
        self.assertEqual(self.machine.data["estimate_missing_info"], "Falta otra unidad verificable.")

import json
from datetime import date

from django.test import TestCase

from portal.catalogue_intake import catalogue_proposal
from portal.intake import has_completed_preparation, preparation_mode, require_prepared_serial
from portal.models import AnalysisJob, Brand, Category, EquipmentModel, Machine, MarketReference, Submission, TechnicalReference, User
from portal.services import save_draft


class CatalogueOnlyIntakeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="catalogue-intake@example.invalid", password=None,
            phone="+525512345678", contact_preference="whatsapp")
        self.category = Category.objects.create(name="Excavadoras", slug="catalogue-excavators", active=True)
        self.brand = Brand.objects.create(name="Caterpillar", active=True)
        self.model = EquipmentModel.objects.create(brand=self.brand, name="320", category=self.category, active=True)
        self.reference = TechnicalReference.objects.create(
            category=self.category, equipment_model=self.model, brand="Caterpillar", model="320",
            period_from=2015, period_to=2020, specs={
                "power": {"value": "121 kW", "evidence": "Net power: 121 kW."},
                "hours": {"value": "5000", "evidence": "Example fleet hours: 5000."},
            }, source="https://manufacturer.example/320", source_title="320 specification sheet",
            retrieved_at=date(2026, 9, 25), review=TechnicalReference.Review.APPROVED, active=True,
            provenance={"period_evidence": "Production years: 2015-2020."},
        )
        for suffix, amount in (("one", "100000.00"), ("two", "120000.00")):
            MarketReference.objects.create(equipment_model=self.model, source=f"https://{suffix}.example/320",
                source_title=f"320 {suffix}", price=amount, currency="USD", market="US",
                price_type=MarketReference.PriceType.ASKING, condition=MarketReference.Condition.USED,
                retrieved_at=date(2026, 9, 25), evidence="Caterpillar 320 used listing.", configurations={},
                review=MarketReference.Review.APPROVED, active=True)

    def test_catalogue_draft_carries_model_references_without_unit_claims(self):
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        self.assertEqual(proposal["data"]["brand"], "Caterpillar")
        self.assertEqual(proposal["data"]["model"], "320")
        self.assertEqual(proposal["data"]["power"], "121 kW")
        self.assertEqual(proposal["data"]["estimated_year_from"], 2015)
        self.assertEqual(proposal["data"]["estimated_year_to"], 2020)
        self.assertEqual(proposal["data"]["estimate_min"], "100000.00")
        self.assertEqual(proposal["data"]["estimate_max"], "120000.00")
        self.assertNotIn("year", proposal["data"])
        self.assertNotIn("hours", proposal["data"])
        self.assertNotIn("location", proposal["data"])
        self.assertEqual(proposal["provenance"]["power"]["source"], "web_model")
        self.assertEqual(proposal["provenance"]["model"]["basis"], "catalogue_intake")

    def test_catalogue_mode_is_explicit_and_allows_no_media_share_submit_guard(self):
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        self.assertEqual(preparation_mode(machine), "catalogue")
        self.assertTrue(has_completed_preparation(machine))
        self.assertEqual(require_prepared_serial(machine), "catalogue")

    def test_model_without_specs_still_describes_its_documented_period_and_market_range(self):
        self.reference.specs = {}
        self.reference.save(update_fields=["specs"])
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        self.assertEqual(len(proposal["data"]["description"].splitlines()), 3)
        self.assertIn("Valor orientativo de equipos comparables", proposal["data"]["description"])
        self.assertNotIn("power", proposal["data"])

    def test_manual_edits_keep_owner_provenance_and_do_not_backfill_unit_fields(self):
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        updated = save_draft(machine, self.owner, {"data": {"power": "118 kW", "hours": None,
            "year": None, "location": ""}}, machine.revision)
        self.assertEqual(updated.data["power"], "118 kW")
        self.assertEqual(updated.provenance["power"]["source"], "user")
        self.assertIsNone(updated.data["hours"])
        self.assertIsNone(updated.data["year"])
        self.assertEqual(updated.data["location"], "")

    def test_catalogue_api_creates_only_a_selected_approved_model(self):
        self.client.force_login(self.owner)
        response = self.client.post("/api/maquinarias/catalogo/", json.dumps({"category": self.category.pk,
            "model_id": self.model.pk}), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIn("entrada=catalogue&paso=2", response.json()["url"])
        machine = Machine.objects.get(pk=response.json()["id"])
        self.assertEqual(machine.data["model"], "320")
        self.assertNotIn("hours", machine.data)
        rejected = self.client.post("/api/maquinarias/catalogo/", json.dumps({"category": self.category.pk,
            "model_id": 99999}), content_type="application/json")
        self.assertEqual(rejected.status_code, 400)

    def test_catalogue_mode_can_be_shared_and_submitted_without_assets(self):
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        self.client.force_login(self.owner)
        share = self.client.post(f"/api/maquinarias/{machine.pk}/compartir/", json.dumps({
            "revision": machine.revision, "action": "enable", "include_serial": False,
            "include_contact": False}), content_type="application/json")
        self.assertEqual(share.status_code, 200, share.content)
        self.assertTrue(share.json()["enabled"])
        submit = self.client.post(f"/api/maquinarias/{machine.pk}/enviar/", json.dumps({
            "advertise_consent": True, "contact_consent": False}), content_type="application/json")
        self.assertEqual(submit.status_code, 200, submit.content)
        self.assertEqual(Submission.objects.filter(machine=machine).count(), 1)

    def test_generate_again_refreshes_catalogue_fiche_without_creating_an_analysis_job(self):
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        self.client.force_login(self.owner)
        response = self.client.post(f"/api/maquinarias/{machine.pk}/analizar/", json.dumps({
            "consent": True, "revision": machine.revision, "asset_ids": [], "mode": "description",
            "research": True, "auto_apply": True}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["mode"], "catalogue")
        self.assertTrue(response.json()["refresh"])
        self.assertEqual(response.json()["machine"]["data"]["model"], "320")
        self.assertFalse(AnalysisJob.objects.filter(machine=machine).exists())

    def test_manual_identity_change_cannot_share_the_previous_model_references(self):
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        changed = save_draft(machine, self.owner, {"data": {"brand": "Otra marca", "model": "Otro modelo",
            "serial": "SERIE-NUEVA-001"}}, machine.revision)
        AnalysisJob.objects.create(machine=changed, revision=changed.revision, requested_by=self.owner,
            asset_ids=[], mode="description", fingerprint="a" * 64, status="completed",
            result={"relevance": {"status": "accepted"}})
        self.assertFalse(has_completed_preparation(changed))
        self.client.force_login(self.owner)
        response = self.client.post(f"/api/maquinarias/{changed.pk}/compartir/", json.dumps({
            "revision": changed.revision, "action": "enable", "include_serial": False,
            "include_contact": False}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("genera la ficha", response.json()["error"].lower())

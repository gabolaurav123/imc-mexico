import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from portal.catalogue_intake import catalogue_proposal, catalogue_selection_research
from portal.intake import catalogue_enrichment_needed, has_completed_preparation, preparation_mode, require_prepared_serial
from portal.models import AnalysisJob, Brand, Category, EquipmentModel, Machine, MarketReference, Submission, TechnicalReference, User
from portal.research import ResearchCandidates, research_machine
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
        self.assertEqual(proposal["title"], "Excavadora Caterpillar 320")
        self.assertEqual(proposal["title_provenance"], {"source": "system", "review": "needs_review"})
        self.assertEqual(proposal["provenance"]["power"]["source"], "web_model")
        self.assertEqual(proposal["provenance"]["model"]["basis"], "catalogue_intake")

    def test_catalogue_mode_is_explicit_and_allows_no_media_share_submit_guard(self):
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        self.assertEqual(preparation_mode(machine), "catalogue")
        self.assertTrue(has_completed_preparation(machine))
        self.assertEqual(require_prepared_serial(machine), "catalogue")
        self.assertFalse(catalogue_enrichment_needed(machine))

    def test_model_without_specs_still_describes_its_documented_period_and_market_range(self):
        self.reference.specs = {}
        self.reference.save(update_fields=["specs"])
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        self.assertEqual(len(proposal["data"]["description"].splitlines()), 3)
        self.assertIn("Valor orientativo de equipos comparables", proposal["data"]["description"])
        self.assertNotIn("power", proposal["data"])
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        self.assertTrue(catalogue_enrichment_needed(machine))

    def test_catalogue_enrichment_uses_model_scope_and_skips_serial_and_broad_manual_search(self):
        """A selected model keeps local proof and only makes two bounded lookups."""
        self.reference.source = "https://www.cat.com/en_US/products/320.html"
        self.reference.source_title = "Caterpillar 320 specification sheet"
        self.reference.specs["power"]["evidence"] = "Caterpillar 320: Net power 121 kW."
        self.reference.save(update_fields=["source", "source_title", "specs"])
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        snapshot = {"data": {**proposal["data"], "serial": "UNIT-123"},
                    "provenance": {**proposal["provenance"], "serial": {"source": "user", "review": "confirmed"}},
                    "category": self.category.name,
                    "provenance": {**proposal["provenance"], "serial": {"source": "user", "review": "confirmed"},
                                   "category": {"source": "user", "review": "confirmed"}}}
        result = {"data": {"brand": proposal["data"]["brand"], "model": proposal["data"]["model"]},
                  "provenance": {"brand": proposal["provenance"]["brand"], "model": proposal["provenance"]["model"]},
                  "category": self.category.name, "fields": [], "warnings": []}
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(status="completed", output_text="", output=[],
            usage=SimpleNamespace(input_tokens=0, output_tokens=0))
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=ResearchCandidates(fields=[]),
            usage=SimpleNamespace(input_tokens=0, output_tokens=0))
        research, _ = research_machine(client, "gpt-5.6-luna", result, snapshot,
            allowed_categories=[self.category.name], knowledge_category=self.category, catalogue_enrichment=True,
            catalogue_reference=catalogue_selection_research(machine))
        requests = [json.loads(call.kwargs["input"]) for call in client.responses.create.call_args_list]
        self.assertEqual([item["research_stage"] for item in requests], ["manufacturer", "catalogs"])
        self.assertTrue(all(item["identifiers"]["serial"] is None for item in requests))
        self.assertIsNone(research["identity"]["serial"])
        self.assertEqual(client.responses.create.call_count, 2)
        self.assertIn("power", {field["key"] for field in research["fields"]})

    def test_catalogue_selection_research_rebuilds_only_signed_model_evidence(self):
        self.reference.source = "https://www.cat.com/en_US/products/320.html"
        self.reference.source_title = "Caterpillar 320 specification sheet"
        self.reference.specs["power"]["evidence"] = "Caterpillar 320: Net power 121 kW."
        self.reference.save(update_fields=["source", "source_title", "specs"])
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        local = catalogue_selection_research(machine)
        self.assertIsNotNone(local)
        self.assertEqual(local["identity"], {"brand": "Caterpillar", "model": "320", "serial": None})
        fields = {item["key"]: item for item in local["fields"]}
        self.assertEqual(fields["power"]["scope"], "model")
        self.assertEqual(fields["power"]["value"], "121 kW")
        self.assertEqual(fields["power"]["source_url"], self.reference.source)
        self.assertIn("estimated_year_from", fields)
        self.assertNotIn("estimate_min", fields)
        self.assertTrue(local["proof"])

    def test_catalogue_api_queues_only_an_explicit_incomplete_enrichment(self):
        self.reference.specs = {}
        self.reference.save(update_fields=["specs"])
        proposal = catalogue_proposal(self.category.pk, self.model.pk)
        machine = Machine.objects.create(owner=self.owner, category=self.category, data=proposal["data"],
            provenance=proposal["provenance"])
        self.client.force_login(self.owner)
        queued = Mock()
        with patch("portal.processing.enqueue_analysis", return_value=queued) as enqueue, \
             patch("portal.views.analysis_state", return_value={"status": "queued", "id": "job-1"}):
            response = self.client.post(f"/api/maquinarias/{machine.pk}/analizar/", json.dumps({
                "consent": True, "revision": machine.revision, "asset_ids": [], "mode": "description",
                "research": True, "auto_apply": True, "enrich_catalogue": True}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(enqueue.call_args.kwargs["catalogue_enrichment"], True)
        self.assertEqual(enqueue.call_args.args[3], "description")
        self.assertTrue(enqueue.call_args.kwargs["research"])

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
        self.assertEqual(machine.title, "Excavadora Caterpillar 320")
        self.assertEqual(machine.provenance["title"], {"source": "system", "review": "needs_review"})
        self.assertEqual(machine.data["model"], "320")
        self.assertNotIn("hours", machine.data)
        rejected = self.client.post("/api/maquinarias/catalogo/", json.dumps({"category": self.category.pk,
            "model_id": 99999}), content_type="application/json")
        self.assertEqual(rejected.status_code, 400)

    def test_catalogue_start_form_creates_the_commercial_title(self):
        self.client.force_login(self.owner)
        response = self.client.post("/panel/maquinarias/nueva/", {
            "category": self.category.pk, "entry_mode": "catalogue", "catalogue_model": self.model.pk,
        })
        self.assertEqual(response.status_code, 302)
        machine = Machine.objects.get(owner=self.owner, title="Excavadora Caterpillar 320")
        self.assertIn(f"/panel/maquinarias/{machine.pk}/?entrada=catalogue&paso=2", response.url)
        self.assertEqual(machine.provenance["title"], {"source": "system", "review": "needs_review"})

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

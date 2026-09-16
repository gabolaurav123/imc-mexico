"""Signed model references must not displace readings of the actual unit."""
import copy
import uuid

from django.test import TestCase

from portal.models import AnalysisJob, Asset, Consent, Machine, User
from portal.research import (ResearchExtraction, ResearchField, is_validated_web_field,
                             merge_research, normalize_research)
from portal.services import apply_analysis_automatically, automatic_application_snapshot


class PlateRefreshReviewTests(TestCase):
    def test_signed_web_reference_preserves_existing_unit_reading(self):
        owner = User.objects.create_user(email="plate-web-review@example.invalid", is_test=True)
        url = "https://www.cat.com/en_US/products/new/equipment/backhoe-loaders/420f2.html"
        text = "Caterpillar 420F2: potencia 70 kW."
        research = normalize_research(
            ResearchExtraction(fields=[ResearchField(
                key="power", value="70 kW", scope="model", source_url=url, evidence=text,
                matched_brand="Caterpillar", matched_model="420F2", matched_serial=None)]),
            {"brand": "Caterpillar", "model": "420F2", "serial": None}, "model",
            [{"url": url, "title": "Caterpillar 420F2"}], text, citations={url: [text]})
        result = merge_research({"data": {}, "provenance": {}, "fields": [], "plates": []}, research)
        self.assertEqual(research["status"], "completed")
        self.assertTrue(is_validated_web_field(result, "power", "70 kW", result["provenance"]["power"]))

        for source in ("plate", "image"):
            for review in ("clear", "confirmed"):
                with self.subTest(source=source, review=review):
                    machine = Machine.objects.create(owner=owner, title="Retroexcavadora",
                        data={"brand": "Caterpillar", "model": "420F2", "power": "68 kW"})
                    asset = Asset.objects.create(machine=machine, kind="image", purpose="general",
                        processing_status="ready", sha256="a" * 64, original="test/unit.jpg",
                        size=1, mime_type="image/jpeg")
                    previous = AnalysisJob.objects.create(machine=machine, requested_by=owner,
                        revision=machine.revision, fingerprint=uuid.uuid4().hex, status="completed")
                    original_meta = {"source": source, "review": review, "component": "machine",
                                     "asset_id": str(asset.pk), "analysis_id": str(previous.pk),
                                     "evidence": "Potencia de la unidad: 68 kW"}
                    machine.provenance = {"power": original_meta}
                    machine.save(update_fields=["provenance"])
                    Consent.objects.create(user=owner, machine=machine, kind="ai", granted=True)
                    job = AnalysisJob.objects.create(machine=machine, requested_by=owner,
                        revision=machine.revision, fingerprint=uuid.uuid4().hex, status="completed",
                        auto_apply=True, asset_ids=[str(asset.pk)],
                        application_snapshot=automatic_application_snapshot(machine), result=copy.deepcopy(result))

                    machine, summary = apply_analysis_automatically(machine, owner, job, machine.revision)
                    self.assertEqual(machine.data["power"], "68 kW")
                    self.assertEqual(machine.provenance["power"], original_meta)
                    self.assertNotIn("power", summary["applied_fields"])
                    self.assertEqual(summary["field_reasons"]["power"], "existing_unit_reading")

"""An incomplete old visual label is not definitive proof against an owner correction."""
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, TestCase, override_settings

from portal.models import AnalysisJob, Asset, Category, Machine, PreparedShare, User
from portal.research import ResearchExtraction, ResearchField, normalize_research


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_URL="https://example.invalid")
class HistoricalModelCorrectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="historical-model@example.invalid")
        self.category = Category.objects.create(name="Compactadores", slug="historical-compactors")
        self.machine = Machine.objects.create(owner=self.owner, category=self.category,
            title="Compactador BOMAG BW211D40", data={
                "brand": "BOMAG", "model": "BW211D40", "serial": "PRIVATE123",
                "estimated_year_from": 2005, "estimated_year_to": 2015,
                "estimate_min": "35000", "estimate_max": "65000", "estimate_currency": "USD",
                "description": "Compactador de suelo con un tambor delantero.\n"
                    "Rodillo con superficie lisa para compactación del terreno.\n"
                    "Dispone de cabina cerrada para el puesto del operador."},
            provenance={key: {"source": "user", "review": "confirmed"}
                        for key in ("brand", "model", "description", "estimated_year_from",
                                    "estimated_year_to", "estimate_min", "estimate_max", "estimate_currency")})
        self.asset = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
            processing_status="ready", original="test/old-model.jpg", sha256="a" * 64,
            size=1, mime_type="image/jpeg")
        self.result = {
            "data": {"brand": "BOMAG", "model": "1D-40"},
            "fields": [self.field("brand", "BOMAG"), self.field("model", "1D-40")],
            "image_observations": [{"asset_id": str(self.asset.pk), "kind": "machine",
                "relevance": "machinery", "category": "Compactadores", "machine_count": 1}],
            "relevance": {"status": "relevant", "accepted_asset_ids": [str(self.asset.pk)]},
            "completion": {"missing_fields": ["year_range", "price_range"]},
        }
        self.job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, status="completed", mode="analysis", fingerprint=uuid4().hex,
            prompt_version="imc-excavators-2026-09-v46", asset_ids=[str(self.asset.pk)], result=self.result)
        self.client.force_login(self.owner)

    def field(self, key, value, **changes):
        return {"key": key, "value": value, "source": "image", "review": "clear",
                "component": "machine", "asset_id": str(self.asset.pk), **changes}

    def share(self):
        return self.client.post(f"/api/maquinarias/{self.machine.pk}/compartir/",
            json.dumps({"revision": self.machine.revision}), content_type="application/json")

    def save_result(self, result):
        self.job.result = result
        self.job.save(update_fields=["result"])

    def legacy_model_reference(self, evidence):
        url = "https://www.indonetwork.co.id/product/alat-berat-komatsu-hitachi-excavator-4029163?utm_source=openai"
        field = ResearchField(key="model", value="1D-40", scope="model", source_url=url,
            evidence=evidence, matched_serial=None, matched_brand="BOMAG", matched_model="1D-40")
        # The former validator signed this exact citation. Keep its original
        # manifest intact and exercise today's offline revalidation at sharing.
        with patch("portal.research._ambiguous_model_occurrence_reason", return_value=""):
            research = normalize_research(ResearchExtraction(fields=[field]),
                {"serial": None, "brand": "BOMAG", "model": "1D-40"}, "model",
                [{"url": url, "title": "BOMAG COMPECTOR"}], evidence, citations={url: [evidence]})
        self.assertEqual([item["key"] for item in research["fields"]], ["model"])
        self.assertTrue(research["proof"])
        return research

    def test_corrected_full_model_can_share_without_rewriting_history_or_using_ai(self):
        before = deepcopy(self.job.result)
        revision = self.machine.revision
        response = self.share()
        self.assertEqual(response.status_code, 200, response.content)
        share = PreparedShare.objects.get(machine=self.machine)
        self.assertEqual(share.snapshot["data"]["model"], "BW211D40")
        public = Client().get(response.json()["url"].removeprefix("https://example.invalid"))
        self.assertEqual(public.status_code, 200)
        self.assertContains(public, "BW211D40")
        self.assertNotContains(public, "PRIVATE123")
        self.assertEqual(public.context["data"]["estimate_min"], "35000")
        self.assertEqual(public.context["data"]["estimated_year_from"], 2005)
        self.job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(self.job.result, before)
        self.assertEqual(self.machine.revision, revision)
        self.assertEqual(AnalysisJob.objects.count(), 1)

    def test_compatible_fragment_is_not_a_confirmed_model_match(self):
        from portal.analysis_specialization import check_equipment_consistency, historical_model_fragments
        result = deepcopy(self.result)
        result["fields"] = [self.field("model", "1D-40")]
        snapshot = {"data": self.machine.data, "provenance": self.machine.provenance}
        fragments = historical_model_fragments(result, snapshot, {str(self.asset.pk)})
        check_equipment_consistency(result, snapshot, model_fragments=fragments)
        self.assertEqual(result["consistency"]["status"], "insufficient_evidence")
        self.assertFalse(any(item["outcome"] == "match" for item in result["consistency"]["comparisons"]))

    def test_old_signed_citation_with_exact_then_longer_model_does_not_block_corrected_share(self):
        evidence = ('**Modelo:** 1D-40; el anuncio lo presenta dentro de la denominación '
                    '“BOMAG COMPECTOR BW2 1D-40”.')
        self.result["research"] = self.legacy_model_reference(evidence)
        self.save_result(self.result)
        historical = deepcopy(self.job.result)
        saved = deepcopy(self.machine.data)
        provenance = deepcopy(self.machine.provenance)
        revision = self.machine.revision
        response = self.share()
        self.assertEqual(response.status_code, 200, response.content)
        public = Client().get(response.json()["url"].removeprefix("https://example.invalid"))
        self.assertEqual(public.status_code, 200)
        for key in ("brand", "model", "estimated_year_from", "estimated_year_to", "estimate_min",
                    "estimate_max", "estimate_currency", "description"):
            with self.subTest(key=key):
                self.assertEqual(public.context["data"][key], saved[key])
        self.assertNotContains(public, "PRIVATE123")
        self.assertNotContains(public, "1D-40")
        self.assertNotContains(public, "indonetwork")
        self.job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(self.job.result, historical)
        self.assertEqual(self.machine.data, saved)
        self.assertEqual(self.machine.provenance, provenance)
        self.assertEqual(self.machine.revision, revision)
        self.assertEqual(AnalysisJob.objects.count(), 1)

    def test_old_signed_literal_model_citation_still_blocks_a_different_owner_model(self):
        evidence = "BOMAG. Modelo: 1D-40. Compactador de suelo con tambor liso."
        self.result["research"] = self.legacy_model_reference(evidence)
        self.save_result(self.result)
        historical = deepcopy(self.job.result)
        response = self.share()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("referencia documentada", response.json()["error"])
        self.assertIn(evidence, response.json()["error"])
        self.assertFalse(PreparedShare.objects.exists())
        self.job.refresh_from_db()
        self.assertEqual(self.job.result, historical)

    def test_explicit_visibility_plate_and_different_models_still_block_sharing(self):
        for changes in ({"model_label_visibility": "complete"}, {"model_label_visibility": None},
                        {"source": "plate"}, {"value": "BW213D40"}, {"value": "R2"}, {"value": "90"}):
            with self.subTest(changes=changes):
                result = deepcopy(self.result)
                result["fields"][1].update(changes)
                if changes.get("value") in {"R2", "90"}:
                    self.machine.data["model"] = "BW" + changes["value"]
                    self.machine.save(update_fields=["data"])
                else:
                    self.machine.data["model"] = "BW211D40"
                    self.machine.save(update_fields=["data"])
                self.save_result(result)
                response = self.share()
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("no coinciden", response.json()["error"])

    def test_fragment_exception_requires_general_machine_photo_and_human_correction(self):
        for change in ("plate_asset", "plate_observation", "no_observation", "automatic_model"):
            with self.subTest(change=change):
                self.asset.purpose = "plate" if change == "plate_asset" else "general"
                self.asset.save(update_fields=["purpose"])
                result = deepcopy(self.result)
                if change == "plate_observation":
                    result["image_observations"][0]["kind"] = "plate"
                elif change == "no_observation":
                    result["image_observations"] = []
                snapshot = {"data": self.machine.data, "provenance": deepcopy(self.machine.provenance)}
                if change == "automatic_model":
                    snapshot["provenance"]["model"] = {"source": "image", "review": "clear"}
                from portal.analysis_specialization import historical_model_fragments
                general = {str(self.asset.pk)} if self.asset.purpose == "general" else set()
                self.assertFalse(historical_model_fragments(result, snapshot, general))

    def test_legacy_duplicate_does_not_hide_a_definitive_reading(self):
        for changes in ({"model_label_visibility": "complete"}, {"source": "plate"}):
            with self.subTest(changes=changes):
                result = deepcopy(self.result)
                result["fields"].append(self.field("model", "1D-40", **changes))
                self.save_result(result)
                response = self.share()
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("no coinciden", response.json()["error"])

    def test_signed_document_for_original_model_preserves_conflict(self):
        url = "https://www.bomag.com/model-document"
        text = "BOMAG 1D-40: potencia 70 kW."
        field = ResearchField(key="power", value="70 kW", scope="model", source_url=url,
            evidence=text, matched_serial=None, matched_brand="BOMAG", matched_model="1D-40")
        self.result["research"] = normalize_research(ResearchExtraction(fields=[field]),
            {"serial": None, "brand": "BOMAG", "model": "1D-40"}, "model",
            [{"url": url, "title": "BOMAG 1D-40"}], text, citations={url: [text]})
        self.assertTrue(self.result["research"]["fields"])
        self.save_result(self.result)
        response = self.share()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("no coinciden", response.json()["error"])
        self.assertIn("Modelo: guardado «BW211D40»; lectura de foto «1D-40»", response.json()["error"])
        self.assertIn("referencia documentada", response.json()["error"])
        self.assertIn(text, response.json()["error"])
        self.assertIn(url, response.json()["error"])
        self.assertNotIn(self.result["research"]["proof"], response.json()["error"])
        # Unsigned research prose alone does not turn the old fragment into proof.
        self.result["research"].pop("proof")
        self.save_result(self.result)
        self.assertEqual(self.share().status_code, 200)

    def test_private_error_explains_visibility_and_does_not_expose_owner_details_to_other_users(self):
        self.result["fields"][1]["model_label_visibility"] = "complete"
        self.save_result(self.result)
        before = deepcopy(self.job.result)
        response = self.share()
        self.assertEqual(response.status_code, 400)
        self.assertIn("etiqueta completa", response.json()["error"])
        self.assertIn("BW211D40", response.json()["error"])
        self.assertIn("1D-40", response.json()["error"])
        self.assertFalse(PreparedShare.objects.exists())
        self.job.refresh_from_db()
        self.assertEqual(self.job.result, before)
        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.client.force_login(User.objects.create_user(email="other-fragment-owner@example.invalid"))
        response = self.share()
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("BW211D40", response.json()["error"])
        self.client.logout()
        response = self.share()
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("1D-40", response.json()["error"])

    def test_missing_machine_observation_explains_the_actual_restriction(self):
        self.result["image_observations"] = []
        self.save_result(self.result)
        response = self.share()
        self.assertEqual(response.status_code, 400)
        self.assertIn("vista de la máquina completa", response.json()["error"])

    def test_older_multi_photo_analysis_cannot_replace_the_latest_conflict_explanation(self):
        second = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
            processing_status="ready", original="test/second.jpg", sha256="b" * 64)
        older = deepcopy(self.result)
        older["fields"].append(self.field("model", "1D-40", asset_id=str(second.pk)))
        older["image_observations"].append({**older["image_observations"][0], "asset_id": str(second.pk)})
        older["relevance"]["accepted_asset_ids"].append(str(second.pk))
        previous = AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, status="completed", mode="analysis", fingerprint=uuid4().hex,
            asset_ids=[str(self.asset.pk), str(second.pk)], result=older)
        AnalysisJob.objects.filter(pk=previous.pk).update(created_at=self.job.created_at - timedelta(seconds=1))
        self.result["fields"][1]["model_label_visibility"] = "complete"
        self.save_result(self.result)
        response = self.share()
        self.assertEqual(response.status_code, 400)
        self.assertIn("etiqueta completa", response.json()["error"])
        self.assertNotIn("no procede de una fotografía clasificada como vista general", response.json()["error"])

    def test_other_identity_and_multiple_machine_conflicts_remain_blocking(self):
        for change in ("brand", "serial", "category", "machine_count", "cross_photo"):
            with self.subTest(change=change):
                result = deepcopy(self.result)
                second = None
                if change == "brand":
                    result["fields"][0]["value"] = "HAMM"
                elif change == "serial":
                    result["fields"].append(self.field("serial", "OTHER123", source="plate"))
                    self.machine.provenance["serial"] = {"source": "user", "review": "confirmed"}
                    self.machine.save(update_fields=["provenance"])
                elif change == "category":
                    result["image_observations"][0]["category"] = "Montacargas"
                elif change == "machine_count":
                    result["image_observations"][0]["machine_count"] = 2
                else:
                    second = Asset.objects.create(machine=self.machine, kind="image", purpose="general",
                        processing_status="ready", original="test/second.jpg", sha256="b" * 64)
                    result["fields"].append(self.field("model", "BW211D40", asset_id=str(second.pk)))
                    result["image_observations"].append({**result["image_observations"][0], "asset_id": str(second.pk)})
                    self.job.asset_ids = [str(self.asset.pk), str(second.pk)]
                    self.job.save(update_fields=["asset_ids"])
                self.save_result(result)
                response = self.share()
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("no coinciden", response.json()["error"])
                if second:
                    second.delete()

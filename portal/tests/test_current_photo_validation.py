"""Reported intake bypasses: independent classification and current-photo gates."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from portal.analysis_specialization import PROFILE_INSTRUCTIONS, check_equipment_consistency
from portal.intake import assessed_photo_states, has_completed_preparation, require_consistent_photos
from portal.models import AnalysisJob, Asset, Category, Machine, PlatformSettings, PreparedShare, User
from portal.processing import ImageObservation, enqueue_analysis, normalize_analysis, process_next_job
from portal.research import UsageTotals
from portal.services import automatic_application_snapshot
from portal.tests.test_image_relevance import field, observation, parsed


class PhotoCategoryAliasTests(SimpleTestCase):
    def test_grader_alias_is_not_discarded_and_conflicts_with_backhoe_selection(self):
        for alias in ("motoconformadora", "motoniveladora", "motor grader", "Motoniveladoras"):
            with self.subTest(alias=alias):
                result = normalize_analysis(parsed([observation("photo", category=alias)]), ["photo"],
                    allowed_categories=["Retroexcavadoras", "Motoniveladoras"])
                self.assertEqual(result["category"], "Motoniveladoras")
                self.assertEqual(check_equipment_consistency(result, {"category": "Retroexcavadoras"}), "category_conflict")

    def test_known_equivalent_names_and_unknown_guesses_do_not_make_conflicts(self):
        result = normalize_analysis(parsed([observation("photo", category="motoconformadora")]), ["photo"],
            allowed_categories=["Motoniveladoras"])
        self.assertFalse(check_equipment_consistency(result, {"category": "Motoniveladora"}))
        result = normalize_analysis(parsed([observation("photo", category="tal vez una motoniveladora")]), ["photo"],
            allowed_categories=["Retroexcavadoras", "Motoniveladoras"])
        self.assertIsNone(result["category"])
        self.assertFalse(check_equipment_consistency(result, {"category": "Retroexcavadoras"}))

    def test_other_or_unknown_object_cannot_claim_machinery_relevance(self):
        for kind, relevance in (("other", "machinery"), ("unknown", "machinery"), ("other", "related")):
            with self.subTest(kind=kind, relevance=relevance):
                result = normalize_analysis(parsed([observation("photo", relevance, kind)],
                    [field("brand", "Unsupported", "photo")]), ["photo"])
                self.assertEqual(result["relevance"]["status"], "uncertain")
                self.assertEqual(result["data"], {})

    def test_component_plate_category_is_not_proof_of_different_host_machine(self):
        result = normalize_analysis(parsed([observation("engine", "related", "plate", category="Motoniveladoras")],
            plates=[{"asset_id": "engine", "component": "engine", "readability": "clear", "transcription": "CAT engine"}]),
            ["engine"], allowed_categories=["Motoniveladoras", "Retroexcavadoras"])
        self.assertFalse(check_equipment_consistency(result, {"category": "Retroexcavadoras"}))

    def test_count_contract_excludes_incidental_yard_equipment_without_ignoring_collages(self):
        description = ImageObservation.model_json_schema()["properties"]["machine_count"]["description"]
        self.assertIn("sujetos principales", description)
        self.assertIn("maquinaria incidental al fondo", description)
        self.assertIn("machine_count=1, no 3", PROFILE_INSTRUCTIONS)
        self.assertIn("collage presenta dos máquinas diferentes", PROFILE_INSTRUCTIONS)

    def test_four_paver_views_with_incidental_background_equipment_are_one_advertised_unit(self):
        ids = ["front", "rear", "left", "right"]
        result = normalize_analysis(parsed([observation(pk, category="Pavimentadoras", machine_count=1,
            visual_features=["Pavimentadora principal con tolva y regla de extendido.",
                             "Equipos estacionados al fondo del patio."]) for pk in ids]), ids,
            allowed_categories=["Pavimentadoras", "Retroexcavadoras"])
        self.assertFalse(check_equipment_consistency(result, {"category": "Pavimentadoras"}))
        self.assertNotIn("multiple_machines", result)

    def test_two_primary_units_or_collage_still_require_separate_fiches(self):
        for count in (2, 3):
            with self.subTest(primary_units=count):
                result = normalize_analysis(parsed([observation("main", category="Pavimentadoras",
                    machine_count=count, visual_features=["Varios equipos en primer plano como protagonistas."])]),
                    ["main"], allowed_categories=["Pavimentadoras"])
                self.assertEqual(check_equipment_consistency(result, {"category": "Pavimentadoras"}), "multiple_machines")


@override_settings(SECURE_SSL_REDIRECT=False, OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class CurrentPhotoValidationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="photo-validation@example.invalid", phone="+525512345678")
        self.backhoe = Category.objects.create(name="Retroexcavadoras", slug="retroexcavadoras")
        self.grader = Category.objects.create(name="Motoniveladoras", slug="motoniveladoras")
        self.machine = Machine.objects.create(owner=self.owner, category=self.backhoe,
            title="Título del propietario", data={"description": "Descripción del propietario"},
            provenance={"description": {"source": "user", "review": "confirmed"},
                        "category": {"source": "user", "review": "confirmed"}})
        self.photo = self.asset()
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=1000000)
        self.client.force_login(self.owner)
        self.enterContext(patch("portal.processing.estimate_machine", return_value=({"status": "not_run"}, UsageTotals())))
        self.enterContext(patch("portal.processing.complete_machine_reference", return_value=(None, UsageTotals())))

    def asset(self, purpose="general"):
        return Asset.objects.create(machine=self.machine, kind="image", purpose=purpose, processing_status="ready",
            original="test/unused.jpg", preview="test/unused.jpg", size=1, mime_type="image/jpeg", sha256=uuid4().hex * 2)

    def completed(self, asset=None, state="accepted", category=None, *, preflight=False, manifest=True, **extra):
        asset = asset or self.photo
        key = {"accepted": "accepted_asset_ids", "unrelated": "excluded_asset_ids", "uncertain": "uncertain_asset_ids"}[state]
        result = {"preflight": preflight, "relevance": {"status": "relevant" if state == "accepted" else state,
            key: [str(asset.pk)]}, "fields": [], "image_observations": [observation(str(asset.pk),
            "machinery" if state == "accepted" else state, "machine" if state == "accepted" else "other",
            category=category)], **extra}
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, revision=self.machine.revision,
            asset_ids=[str(asset.pk)], mode="analysis", status="completed", fingerprint=uuid4().hex,
            application_snapshot=automatic_application_snapshot(self.machine) if manifest else {}, result=result)

    def assert_blocked(self, text=None):
        before = deepcopy(self.machine.data), deepcopy(self.machine.provenance)
        with self.assertRaises(ValidationError) as error:
            require_consistent_photos(self.machine)
        if text:
            self.assertIn(text, str(error.exception))
        shared = self.client.post(f"/api/maquinarias/{self.machine.pk}/compartir/",
            json.dumps({"revision": self.machine.revision}), content_type="application/json")
        self.assertEqual(shared.status_code, 400, shared.content)
        submitted = self.client.post(f"/api/maquinarias/{self.machine.pk}/enviar/",
            json.dumps({"advertise_consent": True}), content_type="application/json")
        self.assertEqual(submitted.status_code, 400, submitted.content)
        self.assertFalse(PreparedShare.objects.exists())
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertEqual(self.owner.advertiser_status, "pending")
        self.machine.refresh_from_db()
        self.assertEqual((self.machine.data, self.machine.provenance), before)

    def test_unanalysed_added_photo_blocks_sharing_even_when_explicitly_omitted_from_share(self):
        self.completed()
        new = self.asset()
        self.assert_blocked("pendientes de identificar")
        self.assertFalse(has_completed_preparation(self.machine))
        response = self.client.post(f"/api/maquinarias/{self.machine.pk}/compartir/",
            json.dumps({"revision": self.machine.revision, "asset_ids": [str(self.photo.pk)]}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        new.delete()
        require_consistent_photos(self.machine)
        self.assertTrue(has_completed_preparation(self.machine))

    def test_latest_uncertain_read_cannot_reuse_older_acceptance(self):
        self.completed()
        self.completed(state="uncertain")
        self.assertEqual(assessed_photo_states(self.machine)[str(self.photo.pk)], "uncertain")
        self.assert_blocked("pendientes de identificar")
        self.assertFalse(has_completed_preparation(self.machine))

    def test_unrelated_second_photo_cannot_hide_behind_valid_machine_or_serial(self):
        self.completed(category="Retroexcavadoras")
        self.machine.data["serial"] = "OWNER123"
        self.machine.provenance["serial"] = {"source": "user", "review": "confirmed"}
        self.machine.save(update_fields=["data", "provenance"])
        self.completed(self.asset(), state="unrelated")
        self.assert_blocked("no corresponden")

    def test_category_conflict_compares_current_owner_selection_without_rewriting_history(self):
        job = self.completed(category="motoconformadora")
        before = deepcopy(job.result)
        self.assert_blocked("no coinciden")
        self.machine.category = self.grader
        self.machine.save(update_fields=["category"])
        require_consistent_photos(self.machine)
        job.refresh_from_db()
        self.assertEqual(job.result, before)

    def test_different_categories_from_separate_jobs_still_conflict(self):
        self.completed(category="Retroexcavadoras")
        self.completed(self.asset(), category="Motoniveladoras")
        self.assert_blocked("no coinciden")

    def test_changed_photo_bytes_or_purpose_cannot_borrow_old_acceptance(self):
        self.completed()
        for key, value in (("sha256", "z" * 64), ("purpose", "plate")):
            with self.subTest(key=key):
                original = getattr(self.photo, key)
                setattr(self.photo, key, value)
                self.photo.save(update_fields=[key])
                self.assert_blocked("pendientes de identificar")
                self.assertFalse(has_completed_preparation(self.machine))
                setattr(self.photo, key, original)
                self.photo.save(update_fields=[key])
        require_consistent_photos(self.machine)

    def test_partial_job_never_claims_its_unprocessed_photo_is_prepared(self):
        self.completed()
        pending = self.asset()
        self.completed(pending, image_analysis_complete=False, image_readings=[
            {"asset_id": str(pending.pk), "status": "not_run"}])
        self.assertFalse(has_completed_preparation(self.machine))
        self.assert_blocked("pendientes de identificar")

    def test_preflight_alone_does_not_make_prepared_sheet(self):
        self.completed(preflight=True)
        require_consistent_photos(self.machine)
        self.assertFalse(has_completed_preparation(self.machine))

    def test_serial_description_request_cannot_skip_an_unanalysed_or_unrelated_photo(self):
        self.machine.data["serial"] = "OWNER123"
        self.machine.save(update_fields=["data"])
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.owner, mode="description", asset_ids=[], authorize_ai=True)
        self.assertFalse(self.machine.analysis_jobs.exists())
        self.completed(state="unrelated")
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.owner, mode="description", asset_ids=[], authorize_ai=True)
        self.assertEqual(self.machine.analysis_jobs.count(), 1)

    def worker(self, responses, *, research=True):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=research,
            auto_apply=True, expected_revision=self.machine.revision)
        with patch("portal.processing._image_input", return_value={"type": "input_image", "image_url": "data:test"}), \
             patch("openai.OpenAI") as provider, patch("portal.processing.research_machine") as external:
            provider.return_value.responses.parse.side_effect = [SimpleNamespace(status="completed", output_parsed=item,
                usage=SimpleNamespace(input_tokens=100, output_tokens=50)) for item in responses]
            process_next_job()
        job.refresh_from_db()
        self.machine.refresh_from_db()
        return job, provider.return_value.responses.parse, external

    def test_reported_backhoe_with_grader_photo_stops_before_research_and_preserves_owner_edits(self):
        before = deepcopy(self.machine.data), deepcopy(self.machine.provenance)
        job, provider, research = self.worker([parsed([observation("image_001", category="motoconformadora")],
            [field("brand", "CAT", "image_001")])])
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.result["blocking_reason"], "category_conflict")
        self.assertEqual(job.application_result["reason"], "category_conflict")
        self.assertEqual((self.machine.data, self.machine.provenance), before)
        research.assert_not_called()
        context = json.loads(provider.call_args.kwargs["input"][0]["content"][0]["text"])
        self.assertIsNone(context["selected_category"])
        self.assertEqual(context["category_profile"], {})
        self.assertEqual(context["declared_data"]["data"], {})
        self.assertEqual(job.result["input_snapshot"]["category"], "Retroexcavadoras")

    def test_unrelated_photo_stops_without_populating_or_punishing_the_owner(self):
        before = deepcopy(self.machine.data)
        job, provider, research = self.worker([parsed([observation("image_001", "unrelated", "other")])])
        self.assertEqual(job.result["blocking_reason"], "photo_relevance")
        self.assertEqual(job.application_result["reason"], "photo_relevance")
        research.assert_not_called()
        self.assertEqual(self.machine.data, before)
        self.assert_blocked("no corresponden")

    def test_correcting_type_reuses_independent_read_and_rechecks_against_new_selection(self):
        photo = parsed([observation("image_001", category="motoconformadora")], [field("brand", "CAT", "image_001")])
        first, provider, _ = self.worker([photo], research=False)
        self.assertEqual(first.result["blocking_reason"], "category_conflict")
        self.machine.category = self.grader
        self.machine.revision += 1
        self.machine.save(update_fields=["category", "revision"])
        second, provider, _ = self.worker([], research=False)
        self.assertEqual(second.status, "completed")
        provider.assert_not_called()
        self.assertNotIn("blocking_reason", second.result)
        self.assertEqual(second.result["image_readings"][0]["status"], "reused")
        self.assertEqual(self.machine.data["brand"], "CAT")
        self.assertEqual(self.machine.data["description"], "Descripción del propietario")
        self.assertEqual(first.result["input_snapshot"]["category"], "Retroexcavadoras")
        self.assertEqual(second.result["input_snapshot"]["category"], "Motoniveladoras")

    def test_new_unrelated_photo_cannot_borrow_cached_machine_read_and_removal_recovers_without_paid_reread(self):
        first, _, _ = self.worker([parsed([observation("image_001", category="Retroexcavadoras")],
            [field("brand", "CAT", "image_001")])], research=False)
        self.assertEqual(first.application_result["status"], "applied")
        before = deepcopy(self.machine.data)
        bad = self.asset()
        self.machine.revision += 1
        self.machine.save(update_fields=["revision"])
        second, provider, research = self.worker([parsed([observation("image_001", "unrelated", "other")])], research=False)
        provider.assert_called_once()
        research.assert_not_called()
        self.assertCountEqual([item["status"] for item in second.result["image_readings"]], ["reused", "completed"])
        self.assertEqual(second.result["blocking_reason"], "photo_relevance")
        self.assertEqual(second.application_result["reason"], "photo_relevance")
        self.assertEqual(self.machine.data, before)
        self.assert_blocked("no corresponden")
        bad.delete()
        self.machine.revision += 1
        self.machine.save(update_fields=["revision"])
        third, provider, _ = self.worker([], research=False)
        self.assertEqual(third.status, "completed")
        provider.assert_not_called()
        self.assertNotIn("blocking_reason", third.result)
        require_consistent_photos(self.machine)
        self.assertEqual(self.machine.data["description"], "Descripción del propietario")

"""Exact unit years satisfy readiness without inventing a model year interval."""
from copy import deepcopy
import json
import uuid

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from portal.ai_completion import missing_fields
from portal.intake import preparation_completeness
from portal.models import AnalysisJob, Category, Machine, PreparedShare, User


COMPLETE_DATA = {
    "brand": "Bobcat", "model": "S650", "serial": "ALJ816015",
    "estimate_min": 15000, "estimate_max": 45000, "estimate_currency": "USD",
    "description": (
        "Minicargador de ruedas para carga y movimiento de materiales.\n"
        "Brazos de elevación para trabajar con cucharón e implementos.\n"
        "Diseño compacto con dirección por deslizamiento."
    ),
}


class YearCompletenessTests(SimpleTestCase):
    def completion(self, data, result=None):
        machine = Machine(category_id=1, data=deepcopy(data))
        job = AnalysisJob(result={"completion": {}} if result is None else result)
        before = deepcopy(machine.data)
        result = preparation_completeness(machine, job)
        self.assertEqual(machine.data, before)
        return result

    def assert_year_ready(self, fields, ready):
        data = {**COMPLETE_DATA, **fields}
        generated = missing_fields(data, "Minicargadores")
        saved = self.completion(data)
        self.assertEqual("year_range" not in generated, ready)
        self.assertEqual("year_range" not in saved["missing_fields"], ready)
        if ready:
            self.assertEqual(saved["message"], "")

    def test_valid_exact_year_satisfies_generated_and_saved_completeness(self):
        for year in (1900, 2015, "2015", 2015.0, timezone.now().year + 1):
            with self.subTest(year=year):
                self.assert_year_ready({"year": year}, True)

    def test_invalid_exact_year_does_not_bypass_required_age_information(self):
        for year in (None, "", True, False, 0, 1899, timezone.now().year + 2,
                     2015.5, "2015–2016", "pendiente", "NaN", "Infinity", [], {}):
            with self.subTest(year=year):
                self.assert_year_ready({"year": year}, False)

    def test_complete_valid_range_still_satisfies_age_without_exact_year(self):
        for low, high in ((2010, 2020), (2015, 2015), (1900, timezone.now().year), ("2010", "2020")):
            with self.subTest(low=low, high=high):
                self.assert_year_ready({"estimated_year_from": low, "estimated_year_to": high}, True)

    def test_incomplete_or_invalid_ranges_do_not_mark_the_sheet_ready(self):
        for low, high in ((2010, None), (None, 2020), (2020, 2010), (1899, 2020),
                          (2010, timezone.now().year + 1), (True, 2020), (2010, False),
                          (2010.5, 2020), ("invalid", 2020)):
            with self.subTest(low=low, high=high):
                self.assert_year_ready({"estimated_year_from": low, "estimated_year_to": high}, False)

    def test_known_exact_year_needs_no_fabricated_or_partial_range(self):
        self.assert_year_ready({"year": 2015, "estimated_year_from": 2010}, True)
        self.assert_year_ready({"year": 2015, "estimated_year_from": 2020, "estimated_year_to": 2010}, True)

    def test_exact_year_does_not_hide_other_missing_fields(self):
        data = {**COMPLETE_DATA, "year": 2015}
        data.pop("estimate_max")
        self.assertEqual(missing_fields(data, "Minicargadores"), ["price_range"])
        self.assertEqual(self.completion(data)["missing_fields"], ["price_range"])

    def test_incomplete_sheet_exposes_safe_actionable_evidence_gaps(self):
        data = {"brand": "Bobcat", "model": "S650", "description": COMPLETE_DATA["description"]}
        saved = self.completion(data, {"completion": {}, "research": {"status": "completed"},
            "valuation": {"status": "insufficient", "diagnostics": {"accepted_comparable_count": 1}}})
        details = {item["field"]: item for item in saved["missing_details"]}
        self.assertEqual(details["year_range"]["code"], "documented_model_period_missing")
        self.assertEqual(details["price_range"]["code"], "second_comparable_missing")
        self.assertNotIn("S650", str(details))
        self.assertNotIn("estimado", " ".join(item["action"] for item in details.values()).casefold())

    def test_manual_ranges_remain_complete_even_when_a_prior_market_job_failed(self):
        data = {**COMPLETE_DATA, "estimated_year_from": 2010, "estimated_year_to": 2015,
                "estimate_min": "10000", "estimate_max": "20000", "estimate_currency": "USD"}
        saved = self.completion(data, {"completion": {}, "research": {"status": "degraded"},
            "valuation": {"status": "not_run", "reason": "budget_unavailable"}})
        self.assertEqual(saved, {"missing_fields": [], "message": ""})

    def test_historical_jobs_keep_their_existing_completion_contract(self):
        self.assertEqual(self.completion(COMPLETE_DATA, result={}), {})


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_URL="https://example.invalid", STORAGES={
    "default": {"BACKEND": "portal.storage.PrivateStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ExactYearPreparedSheetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="exact-year@example.invalid")
        category = Category.objects.create(name="Minicargadores", slug="year-completeness-skid-steer")
        self.machine = Machine.objects.create(owner=self.user, category=category, title="Bobcat S650",
            data={**COMPLETE_DATA, "year": 2015}, provenance={"year": {
                "source": "plate", "review": "clear", "component": "machine"}})
        self.job = AnalysisJob.objects.create(machine=self.machine, requested_by=self.user,
            revision=self.machine.revision, status="completed", mode="description", fingerprint=uuid.uuid4().hex,
            result={"completion": {"missing_fields": ["year_range"]}})
        self.client.force_login(self.user)

    def share(self):
        return self.client.post(f"/api/maquinarias/{self.machine.pk}/compartir/",
            json.dumps({"revision": self.machine.revision}), content_type="application/json")

    def test_saved_exact_year_clears_stale_job_warning_and_can_be_shared(self):
        state = self.client.get(f"/api/analisis/{self.job.pk}/")
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json()["completion"], {"missing_fields": [], "message": ""})
        preview = self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/")
        self.assertContains(preview, "2015")
        shared = self.share()
        self.assertEqual(shared.status_code, 200, shared.content)
        share = PreparedShare.objects.get(machine=self.machine)
        self.assertEqual(share.snapshot["data"]["year"], 2015)
        self.assertNotIn("estimated_year_from", share.snapshot["data"])
        self.assertNotIn("estimated_year_to", share.snapshot["data"])
        public = Client().get(f"/s/{share.code}/")
        self.assertContains(public, "2015")
        self.assertContains(public, "Rango de precio estimado")
        self.assertNotContains(public, "Rango de año estimado")
        self.assertNotContains(public, "ALJ816015")
        self.machine.refresh_from_db()
        self.assertNotIn("estimated_year_from", self.machine.data)
        self.assertNotIn("estimated_year_to", self.machine.data)

    def test_no_exact_year_or_range_still_blocks_new_share(self):
        self.machine.data.pop("year")
        self.machine.save(update_fields=["data"])
        response = self.share()
        self.assertEqual(response.status_code, 400)
        self.assertIn("rango de años", response.json()["error"])
        self.assertFalse(PreparedShare.objects.exists())

    def test_previous_price_context_and_fixed_note_survive_private_to_shared_html(self):
        from portal.ai_completion import PREVIOUS_PRICE_LABEL, PREVIOUS_PRICE_NOTE
        self.machine.data.update({
            "estimate_market": "Estados Unidos", "estimate_date": "2026-09-27",
            "estimate_basis": "PRIVATE-VALUATION-BASIS", "location_country": "México",
            "location_region": "Jalisco", "location_city": "Guadalajara", "hours": 0,
        })
        self.machine.provenance["estimate_min"] = {
            "source": "ai_reference", "label": PREVIOUS_PRICE_LABEL,
            "evidence": "PRIVATE-VALUATION-EVIDENCE",
        }
        self.machine.save(update_fields=["data", "provenance"])

        private = self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/")
        self.assertContains(private, PREVIOUS_PRICE_NOTE)
        shared = self.share()
        self.assertEqual(shared.status_code, 200, shared.content)
        share = PreparedShare.objects.get(machine=self.machine)
        self.assertEqual(share.snapshot["data"]["estimate_reference_note"], PREVIOUS_PRICE_NOTE)
        self.assertNotIn("PRIVATE-VALUATION", json.dumps(share.snapshot))
        public = Client().get(f"/s/{share.code}/")
        for response in (private, public):
            with self.subTest(public=response is public):
                for expected in (PREVIOUS_PRICE_NOTE, "Estados Unidos", "2026-09-27",
                                 "México", "Jalisco", "Guadalajara", "Horas de uso"):
                    self.assertContains(response, expected)
                for private_value in ("PRIVATE-VALUATION-BASIS", "PRIVATE-VALUATION-EVIDENCE"):
                    self.assertNotContains(response, private_value)
        self.assertEqual(public.context["data"]["hours"], 0)
        self.assertEqual(public.context["data"]["estimate_min"], 15000)
        self.assertEqual(public.context["data"]["estimate_max"], 45000)
        self.assertEqual(public.context["data"]["estimate_currency"], "USD")

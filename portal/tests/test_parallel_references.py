"""Independent lookups overlap without losing evidence, usage or cancellation."""
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from portal.analysis_parallel import ConcurrentReference
from portal.models import Asset, Category, Machine, PlatformSettings, User
from portal.processing import _can_spend_step, _independent_valuation_identity, enqueue_analysis, process_next_job
from portal.research import UsageTotals, empty_research, research_reservation
from portal.tests.test_ai_completion import IDENTITY, proposal
from portal.tests.test_image_relevance import field, observation, parsed
from portal.valuation import _empty, _seal, valuation_reservation


class ConcurrentReferenceTests(SimpleTestCase):
    def test_branch_starts_before_main_work_and_usage_is_accounted_only_once(self):
        entered, release = Event(), Event()

        def lookup(stopped):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Main work did not release the independent lookup")
            return {"status": "estimated"}, UsageTotals(13, 7, 3, 1)

        with patch("portal.analysis_parallel.connections.close_all") as close:
            branch = ConcurrentReference(lookup)
            try:
                self.assertTrue(entered.wait(2))
                usage = UsageTotals(11, 5, 2, 1)
                release.set()
                first = branch.settle(usage)
                self.assertEqual(first, {"status": "estimated"})
                self.assertEqual(branch.settle(usage), first)
                self.assertEqual(usage.as_dict(), dict(input_tokens=24, output_tokens=12,
                    estimated_tokens=5, web_search_calls=2))
            finally:
                release.set()
                branch.close()
            close.assert_called_once_with()

    def test_error_signals_cancellation_and_retains_consumption_once(self):
        failure = RuntimeError("Bounded lookup failed")
        failure.accounted_usage = UsageTotals(23, 9, 4, 1)

        def lookup(stopped):
            raise failure

        with patch("portal.analysis_parallel.connections.close_all") as close:
            branch = ConcurrentReference(lookup)
            usage = UsageTotals(7, 2)
            try:
                with self.assertRaisesRegex(RuntimeError, "Bounded lookup failed"):
                    branch.settle(usage)
                self.assertTrue(branch.stopped.is_set())
                self.assertIsNone(branch.settle(usage, raise_error=False))
                self.assertEqual(usage.as_dict(), dict(input_tokens=30, output_tokens=11,
                    estimated_tokens=4, web_search_calls=1))
            finally:
                branch.close()
            close.assert_called_once_with()

    def test_close_cancels_and_joins_the_branch_before_returning(self):
        entered, finished = Event(), Event()

        def lookup(stopped):
            entered.set()
            if not stopped.wait(2):
                raise AssertionError("Closing the helper did not cancel the lookup")
            finished.set()
            return {"status": "not_run"}, UsageTotals()

        with patch("portal.analysis_parallel.connections.close_all") as close:
            branch = ConcurrentReference(lookup)
            try:
                self.assertTrue(entered.wait(2))
            finally:
                branch.close()
            self.assertTrue(finished.is_set())
            self.assertEqual(branch.settle(UsageTotals()), {"status": "not_run"})
            close.assert_called_once_with()


class IndependentValuationIdentityTests(SimpleTestCase):
    def setUp(self):
        self.job = SimpleNamespace(mode="analysis")
        self.result = {"relevance": {"status": "relevant"},
            "data": {"brand": "Caterpillar", "model": "320D"},
            "provenance": {key: {"source": "image", "review": "clear", "component": "machine"}
                           for key in ("brand", "model")}}
        self.snapshot = {"data": {}, "provenance": {}}

    def eligible(self, result=None, snapshot=None):
        with patch("portal.processing.connection") as connection:
            connection.in_atomic_block = False
            return _independent_valuation_identity(self.job,
                result if result is not None else self.result,
                snapshot if snapshot is not None else self.snapshot)

    def test_clear_image_identity_can_start_with_the_exact_owner_context(self):
        snapshot = {"data": {"hours": 2400, "year": 2013, "condition": "used",
                             "location_country": "México"},
            "provenance": {key: {"source": "user"} for key in
                           ("hours", "year", "condition", "location_country")}}
        identity = self.eligible(snapshot=snapshot)
        self.assertEqual((identity["brand"], identity["model"]), ("Caterpillar", "320D"))
        self.assertEqual(identity["compatibility"], {"year": "2013", "hours": "2400"})
        self.assertEqual((identity["condition"], identity["market_hint"]), ("used", "MX"))

    def test_unclear_component_or_web_identity_waits_for_research(self):
        for change in ({"review": "needs_review"}, {"component": "engine"}, {"source": "web"}):
            with self.subTest(change=change):
                result = deepcopy(self.result)
                result["provenance"]["model"].update(change)
                self.assertIsNone(self.eligible(result=result))
        result = deepcopy(self.result)
        result["data"].pop("model")
        result["data"]["model_family"] = "320"
        self.assertIsNone(self.eligible(result=result))

    def test_serial_input_unreviewed_photos_and_description_mode_stay_sequential(self):
        for status in ("uncertain", "unrelated", "mixed", "unassessed"):
            with self.subTest(status=status):
                result = deepcopy(self.result)
                result["relevance"]["status"] = status
                self.assertIsNone(self.eligible(result=result))
        for source in ("result", "snapshot"):
            with self.subTest(source=source):
                result, snapshot = deepcopy(self.result), deepcopy(self.snapshot)
                (result if source == "result" else snapshot)["data"]["serial"] = "UNIT12345"
                self.assertIsNone(self.eligible(result=result, snapshot=snapshot))
        self.job.mode = "description"
        self.assertIsNone(self.eligible())

    def test_uncommitted_transaction_never_dispatches_a_second_connection(self):
        with patch("portal.processing.connection") as connection:
            connection.in_atomic_block = True
            self.assertIsNone(_independent_valuation_identity(self.job, self.result, self.snapshot))


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class ParallelReferencePipelineTests(TransactionTestCase):
    def setUp(self):
        category = Category.objects.create(name="Excavadoras", slug="excavadoras", active=True)
        self.owner = User.objects.create_user(email="parallel-reference@example.invalid")
        self.machine = Machine.objects.create(owner=self.owner, category=category)
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=500000)
        Asset.objects.create(machine=self.machine, kind="image", purpose="general", processing_status="ready",
            original="test/unused.jpg", preview="test/unused.jpg", size=1, mime_type="image/jpeg", sha256="a" * 64)

    def reading_response(self):
        reading = parsed([observation("image_001", category="Excavadoras")],
            [field("brand", "Caterpillar", "image_001"), field("model", "320D", "image_001")])
        return SimpleNamespace(status="completed", output_parsed=reading,
            usage=SimpleNamespace(input_tokens=180, output_tokens=90))

    def test_photo_validation_then_overlapping_lookups_keep_all_three_required_outputs(self):
        valuation_entered, research_entered = Event(), Event()
        reading = parsed([observation("image_001", category="Excavadoras")],
            [field("brand", "Caterpillar", "image_001"), field("model", "320D", "image_001")])

        def research(*args, **kwargs):
            if not valuation_entered.wait(2):
                raise AssertionError("Valuation did not overlap research")
            self.assertTrue(kwargs["allowed"]())
            research_entered.set()
            return empty_research("no_results"), UsageTotals(17, 8, 3, 1)

        def valuation(*args, **kwargs):
            valuation_entered.set()
            if not research_entered.wait(2):
                raise AssertionError("Research did not overlap valuation")
            self.assertTrue(kwargs["allowed"]())
            return _seal(_empty(IDENTITY, "No comparables")), UsageTotals(19, 6, 2, 1)

        with patch("openai.OpenAI") as provider, patch("portal.processing._image_input",
                return_value={"type": "input_image", "image_url": "data:test"}), \
                patch("portal.processing.research_machine", side_effect=research) as researched, \
                patch("portal.processing.estimate_machine", side_effect=valuation) as estimated:
            provider.return_value.responses.parse.side_effect = [
                SimpleNamespace(status="completed", output_parsed=reading,
                    usage=SimpleNamespace(input_tokens=180, output_tokens=90)),
                SimpleNamespace(status="completed", output_parsed=proposal(),
                    usage=SimpleNamespace(input_tokens=120, output_tokens=60))]
            job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True,
                auto_apply=True, expected_revision=self.machine.revision)
            self.assertTrue(process_next_job())
            researched.assert_called_once()
            estimated.assert_called_once()
            self.assertEqual(provider.return_value.responses.parse.call_count, 2)
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.result["execution"], {"references": "parallel"})
        self.assertEqual(job.result["relevance"]["status"], "relevant")
        self.assertEqual(job.result["completion"]["missing_fields"], [])
        self.assertEqual((self.machine.data["estimate_min"], self.machine.data["estimate_max"]), (45000, 90000))
        self.assertEqual((self.machine.data["estimated_year_from"], self.machine.data["estimated_year_to"]), (2006, 2015))
        self.assertEqual(len(self.machine.data["description"].splitlines()), 4)
        self.assertEqual(job.result["usage"], dict(input_tokens=336, output_tokens=164,
            estimated_tokens=5, web_search_calls=2))

    def test_changed_identity_discards_the_parallel_price_without_a_second_search(self):
        valuation_entered, research_finished = Event(), Event()

        def research(client, model, result, *args, **kwargs):
            if not valuation_entered.wait(2):
                raise AssertionError("Valuation did not start")
            # Defense in depth: a later identity correction must not attach
            # the already-requested price to a different model.
            result["data"]["model"] = "330D"
            research_finished.set()
            return empty_research("no_results"), UsageTotals()

        def valuation(client, model, result, *args, **kwargs):
            valuation_entered.set()
            if not research_finished.wait(2):
                raise AssertionError("Research did not finish")
            self.assertEqual(result["data"]["model"], "320D")
            value = _empty(IDENTITY, "Reference for the original model")
            value.update(status="estimated")
            value["fields"].update(estimate_min="40000", estimate_max="80000", estimate_currency="USD")
            return _seal(value), UsageTotals(19, 6)

        with patch("openai.OpenAI") as provider, patch("portal.processing._image_input",
                return_value={"type": "input_image", "image_url": "data:test"}), \
                patch("portal.processing.research_machine", side_effect=research), \
                patch("portal.processing.estimate_machine", side_effect=valuation) as estimated, \
                patch("portal.processing.complete_machine_reference", return_value=(None, UsageTotals())):
            provider.return_value.responses.parse.return_value = self.reading_response()
            job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True)
            self.assertTrue(process_next_job())
            estimated.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.result["valuation"], {"status": "not_run", "reason": "identity_changed"})
        self.assertNotIn("estimate_min", job.result["data"])
        self.assertEqual(job.input_tokens, 199)

    def test_research_failure_waits_for_the_other_branch_and_accounts_for_both(self):
        valuation_entered, fail_research = Event(), Event()
        failure = RuntimeError("Research interrupted after a measured response")
        failure.accounted_usage = UsageTotals(17, 8, 3, 1)

        def research(*args, **kwargs):
            if not valuation_entered.wait(2):
                raise AssertionError("Valuation did not start")
            fail_research.set()
            raise failure

        def valuation(*args, **kwargs):
            valuation_entered.set()
            if not fail_research.wait(2):
                raise AssertionError("Research did not reach its failure")
            return _seal(_empty(IDENTITY, "No comparables")), UsageTotals(19, 6, 2, 1)

        with patch("openai.OpenAI") as provider, patch("portal.processing._image_input",
                return_value={"type": "input_image", "image_url": "data:test"}), \
                patch("portal.processing.research_machine", side_effect=research), \
                patch("portal.processing.estimate_machine", side_effect=valuation) as estimated, \
                patch("portal.processing.complete_machine_reference") as completion:
            provider.return_value.responses.parse.return_value = self.reading_response()
            job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True)
            self.assertTrue(process_next_job())
            estimated.assert_called_once()
            completion.assert_not_called()
            provider.return_value.close.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual((job.input_tokens, job.output_tokens), (216, 104))

    def test_insufficient_joint_reservation_uses_each_lookup_once_sequentially(self):
        stages, budgets = [], []

        def budget(job, usage, cost):
            allowed = _can_spend_step(job, usage, cost)
            budgets.append((cost, allowed))
            return allowed

        def research(*args, **kwargs):
            stages.append("research")
            return empty_research("no_results"), UsageTotals(17, 8, 3, 1)

        def valuation(*args, **kwargs):
            self.assertEqual(stages, ["research"])
            stages.append("valuation")
            return _seal(_empty(IDENTITY, "No comparables")), UsageTotals(19, 6, 2, 1)

        # A larger-than-reserved vision response leaves room for either lookup
        # but not both reservations together. Cheap actual research then frees
        # enough headroom to run the original sequential valuation safely.
        reading = self.reading_response()
        reading.usage = SimpleNamespace(input_tokens=24000, output_tokens=1000)
        with patch("openai.OpenAI") as provider, patch("portal.processing._image_input",
                return_value={"type": "input_image", "image_url": "data:test"}), \
                patch("portal.processing._can_spend_step", side_effect=budget), \
                patch("portal.processing.ConcurrentReference") as parallel, \
                patch("portal.processing.research_machine", side_effect=research) as researched, \
                patch("portal.processing.estimate_machine", side_effect=valuation) as estimated:
            provider.return_value.responses.parse.side_effect = [reading,
                SimpleNamespace(status="completed", output_parsed=proposal(),
                    usage=SimpleNamespace(input_tokens=120, output_tokens=60))]
            job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True,
                auto_apply=True, expected_revision=self.machine.revision)
            self.assertTrue(process_next_job())
            parallel.assert_not_called()
            researched.assert_called_once()
            estimated.assert_called_once()
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(stages, ["research", "valuation"])
        self.assertIn((research_reservation(job.model) + valuation_reservation(job.model), False), budgets)
        self.assertIn((research_reservation(job.model), True), budgets)
        self.assertIn((valuation_reservation(job.model), True), budgets)
        self.assertNotIn("execution", job.result)
        self.assertEqual(job.result["completion"]["missing_fields"], [])
        self.assertEqual((self.machine.data["estimate_min"], self.machine.data["estimate_max"]), (45000, 90000))
        self.assertEqual((self.machine.data["estimated_year_from"], self.machine.data["estimated_year_to"]), (2006, 2015))
        self.assertEqual(len(self.machine.data["description"].splitlines()), 4)

    def test_valid_cached_valuation_starts_no_future_and_preserves_its_signed_range(self):
        cached = _empty(IDENTITY, "", status="conditional_reference")
        cached["fields"].update(estimate_min="52000.00", estimate_max="78000.00", estimate_currency="USD",
            estimate_date=timezone.localdate().isoformat(), estimate_market="Estados Unidos",
            estimate_basis="Rango de referencia obtenido de anuncios independientes del modelo.")
        cached = _seal(cached)
        with patch("openai.OpenAI") as provider, patch("portal.processing._image_input",
                return_value={"type": "input_image", "image_url": "data:test"}), \
                patch("portal.processing._cached_valuation", return_value=(cached, "previous-job")) as cache, \
                patch("portal.processing.ConcurrentReference") as parallel, \
                patch("portal.processing.research_machine",
                    return_value=(empty_research("no_results"), UsageTotals(17, 8, 3, 1))) as researched, \
                patch("portal.processing.estimate_machine") as estimated:
            provider.return_value.responses.parse.side_effect = [self.reading_response(),
                SimpleNamespace(status="completed", output_parsed=proposal(),
                    usage=SimpleNamespace(input_tokens=120, output_tokens=60))]
            job = enqueue_analysis(self.machine, self.owner, research=True, authorize_ai=True,
                auto_apply=True, expected_revision=self.machine.revision)
            self.assertTrue(process_next_job())
            cache.assert_called_once()
            parallel.assert_not_called()
            researched.assert_called_once()
            estimated.assert_not_called()
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.result["valuation"]["proof"], cached["proof"])
        self.assertEqual(job.result["valuation_reuse"], {
            "source_job_id": "previous-job", "reason": "same_day_signed_identity_match"})
        self.assertNotIn("execution", job.result)
        self.assertEqual(job.result["completion"]["missing_fields"], [])
        self.assertEqual((self.machine.data["estimate_min"], self.machine.data["estimate_max"]), (52000, 78000))
        self.assertEqual((self.machine.data["estimated_year_from"], self.machine.data["estimated_year_to"]), (2006, 2015))
        self.assertEqual(len(self.machine.data["description"].splitlines()), 4)
        self.assertEqual(job.result["usage"], dict(input_tokens=317, output_tokens=158,
            estimated_tokens=3, web_search_calls=1))

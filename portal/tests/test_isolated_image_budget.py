"""Admission and stale recovery cover every isolated image, without API calls."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from portal.models import AnalysisJob, Asset, Machine, PlatformSettings, User
from portal.processing import _claim_job, _job_lease_seconds, _reservation, enqueue_analysis
from portal.research import RESEARCH_RESERVATION
from portal.valuation import VALUATION_RESERVATION


IMAGE_COST = 12_200


@override_settings(OPENAI_API_KEY='test-only-no-network', OPENAI_MODEL='gpt-4.1-mini',
                   OPENAI_TIMEOUT=90, AI_JOB_STALE_SECONDS=300)
class IsolatedImageBudgetTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='isolated-budget@example.invalid')
        self.machine = Machine.objects.create(owner=self.owner)
        self.limits = PlatformSettings.objects.create(pk=1, ai_enabled=True,
            ai_daily_token_limit=2_000_000, ai_max_attempts=2)

    def assets(self, count):
        return [str(Asset.objects.create(machine=self.machine, kind='image', purpose='general',
            processing_status='ready', original='test/unused.jpg', preview='test/unused.jpg',
            size=1, mime_type='image/jpeg', sha256=f'{index:064x}', position=index).pk)
            for index in range(count)]

    def budget(self, value):
        self.limits.ai_daily_token_limit = value
        self.limits.save(update_fields=['ai_daily_token_limit'])

    def running(self, name, image_count, age, *, recorded_lease=None):
        cost = IMAGE_COST * image_count
        result = {'reservation_per_attempt': cost, 'attempt_limit': 2, 'research_requested': False}
        if recorded_lease is not None:
            result['execution_lease_seconds'] = recorded_lease
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint=name, mode='analysis',
            asset_ids=[f'synthetic-image-{index}' for index in range(image_count)],
            status='running', attempts=1, reserved_tokens=cost * 2,
            locked_at=timezone.now() - timedelta(seconds=age), result=result)

    def test_reservation_covers_each_full_extraction_and_only_one_research_pipeline(self):
        for count in (1, 2, 20):
            with self.subTest(count=count):
                self.assertEqual(_reservation(count, 'analysis'), count * IMAGE_COST)
                self.assertEqual(_reservation(count, 'analysis', True), count * IMAGE_COST + RESEARCH_RESERVATION + VALUATION_RESERVATION)
        self.assertEqual(_reservation(0, 'description'), 9000)
        self.assertEqual(_reservation(0, 'description', True, research_description_only=True), RESEARCH_RESERVATION)

    def test_exact_budget_admits_one_complete_attempt_without_raising_limits(self):
        self.assets(2)
        cost = 2 * IMAGE_COST + RESEARCH_RESERVATION + VALUATION_RESERVATION
        self.budget(cost)
        with patch('openai.OpenAI') as provider:
            job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=True)
        provider.assert_not_called()
        self.assertEqual((job.result['attempt_limit'], job.reserved_tokens), (1, cost))
        self.assertEqual(job.result['reservation_per_attempt'], cost)
        self.limits.refresh_from_db()
        self.assertEqual(self.limits.ai_daily_token_limit, cost)

    def test_one_token_short_rejects_before_any_image_or_provider_work(self):
        self.assets(2)
        self.budget(2 * IMAGE_COST + RESEARCH_RESERVATION + VALUATION_RESERVATION - 1)
        with patch('openai.OpenAI') as provider, patch('portal.processing._image_input') as image, self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=True)
        provider.assert_not_called()
        image.assert_not_called()
        self.assertFalse(AnalysisJob.objects.exists())

    def test_admission_counts_prior_consumption_and_other_active_reservations(self):
        self.assets(2)
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, fingerprint='already-used',
            revision=self.machine.revision, status='completed', input_tokens=3000, output_tokens=1000, finished_at=timezone.now())
        AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner, fingerprint='other-running',
            revision=self.machine.revision, status='running', reserved_tokens=10_000, attempts=1, locked_at=timezone.now())
        self.budget(2 * IMAGE_COST + 14_000 - 1)
        with self.assertRaises(ValidationError):
            enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.budget(2 * IMAGE_COST + 14_000)
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        self.assertEqual((job.reserved_tokens, job.result['attempt_limit']), (2 * IMAGE_COST, 1))

    def legacy(self):
        return AnalysisJob.objects.create(machine=self.machine, requested_by=self.owner,
            revision=self.machine.revision, fingerprint='pre-isolation', mode='analysis',
            asset_ids=['old-photo-a', 'old-photo-b'], status='queued', reserved_tokens=30_800,
            prompt_version='imc-vision-research-2026-09-v17',
            result={'reservation_per_attempt': 15_400, 'attempt_limit': 2, 'research_requested': False})

    def test_queued_legacy_reservation_is_upgraded_and_attempts_reduced_when_needed(self):
        job = self.legacy()
        self.budget(2 * IMAGE_COST)
        claimed = _claim_job()
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual((claimed.attempts, claimed.reserved_tokens), (1, 2 * IMAGE_COST))
        self.assertEqual(claimed.result['attempt_limit'], 1)
        self.assertEqual(claimed.result['reservation_per_attempt'], 2 * IMAGE_COST)
        self.assertEqual((claimed.input_tokens, claimed.output_tokens), (0, 0))

    def test_legacy_upgrade_without_one_full_attempt_fails_without_claiming(self):
        job = self.legacy()
        self.budget(2 * IMAGE_COST - 1)
        with patch('openai.OpenAI') as provider:
            self.assertIsNone(_claim_job())
        provider.assert_not_called()
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.reserved_tokens), ('failed', 0, 0))
        self.assertEqual((job.input_tokens, job.output_tokens), (0, 0))

    def test_twenty_image_job_is_not_reclaimed_at_the_old_ten_minute_boundary(self):
        job = self.running('long-active', 20, 601)
        original_lease = job.locked_at
        self.assertEqual(_job_lease_seconds(job), 600 + 19 * 90)
        self.assertIsNone(_claim_job())
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.input_tokens), ('running', 1, 0))
        self.assertEqual(job.locked_at, original_lease)

    def test_active_long_job_does_not_hide_an_expired_short_job(self):
        expired = self.running('expired-short', 1, 601)
        active = self.running('active-long', 20, 1000)
        # Active comes first both in default newest-created order and oldest
        # locked-at order. Recovery must inspect each job's own deadline.
        original_lease = active.locked_at
        claimed = _claim_job()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, expired.pk)
        self.assertEqual((claimed.attempts, claimed.input_tokens, claimed.reserved_tokens),
                         (2, IMAGE_COST, IMAGE_COST))
        active.refresh_from_db()
        self.assertEqual((active.status, active.attempts, active.input_tokens), ('running', 1, 0))
        self.assertEqual(active.locked_at, original_lease)

    def test_recorded_longer_lease_survives_a_shorter_runtime_configuration(self):
        job = self.running('recorded-lease', 1, 601, recorded_lease=1200)
        self.assertEqual(_job_lease_seconds(job), 1200)
        self.assertIsNone(_claim_job())
        AnalysisJob.objects.filter(pk=job.pk).update(locked_at=timezone.now() - timedelta(seconds=1201))
        claimed = _claim_job()
        self.assertEqual((claimed.pk, claimed.attempts, claimed.input_tokens), (job.pk, 2, IMAGE_COST))

    @override_settings(OPENAI_TIMEOUT=180)
    def test_lease_includes_every_configured_image_timeout_without_changing_description_path(self):
        multi = SimpleNamespace(mode='analysis', asset_ids=['a', 'b', 'c'], result={})
        description = SimpleNamespace(mode='description', asset_ids=[], result={})
        self.assertEqual(_job_lease_seconds(multi), 600 + 90 + 2 * 180)
        self.assertEqual(_job_lease_seconds(description), 600 + 90)

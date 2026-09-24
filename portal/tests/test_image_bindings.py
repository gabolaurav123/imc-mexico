"""Canonical request-local aliases prevent UUID authority and ordering drift."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from portal.models import Asset, Category, Machine, PlatformSettings, User
from portal.processing import (_bind_image_aliases, MachineAnalysis, enqueue_analysis,
                               normalize_analysis, process_analysis, process_next_job)
from portal.tests.test_image_relevance import field, observation, parsed


PLATE_ID = "00000000-0000-0000-0000-000000000001"
LIST_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
BINDINGS = [{"alias": "image_001", "asset_id": PLATE_ID},
            {"alias": "image_002", "asset_id": LIST_ID}]


class ImageAliasValidationTests(SimpleTestCase):
    def test_mapping_is_explicit_for_all_sections_without_mutating_provider(self):
        response = MachineAnalysis(title="Equipo", description="", category=None,
            fields=[field("brand", "EXAMPLE", "image_001")],
            plates=[dict(asset_id="image_001", component="machine", readability="clear", transcription="EXAMPLE")],
            image_observations=[dict(asset_id="image_001", kind="plate", relevance="related")], warnings=[], questions=[])
        mapped = _bind_image_aliases(response, BINDINGS)
        for section in (mapped.fields, mapped.plates, mapped.image_observations):
            self.assertEqual(section[0].asset_id, PLATE_ID)
        self.assertEqual(response.fields[0].asset_id, "image_001")
        self.assertIn("relevance", mapped.image_observations[0].model_fields_set)
        self.assertEqual(normalize_analysis(mapped, [PLATE_ID])["relevance"]["status"], "relevant")

    def test_new_provider_boundary_rejects_omitted_classification_while_direct_legacy_normalization_survives(self):
        for observations in (None, [{"asset_id": "image_001", "kind": "machine"}]):
            with self.subTest(observations=observations):
                data = dict(title="Legacy", description="", category=None,
                    fields=[field("brand", "EXAMPLE", "image_001")], plates=[], warnings=[], questions=[])
                if observations is not None:
                    data["image_observations"] = observations
                response = MachineAnalysis(**data)
                with self.assertRaises(ValidationError):
                    _bind_image_aliases(response, BINDINGS)
                self.assertEqual(normalize_analysis(response, ["image_001"])["relevance"]["status"], "unassessed")

    def test_unknown_aliases_and_even_real_uuid_passthrough_are_rejected_in_every_section(self):
        for invalid in (PLATE_ID, LIST_ID, "image_000", "image_003", "image_001-extra", "IMAGE_001"):
            for section in ("fields", "plates", "image_observations"):
                with self.subTest(invalid=invalid, section=section):
                    response = parsed([observation("image_001", "related", "plate")],
                        [field("brand", "EXAMPLE", "image_001")],
                        [dict(asset_id="image_001", component="machine", readability="clear", transcription="EXAMPLE")])
                    getattr(response, section)[0].asset_id = invalid
                    with self.assertRaises(ValidationError):
                        _bind_image_aliases(response, BINDINGS)
                    # Validation cannot partially rewrite the input model.
                    self.assertEqual(getattr(response, section)[0].asset_id, invalid)

    def test_contradictory_observations_fail_before_proposals_can_be_bound(self):
        for conflicting in (observation("image_001", "unrelated", "other"),
                            observation("image_001", "related", "plate", category="Different category")):
            with self.subTest(conflicting=conflicting):
                response = parsed([observation("image_001", "related", "plate"), conflicting],
                                  [field("brand", "EXAMPLE", "image_001")])
                with self.assertRaises(ValidationError):
                    _bind_image_aliases(response, BINDINGS)
                self.assertEqual(response.fields[0].asset_id, "image_001")


@override_settings(OPENAI_API_KEY="test-only-no-network", OPENAI_MODEL="gpt-4.1-mini")
class ImageMessageBindingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="image-binding@example.invalid")
        self.machine = Machine.objects.create(owner=self.owner, data={"brand": "Declared brand"},
            provenance={"brand": {"source": "user", "review": "confirmed", "asset_id": LIST_ID,
                                  "analysis_id": "OLD-JOB-PRIVATE", "evidence": "OLD PRIVATE EVIDENCE"}})
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=1000000)
        Category.objects.create(name="Montacargas", slug="montacargas")
        # The shopping list sorts first by display position and last by UUID.
        for pk, position, sha in ((PLATE_ID, 1, "a"), (LIST_ID, 0, "b")):
            Asset.objects.create(id=pk, machine=self.machine, kind="image", purpose="general",
                processing_status="ready", original="test/unused.jpg", preview="test/unused.jpg",
                size=1, mime_type="image/jpeg", sha256=sha * 64, position=position)

    @staticmethod
    def image_input(asset):
        return {"type": "input_image", "image_url": "data:plate-pixels" if str(asset.pk) == PLATE_ID else "data:shopping-pixels"}

    def provider_result(self, **kwargs):
        """A faithful stand-in reads each message, never a parallel UUID list."""
        messages = kwargs["input"]
        manifest = json.loads(messages[0]["content"][0]["text"])["image_manifest"]
        observations, fields, plates = [], [], []
        for index, message in enumerate(messages[1:]):
            alias = manifest[index]["asset_id"]
            self.assertEqual(manifest[index]["message_index"], index + 1)
            before, image, after = message["content"]
            self.assertIn(f"INICIO FOTO {alias}", before["text"])
            self.assertIn(f"FIN FOTO {alias}", after["text"])
            self.assertEqual(image["type"], "input_image")
            self.assertEqual(sum(item["type"] == "input_image" for item in message["content"]), 1)
            if image["image_url"] == "data:plate-pixels":
                observations.append(observation(alias, "related", "plate", category="Montacargas"))
                fields.extend([field("brand", "EXAMPLE", alias, "plate"),
                               field("model", "FORK20", alias, "plate"),
                               field("serial", "TESTSERIAL123", alias, "plate")])
                plates.append(dict(asset_id=alias, component="machine", readability="clear",
                                   transcription="EXAMPLE FORK20 SERIAL No. TESTSERIAL123"))
            else:
                observations.append(observation(alias, "unrelated", "other"))
        # Output order intentionally differs from input order. Alias identity,
        # never list position, determines the stored photo association.
        response = parsed(list(reversed(observations)), fields, plates)
        return SimpleNamespace(status="completed", output_parsed=response,
                               usage=SimpleNamespace(input_tokens=400, output_tokens=200))

    def test_display_order_cannot_change_alias_manifest_and_both_recorded_orders_bind_exact_photo(self):
        self.assertEqual(list(self.machine.assets.values_list("id", flat=True)),
                         [Asset.objects.get(pk=LIST_ID).pk, Asset.objects.get(pk=PLATE_ID).pk])
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        for order in ([PLATE_ID, LIST_ID], [LIST_ID, PLATE_ID]):
            with self.subTest(order=order):
                job.asset_ids = order
                job.save(update_fields=["asset_ids"])
                with patch("portal.processing._image_input", side_effect=self.image_input), patch("openai.OpenAI") as provider:
                    provider.return_value.responses.parse.side_effect = self.provider_result
                    result, usage = process_analysis(job)
                self.assertEqual(provider.return_value.responses.parse.call_count, 2)
                provider.return_value.responses.create.assert_not_called()
                calls = provider.return_value.responses.parse.call_args_list
                sent = [call.kwargs["input"] for call in calls]
                serialized = json.dumps(sent)
                for internal in (PLATE_ID, LIST_ID, "OLD-JOB-PRIVATE", "OLD PRIVATE EVIDENCE"):
                    self.assertNotIn(internal, serialized)
                expected_pixels = ["data:plate-pixels" if pk == PLATE_ID else "data:shopping-pixels" for pk in order]
                self.assertEqual([request[1]["content"][1]["image_url"] for request in sent], expected_pixels)
                self.assertTrue(all(len(request) == 2 for request in sent))
                self.assertEqual(result["input_image_bindings"],
                                 [{"alias": "image_001", "asset_id": pk, "sequence": index} for index, pk in enumerate(order, 1)])
                self.assertEqual(result["relevance"]["accepted_asset_ids"], [PLATE_ID])
                self.assertEqual(result["relevance"]["excluded_asset_ids"], [LIST_ID])
                self.assertEqual(result["data"]["serial"], "TESTSERIAL123")
                self.assertTrue(all(item["asset_id"] == PLATE_ID for item in result["fields"] + result["plates"]))
                self.assertEqual(result["provenance"]["serial"]["asset_id"], PLATE_ID)
                self.assertEqual((usage.input_tokens, usage.output_tokens), (800, 400))
                self.assertEqual(job.result["reservation_per_attempt"], 2 * 12200)

    def test_declared_plate_runs_first_without_changing_recorded_gallery_order(self):
        Asset.objects.filter(pk=PLATE_ID).update(purpose='plate')
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        job.asset_ids = [LIST_ID, PLATE_ID]
        job.save(update_fields=['asset_ids'])
        with patch('portal.processing._image_input', side_effect=self.image_input), patch('openai.OpenAI') as provider:
            provider.return_value.responses.parse.side_effect = self.provider_result
            result, _ = process_analysis(job)
        sent = [call.kwargs['input'][1]['content'][1]['image_url']
                for call in provider.return_value.responses.parse.call_args_list]
        self.assertEqual(sent, ['data:plate-pixels', 'data:shopping-pixels'])
        self.assertEqual(result['input_image_bindings'], [
            {'alias': 'image_001', 'asset_id': LIST_ID, 'sequence': 1},
            {'alias': 'image_001', 'asset_id': PLATE_ID, 'sequence': 2},
        ])

    def test_invalid_binding_is_accounted_as_failed_without_search_or_draft_mutation(self):
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True, research=True,
                               auto_apply=True, expected_revision=self.machine.revision)
        response = parsed([observation(PLATE_ID, "related", "plate")], [field("brand", "Wrong", PLATE_ID)])
        with patch("portal.processing._image_input", side_effect=self.image_input), patch("openai.OpenAI") as provider, \
             patch("portal.processing.research_machine") as research:
            provider.return_value.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=response,
                usage=SimpleNamespace(input_tokens=450, output_tokens=100))
            self.assertTrue(process_next_job())
        research.assert_not_called()
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual((job.status, job.input_tokens, job.output_tokens, job.reserved_tokens), ("failed", 450, 100, 0))
        self.assertEqual(self.machine.data["brand"], "Declared brand")
        self.assertNotIn("data", job.result)

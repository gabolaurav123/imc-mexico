"""Offline regression for a possible suffix lost while reading a plate."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.core import signing
from django.test import SimpleTestCase

from portal.research import (
    SIGNING_SALT, ResearchCandidate, ResearchCandidates, _manifest, research_machine,
)


SERIAL = "A2EC262313"
PLATE_MODEL = "2EC2"
CANDIDATE = "2EC25"
DEALER = "https://www.example.com/listings/caterpillar-2ec25"
MAKER = "https://www.catlifttruck.com/support/legacy-2ec25"
CATALOG = "https://www.machinetools.com/models/caterpillar-2ec25"


def response(url, title, text):
    return SimpleNamespace(
        status="completed", output_text=f"{text} [Fuente]({url})",
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        output=[
            {"type": "web_search_call", "status": "completed",
             "action": {"type": "search", "sources": [{"url": url, "title": title}]}},
            {"type": "message", "content": [{"text": f"{text} [Fuente]({url})", "annotations": []}]},
        ],
    )


def plate_snapshot():
    return {
        "data": {"brand": "Caterpillar", "model": PLATE_MODEL, "serial": SERIAL},
        "provenance": {key: {"source": "user", "review": "confirmed"}
                       for key in ("brand", "model", "serial", "category")},
        "category": "Montacargas",
    }


class SerialModelExtensionResearchTests(SimpleTestCase):
    def test_serial_bound_suffix_is_only_a_supported_review_hypothesis(self):
        client = Mock()
        client.responses.create.side_effect = [
            response(DEALER, "Caterpillar 2EC25 forklift listing",
                     f"Caterpillar forklift model {CANDIDATE}; serial number {SERIAL}."),
            response(MAKER, "Cat Lift Trucks 2EC25 documentation",
                     f"Caterpillar {CANDIDATE} forklift technical documentation."),
            response(CATALOG, "Caterpillar 2EC25 specifications",
                     f"Caterpillar {CANDIDATE} forklift specifications."),
        ]
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed=ResearchCandidates(fields=[
                # These source values are intentionally richer than the plate
                # reading. They must not enter data, fields, years or value.
                ResearchCandidate(key="capacity", value="4,500 lb", scope="model", passage_index=1,
                                  matched_serial=None, matched_brand="Caterpillar", matched_model=CANDIDATE),
                ResearchCandidate(key="weight", value="5,000 lb", scope="model", passage_index=2,
                                  matched_serial=None, matched_brand="Caterpillar", matched_model=CANDIDATE),
                ResearchCandidate(key="year", value="2016", scope="exact_serial", passage_index=0,
                                  matched_serial=SERIAL, matched_brand="Caterpillar", matched_model=CANDIDATE),
            ]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )

        research, _ = research_machine(client, "gpt-5.6-luna", {"data": {}, "provenance": {}},
                                       plate_snapshot(), allowed_categories=["Montacargas"])

        self.assertEqual(research["status"], "no_results")
        self.assertEqual(research["fields"], [])
        self.assertEqual(len(research["hypotheses"]), 1)
        hypothesis = research["hypotheses"][0]
        self.assertEqual(hypothesis["model"], CANDIDATE)
        self.assertEqual(hypothesis["confidence"], "supported")
        self.assertEqual(hypothesis["support_count"], 3)
        self.assertEqual(hypothesis["relation"], "serial_model_extension")
        self.assertIn("año ni precio", research["warnings"][-1])
        self.assertEqual(client.responses.create.call_count, 3)
        self.assertEqual(client.responses.parse.call_count, 1)
        maker_payload = json.loads(client.responses.create.call_args_list[1].kwargs["input"])
        self.assertIn(CANDIDATE, maker_payload["query"])
        self.assertEqual(maker_payload["candidate_models_for_review"], [CANDIDATE])
        self.assertEqual(signing.Signer(salt=SIGNING_SALT).unsign_object(research["proof"]), _manifest(research))

    def test_single_listing_cannot_become_supported_or_replace_plate_model(self):
        client = Mock()
        client.responses.create.side_effect = [
            response(DEALER, "Caterpillar 2EC25 forklift listing",
                     f"Caterpillar forklift model {CANDIDATE}; serial number {SERIAL}."),
            response(MAKER, "Cat Lift Trucks service", "Service information for historic forklifts."),
            response(CATALOG, "Forklift catalogue", "Catalogued forklift families."),
        ]
        client.responses.parse.return_value = SimpleNamespace(
            status="completed", output_parsed=ResearchCandidates(fields=[]),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )

        research, _ = research_machine(client, "gpt-5.6-luna", {"data": {}, "provenance": {}},
                                       plate_snapshot(), allowed_categories=["Montacargas"])

        self.assertEqual(research["identity"]["model"], PLATE_MODEL)
        self.assertEqual(research["fields"], [])
        self.assertEqual(research["hypotheses"][0]["confidence"], "lead")
        self.assertEqual(research["hypotheses"][0]["support_count"], 1)

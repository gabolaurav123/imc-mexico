"""An actual unit reference beats general model data, without guessing origin."""
from django.test import SimpleTestCase

from portal.research import ResearchField, normalize_direct_fields


IDENTITY = {"brand": "Caterpillar", "model": "2EC25", "serial": "TEST262313"}
URL = "https://www.smithmachinery.com/listing/cat-2ec25/"
HEADING = "1 - PREOWNED CAT FORKLIFT 5000LBS, MODEL #: 2EC25, S/N: TEST262313"


def field(value="5000 LBS", **changes):
    data = dict(key="capacity", value=value, scope="exact_serial", source_url=URL,
                evidence=HEADING + " | CAPACITY: " + value, matched_brand="Caterpillar",
                matched_model="2EC25", matched_serial="TEST262313")
    return ResearchField(**{**data, **changes})


def normalize(fields):
    sources = list({f.source_url: {"url": f.source_url, "title": "Caterpillar 2EC25 specifications"}
                    for f in fields}.values())
    passages = [{"source_url": f.source_url, "text": f.evidence} for f in fields]
    return normalize_direct_fields(IDENTITY, "exact_serial", sources,
        "\n\n".join(f.evidence for f in fields), passages, direct_fields=fields)


class ForkliftResearchScopeTests(SimpleTestCase):
    def test_literal_document_can_identify_the_same_serial(self):
        result = normalize([field()])
        self.assertEqual(result["match"], "exact_serial")
        self.assertEqual(result["fields"][0]["value"], "5000 LBS")

    def test_wrong_missing_or_denied_serial_never_becomes_a_model_reference(self):
        for evidence in [HEADING.replace("TEST262313", "TEST999999") + " CAPACITY: 5000 LBS",
                         "Caterpillar 2EC25 CAPACITY: 5000 LBS",
                         "No record for serial TEST262313. Caterpillar 2EC25 capacity: 5000 LBS"]:
            with self.subTest(evidence=evidence):
                self.assertEqual(normalize([field(evidence=evidence)])["fields"], [])

    def test_exact_unit_wins_regardless_of_input_order(self):
        model = field("4800 LBS", scope="model", matched_serial=None,
                      evidence="Caterpillar 2EC25 capacity: 4800 LBS")
        for fields in [[model, field()], [field(), model]]:
            result = normalize(fields)
            self.assertEqual(result["fields"][0]["value"], "5000 LBS")
            self.assertEqual(result["fields"][0]["scope"], "exact_serial")

    def test_disagreement_between_exact_unit_sources_still_blocks(self):
        result = normalize([field(), field("6000 LBS", source_url="https://example.com/specs")])
        self.assertEqual(result["fields"], [])

    def test_model_conflicts_do_not_veto_a_later_matching_unit_reference(self):
        models = [field(value, scope="model", matched_serial=None,
                        evidence="Caterpillar 2EC25 capacity: " + value) for value in ["4800 LBS", "4500 LBS"]]
        self.assertEqual(normalize([*models, field()])["fields"][0]["value"], "5000 LBS")

    def test_manufacturer_address_is_separate_from_origin_and_seller_year_is_not_authoritative(self):
        address = field("HOUSTON, USA", key="manufacturer_address",
                        evidence=HEADING + " Manufacturer address: HOUSTON, USA")
        result = normalize([address, address.model_copy(update={"key": "country_of_origin", "value": "USA"}),
                            field("2020", key="year", evidence=HEADING + " YEAR: 2020")])
        self.assertEqual([f["key"] for f in result["fields"]], ["manufacturer_address"])

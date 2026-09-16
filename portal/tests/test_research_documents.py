from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research import ResearchField, research_machine, is_validated_web_field, merge_research
from portal.research_documents import collect_document_fields
from portal.tests.test_research import vision, web_response
from portal.tests.test_research_stages import extraction


URL = "https://www.ritchiespecs.com/model/caterpillar-420f2"
TITLE = "Caterpillar 420F2 Loader Backhoe"
IDENTITY = {"brand": "Caterpillar", "model": "420F2", "serial": None}


def document(url=URL):
    return {"status": "matched", "title": TITLE, "fields": [ResearchField(
        key="weight", value="8400 kg", scope="model", source_url=url,
        evidence="Operating Weight: 8400 kg", matched_brand="Caterpillar",
        matched_model="420F2", matched_serial=None)]}


class DocumentResearchTests(SimpleTestCase):
    def test_uncited_retrieved_table_supplies_signed_data_without_extra_ai(self):
        client = Mock()
        client.responses.create.side_effect = [web_response(sources=[]),
            web_response(sources=[{"url": URL, "title": TITLE}]), web_response(sources=[])]
        with patch("portal.research_documents.fetch_catalog_html", return_value=SimpleNamespace(html="table", final_url=URL)), \
                patch("portal.research_documents.parse_catalog_html", return_value=document()):
            research, usage = research_machine(client, "gpt-4.1-mini", vision())
        client.responses.parse.assert_not_called()
        self.assertEqual(research["fields"][0]["value"], "8400 kg")
        self.assertEqual(research["diagnostics"]["direct_candidate_count"], 1)
        self.assertEqual(usage.web_search_calls, 3)
        merged = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, research)
        self.assertTrue(is_validated_web_field(merged, "weight", "8400 kg", merged["provenance"]["weight"]))

    def test_public_rows_survive_summary_normalizer_failure(self):
        from portal.tests.test_research_stages import response
        client = Mock()
        client.responses.create.side_effect = [response("Caterpillar 420F2: potencia 70 kW."),
            web_response(sources=[{"url": URL, "title": TITLE}]), web_response(sources=[])]
        client.responses.parse.side_effect = TimeoutError("secret")
        with patch("portal.research_documents.fetch_catalog_html", return_value=SimpleNamespace(html="table", final_url=URL)), \
                patch("portal.research_documents.parse_catalog_html", return_value=document()):
            research, _ = research_machine(client, "gpt-4.1-mini", vision())
        self.assertEqual(research["fields"][0]["key"], "weight")
        self.assertFalse(research["diagnostics"]["search_complete"])
        self.assertNotIn("secret", str(research))

    def test_cancellation_after_download_discards_document_and_stops(self):
        with patch("portal.research_documents.fetch_catalog_html", return_value=SimpleNamespace(html="table", final_url=URL)), \
                patch("portal.research_documents.parse_catalog_html") as parse:
            fields, attempts, cancelled = collect_document_fields(
                IDENTITY, [{"url": URL, "title": TITLE}], [], [], {}, Mock(side_effect=[True, False]))
        self.assertTrue(cancelled)
        self.assertEqual(fields, [])
        parse.assert_not_called()

    def test_maximum_two_documents_and_passage_limits(self):
        sources = [{"url": URL + str(i), "title": TITLE} for i in range(8)]
        passages = [{"passage_index": i, "source_url": "https://www.cat.com/specs", "text": "x" * 800}
                    for i in range(36)]
        def fetched(url, **kwargs):
            return SimpleNamespace(html="table", final_url=url)
        def parsed(html, url, identity):
            return document(url)
        with patch("portal.research_documents.fetch_catalog_html", side_effect=fetched) as fetch, \
                patch("portal.research_documents.parse_catalog_html", side_effect=parsed):
            fields, attempts, cancelled = collect_document_fields(IDENTITY, sources, [], passages, {})
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(fields), 2)
        self.assertLessEqual(len(passages), 36)
        self.assertLessEqual(sum(len(p["text"]) for p in passages), 18000)
        self.assertEqual([p["passage_index"] for p in passages], list(range(len(passages))))

    def test_missing_identity_never_triggers_document_reads(self):
        with patch("portal.research_documents.fetch_catalog_html") as fetch:
            result = collect_document_fields({"brand": "Caterpillar", "model": None},
                [{"url": URL, "title": TITLE}], [], [], {})
        self.assertEqual(result, ([], [], False))
        fetch.assert_not_called()

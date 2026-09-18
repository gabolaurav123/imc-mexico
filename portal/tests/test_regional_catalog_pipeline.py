from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research import ResearchCandidates, is_validated_web_field, merge_research, research_machine
from portal.tests.test_research_regional_catalog import INDEX, INDEX_URL, PRODUCT, PRODUCT_URL


IDENTITY_RESULT = {
    "data": {"brand": "DEVELON", "model": "DX300LC-7"},
    "provenance": {
        "brand": {"source": "image", "review": "clear", "component": "machine"},
        "model": {"source": "image", "review": "clear", "component": "machine"},
    },
    "category": "Excavadoras", "fields": [], "warnings": [],
}


def empty_search_response(url=None):
    sources = [] if not url else [{"url": url, "title": "DEVELON DX300LC-7 manual"}]
    text = "DEVELON DX300LC-7 guía general de excavadora." if url else ""
    cited = text + (f" [Ficha]({url})" if url else "")
    output = [{"type": "web_search_call", "status": "completed",
               "action": {"type": "search", "sources": sources}}]
    if url:
        output.append({"type": "message", "content": [{"text": cited, "annotations": [{
            "type": "url_citation", "url": url, "title": "DEVELON DX300LC-7 manual",
            "start_index": len(text) + 1, "end_index": len(cited),
        }]}]})
    return SimpleNamespace(status="completed", output_text=cited,
                           usage=SimpleNamespace(input_tokens=0, output_tokens=0), output=output)


class RegionalCatalogPipelineTests(SimpleTestCase):
    def fetch_listing(self, url, retrieved_urls, deadline):
        if url == INDEX_URL:
            return SimpleNamespace(html=INDEX, final_url=INDEX_URL)
        if url == PRODUCT_URL:
            return SimpleNamespace(html=PRODUCT, final_url=PRODUCT_URL)
        raise AssertionError(url)

    def test_exact_model_gets_four_signed_model_fields_without_extra_parser_call(self):
        client = Mock()
        client.responses.create.return_value = empty_search_response()
        client.responses.parse.return_value = SimpleNamespace(
            status="completed", output_parsed=ResearchCandidates(fields=[]),
            usage=SimpleNamespace(input_tokens=0, output_tokens=0),
        )
        with patch("portal.valuation._fetch_listing", side_effect=self.fetch_listing) as fetch:
            research, usage = research_machine(
                client, "gpt-5.6-luna", IDENTITY_RESULT,
                allowed_categories=["Excavadoras"],
            )

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(research["fields"]), 6)
        self.assertEqual({field["key"] for field in research["fields"]},
                         {"weight", "capacity", "power", "engine", "digging_depth", "hydraulic_system"})
        self.assertEqual({field["scope"] for field in research["fields"]}, {"model"})
        self.assertEqual({field["source_url"] for field in research["fields"]}, {PRODUCT_URL})
        self.assertTrue(research.get("proof"))
        merged = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, research)
        for field in research["fields"]:
            meta = merged["provenance"][field["key"]]
            self.assertTrue(is_validated_web_field(merged, field["key"], field["value"], meta))
        self.assertEqual(usage.web_search_calls, 3)
        client.responses.parse.assert_not_called()

    def test_missing_model_never_reads_regional_product_catalog(self):
        client = Mock()
        client.responses.create.return_value = empty_search_response()
        no_model = {**IDENTITY_RESULT,
                    "data": {"brand": "DEVELON"},
                    "provenance": {"brand": IDENTITY_RESULT["provenance"]["brand"]}}
        with patch("portal.research._direct_catalog_context", return_value=None), \
                patch("portal.valuation._fetch_listing", side_effect=self.fetch_listing) as fetch:
            research_machine(client, "gpt-5.6-luna", no_model, allowed_categories=["Excavadoras"])
        self.assertEqual(fetch.call_count, 0)

    def test_cancellation_after_regional_reads_drops_fields(self):
        client = Mock()
        allowed = Mock(side_effect=[True, True, False])
        with patch("portal.valuation._fetch_listing", side_effect=self.fetch_listing):
            research, usage = research_machine(
                client, "gpt-5.6-luna", IDENTITY_RESULT,
                allowed=allowed, allowed_categories=["Excavadoras"],
            )
        self.assertEqual(research["fields"], [])
        self.assertEqual(research["status"], "degraded")
        client.responses.create.assert_not_called()
        self.assertEqual(usage.web_search_calls, 0)

    def test_other_document_does_not_displace_regional_direct_fields(self):
        client = Mock()
        web_url = "https://eu.develon-ce.com/en/products/crawler-excavators"
        client.responses.create.return_value = empty_search_response(web_url)
        client.responses.parse.return_value = SimpleNamespace(
            status="completed", output_parsed=ResearchCandidates(fields=[]),
            usage=SimpleNamespace(input_tokens=0, output_tokens=0),
        )
        with patch("portal.valuation._fetch_listing", side_effect=self.fetch_listing):
            research, _ = research_machine(
                client, "gpt-5.6-luna", IDENTITY_RESULT,
                allowed_categories=["Excavadoras"],
            )
        self.assertEqual(len(research["fields"]), 6)
        self.assertEqual({field["source_url"] for field in research["fields"]}, {PRODUCT_URL})

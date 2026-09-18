from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from portal.research_catalog import catalog_listing_candidates


URL = "https://eu.develon-ce.com/en/products/crawler-excavators"
FINAL_URL = URL
HTML = """
<!doctype html><html><head><title>Crawler Excavators | Develon Europe</title>
<script>DX999 must not become a model</script></head><body>
<nav><a href='/machines/dx999'>DX999</a></nav>
<h1>Crawler Excavators</h1>
<h2>DX999</h2><h2>Top 10 Features</h2>
<div class='list__headline'><h2>Series 2025</h2></div>
<div class='list__item'><div class='list__headline'><h2>DX140LC-7K</h2>
<a href='https://eu.develon-ce.com/en/machines/dx140lc-7k'>Details</a></div></div>
<div class='list__item'><div class='list__headline'><h2>DX225LC-7X</h2>
<a href='/en/machines/dx225lc-7x'>DX225LC-7X</a></div></div>
<div class='list__item'><div class='list__headline'><h2>DX225LC-7 SLR</h2></div></div>
<footer><h2>DX888</h2></footer>
</body></html>
"""


class ResearchCatalogTests(SimpleTestCase):
    def identity(self, **changes):
        value = {"brand": "DEVELON", "model": None, "category": "Excavadoras"}
        value.update(changes)
        return value

    def fetcher(self, html=HTML, final_url=FINAL_URL):
        calls = []

        def fetch(url, retrieved_urls, deadline):
            calls.append((url, list(retrieved_urls), deadline))
            return SimpleNamespace(html=html, final_url=final_url)

        fetch.calls = calls
        return fetch

    def test_reads_visible_product_headings_and_pins_same_domain_anchor(self):
        fetch = self.fetcher()
        candidates = catalog_listing_candidates(self.identity(), "Excavadoras", fetcher=fetch)

        self.assertEqual([item["model"] for item in candidates], ["DX140LC-7K", "DX225LC-7X", "DX225LC-7 SLR"])
        self.assertEqual(candidates[0]["source_url"], URL)
        self.assertEqual(candidates[0]["source_title"], "Crawler Excavators | Develon Europe")
        self.assertEqual(candidates[0]["anchor_url"], "https://eu.develon-ce.com/en/machines/dx140lc-7k")
        self.assertEqual(candidates[0]["confidence"], "lead")
        self.assertIn("Crawler Excavators", candidates[0]["evidence"])
        self.assertEqual(len(fetch.calls), 1)

    def test_registry_does_not_fetch_for_unknown_brand_or_non_supported_category(self):
        fetch = self.fetcher()
        self.assertEqual(catalog_listing_candidates(self.identity(brand="DEVELON 999"), "Excavadoras", fetcher=fetch), [])
        self.assertEqual(catalog_listing_candidates(self.identity(), "Retroexcavadoras", fetcher=fetch), [])
        self.assertEqual(fetch.calls, [])

    def test_redirect_to_unverified_homonym_is_rejected(self):
        fetch = self.fetcher(final_url="https://www.develon.com/en/the-group/")
        self.assertEqual(catalog_listing_candidates(self.identity(), "Excavadoras", fetcher=fetch), [])

    def test_model_identity_is_required_and_input_model_skips_fallback(self):
        fetch = self.fetcher()
        self.assertEqual(catalog_listing_candidates(self.identity(model="DX140LC-7K"), "Excavadoras", fetcher=fetch), [])
        self.assertEqual(catalog_listing_candidates(self.identity(), "Excavadoras", fetcher=fetch, deadline=0), [])

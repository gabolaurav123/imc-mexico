from types import SimpleNamespace

from django.test import SimpleTestCase

from portal.research_catalog import catalog_product_fields


INDEX_URL = "https://develon-ce.cl/product-category/excavadoras-sobre-orugas/"
PRODUCT_URL = "https://develon-ce.cl/product/excavadora-sobre-orugas-dx300lc-7-develon/"

INDEX = """
<html><head><title>Excavadoras sobre Orugas archivos - Hyundai Develon Chile</title></head>
<body><h2>Excavadoras sobre Orugas</h2>
<div class='product'><h3><a href='/product/excavadora-sobre-orugas-dx300lc-7-develon/'>
Excavadora Sobre Orugas DX300LC-7</a></h3></div>
<div class='product'><a href='/product/excavadora-sobre-orugas-dx255lc-7/'>DX255LC-7</a></div>
<div aria-hidden='true'><div><a href='/product/dx888/'>DX888</a></div></div>
<script><a href='/product/dx999/'>DX999</a></script></body></html>
"""

PRODUCT = """
<html><head><title>Excavadora Sobre Orugas DX300LC-7 - Hyundai Develon Chile</title></head>
<body><h2>Excavadora Sobre Orugas DX300LC-7</h2>
<table><tr><th>Peso Operativo</th><td>31.5 t</td></tr>
<tr><th>Capacidad del Balde</th><td>1.60 m3</td></tr>
<tr><th>Potencia del Motor</th><td>266.9 hp @ 1,900 rpm</td></tr>
<tr><th>Motor</th><td>DEVELON DL08 (6 cilindros)</td></tr>
<tr><th>Ubicación del distribuidor</th><td>Santiago</td></tr></table>
</body></html>
"""


class RegionalCatalogTests(SimpleTestCase):
    identity = {"brand": "DEVELON", "model": None, "category": "Excavadoras"}

    def fetcher(self, index=INDEX, product=PRODUCT):
        calls = []

        def fetch(url, retrieved_urls, deadline):
            calls.append(url)
            if url == INDEX_URL:
                return SimpleNamespace(html=index, final_url=INDEX_URL)
            if url == PRODUCT_URL:
                return SimpleNamespace(html=product, final_url=PRODUCT_URL)
            return SimpleNamespace(html="", final_url=url)

        fetch.calls = calls
        return fetch

    def test_clear_model_hint_follows_one_same_domain_link_and_reads_literal_rows(self):
        fetch = self.fetcher()
        result = catalog_product_fields(self.identity, "DX300LC-7", fetcher=fetch)

        self.assertIsNotNone(result)
        self.assertEqual(fetch.calls, [INDEX_URL, PRODUCT_URL])
        self.assertEqual(result["model"], "DX300LC-7")
        self.assertEqual(result["source_url"], PRODUCT_URL)
        fields = {field.key: field for field in result["fields"]}
        self.assertEqual(fields["weight"].value, "31.5 t")
        self.assertEqual(fields["power"].value, "266.9 hp @ 1,900 rpm")
        self.assertNotIn("distribuidor", fields)
        self.assertTrue(all(field.scope == "model" for field in result["fields"]))

    def test_no_photo_model_hint_never_selects_a_catalogue_model(self):
        fetch = self.fetcher()
        self.assertIsNone(catalog_product_fields(self.identity, None, fetcher=fetch))
        self.assertEqual(fetch.calls, [])

    def test_comparison_title_cannot_bind_rows_to_one_of_two_models(self):
        fetch = self.fetcher(product=PRODUCT.replace('DX300LC-7 - Hyundai', 'DX300LC-7 vs DX255LC-7 - Hyundai'))
        self.assertIsNone(catalog_product_fields(self.identity, 'DX300LC-7', fetcher=fetch))

    def test_wrong_page_model_or_unverified_redirect_is_rejected(self):
        fetch = self.fetcher(product=PRODUCT.replace("DX300LC-7", "DX255LC-7"))
        self.assertIsNone(catalog_product_fields(self.identity, "DX300LC-7", fetcher=fetch))

        related = PRODUCT.replace(
            "</body>",
            "<h2>Related Products</h2><h3>DX300LC-7</h3></body>",
        ).replace("DX300LC-7 - Hyundai", "DX255LC-7 - Hyundai").replace(
            "Orugas DX300LC-7</h2>", "Orugas DX255LC-7</h2>"
        )
        fetch = self.fetcher(product=related)
        self.assertIsNone(catalog_product_fields(self.identity, "DX300LC-7", fetcher=fetch))

        fetch = self.fetcher()

        def redirected(url, retrieved_urls, deadline):
            response = fetch(url, retrieved_urls, deadline)
            if url == PRODUCT_URL:
                response.final_url = "https://develon.com/product/dx300lc-7/"
            return response

        self.assertIsNone(catalog_product_fields(self.identity, "DX300LC-7", fetcher=redirected))

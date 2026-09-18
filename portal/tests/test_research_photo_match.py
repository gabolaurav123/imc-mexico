from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from portal.research_fetch import CatalogFetchError
from portal.research_photo_match import MAX_IMAGES, _fetch_image, match_catalog_photo


INDEX_URL = "https://develon-ce.cl/product-category/excavadoras-sobre-orugas/"
P300 = "https://develon-ce.cl/product/excavadora-sobre-orugas-dx300lc-7-develon/"
P255 = "https://develon-ce.cl/product/excavadora-sobre-orugas-dx255lc-7/"
I300 = "https://develon-ce.cl/wp-content/uploads/dx300.png"
I255 = "https://develon-ce.cl/wp-content/uploads/dx255.png"
I300_ALT = "https://develon-ce.cl/wp-content/uploads/dx300-alt.png"

INDEX = f"""
<html><head><title>Excavadoras sobre Orugas - Hyundai Develon Chile</title></head><body>
<h1>Excavadoras sobre Orugas</h1>
<a href="{P300}"><img src="{I300}"></a>
<a href="{P300}">Excavadora Sobre Orugas DX300LC-7</a>
<a href="{P255}"><img src="{I255}"></a>
<a href="{P255}">Excavadora Sobre Orugas DX255LC-7</a>
</body></html>
"""


def image_bytes(seed, *, size=(120, 120)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10 + seed, 15, 90, 100), fill=(220, 70 + seed, 20))
    draw.line((0, seed, 119, 119 - seed), fill=(20, 30, 100), width=3)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class PhotoMatchTests(SimpleTestCase):
    def setUp(self):
        self.target = image_bytes(4)
        self.thumbs = {I300: self.target, I255: image_bytes(45)}

    def index_fetcher(self, url, retrieved_urls, deadline):
        self.assertEqual(url, INDEX_URL)
        return SimpleNamespace(html=INDEX, final_url=INDEX_URL)

    def image_fetcher(self, url, deadline):
        return self.thumbs[url]

    def test_only_unique_high_similarity_thumbnail_returns_document_reference(self):
        result = match_catalog_photo(self.target, "DEVELON", "Excavadoras",
                                     index_fetcher=self.index_fetcher,
                                     image_fetcher=self.image_fetcher)
        self.assertIsNotNone(result)
        self.assertEqual(result["model"], "DX300LC-7")
        self.assertEqual(result["source_url"], P300)
        self.assertEqual(result["image_url"], I300)
        self.assertGreaterEqual(result["score"], 0.985)
        self.assertEqual(result["origin"], "direct_verified_catalog_photo_match")

    def test_low_similarity_and_ambiguous_duplicates_return_no_match(self):
        self.thumbs[I300] = image_bytes(70)
        self.assertIsNone(match_catalog_photo(self.target, "DEVELON", "Excavadoras",
                                              index_fetcher=self.index_fetcher,
                                              image_fetcher=self.image_fetcher))

    def test_two_thumbnails_for_one_model_do_not_create_a_false_ambiguity(self):
        index = INDEX.replace("</body>", f'<a href="{P300}"><img src="{I300_ALT}"></a></body>')
        self.thumbs[I300_ALT] = image_bytes(30)
        result = match_catalog_photo(
            self.target, "DEVELON", "Excavadoras",
            index_fetcher=lambda *args: SimpleNamespace(html=index, final_url=INDEX_URL),
            image_fetcher=self.image_fetcher,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["model"], "DX300LC-7")
        self.thumbs[I300] = self.target
        self.thumbs[I255] = self.target
        self.assertIsNone(match_catalog_photo(self.target, "DEVELON", "Excavadoras",
                                              index_fetcher=self.index_fetcher,
                                              image_fetcher=self.image_fetcher))

    def test_unknown_scope_and_conflicting_same_product_models_are_rejected(self):
        self.assertIsNone(match_catalog_photo(self.target, "DEVELON", "Retroexcavadoras",
                                              index_fetcher=self.index_fetcher,
                                              image_fetcher=self.image_fetcher))
        conflicting = INDEX.replace("Excavadora Sobre Orugas DX300LC-7</a>",
                                    "Excavadora Sobre Orugas DX255LC-7</a>")
        result = match_catalog_photo(self.target, "DEVELON", "Excavadoras",
                                     index_fetcher=lambda *args: SimpleNamespace(html=conflicting, final_url=INDEX_URL),
                                     image_fetcher=self.image_fetcher)
        self.assertIsNone(result)

    def test_total_thumbnail_downloads_are_bounded(self):
        calls = []
        def fetch(url, deadline):
            calls.append(url)
            return self.thumbs.get(url, image_bytes(90))
        match_catalog_photo(self.target, "DEVELON", "Excavadoras",
                            index_fetcher=self.index_fetcher, image_fetcher=fetch)
        self.assertLessEqual(len(calls), MAX_IMAGES)

    def test_uniform_photo_is_not_a_catalogue_match(self):
        image = Image.new("RGB", (120, 120), (128, 128, 128))
        out = BytesIO()
        image.save(out, format="PNG")
        calls = []
        result = match_catalog_photo(out.getvalue(), "DEVELON", "Excavadoras",
                                     index_fetcher=self.index_fetcher,
                                     image_fetcher=lambda *args: calls.append(args) or self.target)
        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_image_transport_rejects_http_and_pins_public_ip_with_query(self):
        from unittest.mock import patch

        with patch("portal.research_photo_match._resolve_public_ip") as resolve:
            with self.assertRaises(CatalogFetchError):
                _fetch_image("http://develon-ce.cl/wp-content/a.png", 9999999999, ("develon-ce.cl",))
            resolve.assert_not_called()

        payload = self.target
        calls = []

        class Response:
            status = 200
            headers = {"Content-Type": "image/png", "Content-Length": str(len(payload))}
            def read1(self, size, decode_content=False):
                if hasattr(self, "read"):
                    return b""
                self.read = True
                return payload
            def close(self):
                pass

        class Pool:
            def __init__(self, ip, **kwargs):
                calls.append((ip, kwargs))
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def urlopen(self, method, target, **kwargs):
                calls.append((method, target, kwargs))
                return Response()

        with patch("portal.research_photo_match._resolve_public_ip", return_value="198.51.100.9") as resolve, \
                patch("portal.research_photo_match.urllib3.HTTPSConnectionPool", Pool):
            raw, final_url = _fetch_image("https://develon-ce.cl/wp-content/a.png?size=367", 9999999999,
                                          ("develon-ce.cl",))
        self.assertEqual(raw, payload)
        self.assertEqual(final_url, "https://develon-ce.cl/wp-content/a.png?size=367")
        resolve.assert_called_once_with("develon-ce.cl", 9999999999)
        self.assertEqual(calls[0][0], "198.51.100.9")
        self.assertEqual(calls[1][0:2], ("GET", "/wp-content/a.png?size=367"))
        self.assertEqual(calls[0][1]["assert_hostname"], "develon-ce.cl")

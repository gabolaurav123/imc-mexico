"""Small synthetic fixtures use the structures observed on the public sites."""
from django.test import SimpleTestCase

from portal.research import ResearchExtraction, normalize_research
from portal.research_catalogs import MAX_HTML_BYTES, MAX_ROWS, parse_catalog_html

CAT_URL = "https://h-cpc.cat.com/cmms/v2?f=product&pid=1000001746&lid=en"
RITCHIE_URL = "https://www.ritchiespecs.com/model/caterpillar-330d-l-hydraulic-excavator"


def table(section, rows):
    return "<table><caption>" + section + "</caption><tbody>" + "".join(
        f"<tr><td>{label}</td><td>{value}</td></tr>" for label, value in rows) + "</tbody></table>"


def metric(value):
    return f'<span class="unit">—</span><span class="unit english hidden">94&nbsp;hp</span><span class="unit metric hidden">{value}</span>'


def cat_html(model="320", content="", title=None):
    title = title if title is not None else f"Cat {model} | Caterpillar"
    return f'<html><head><title>{title}</title></head><body><h1>{model}</h1><div id="specifications">{content}</div></body></html>'


def ritchie_section(name, rows):
    return '<div class="two-grid dimensions"><div class="row"><h3>' + name + '</h3></div>' + "".join(
        f'<div><div class="row"><div><h4 itemprop="name">{label}</h4></div><div><p>'
        f'<span itemprop="value">{value}</span><span itemprop="unitText">{unit}</span></p></div></div></div>'
        for label, value, unit in rows) + '</div>'


def ritchie_html(content, heading="Caterpillar 330D L Hydraulic Excavator", other=""):
    # The actual server HTML has an empty title; the exact H1 supplies its title.
    return f'<html><head><title></title></head><body><div class="item-details"><h1>{heading}</h1>{content}</div>{other}</body></html>'


class CatalogueParserTests(SimpleTestCase):
    def cat(self, html, model="320", brand="Caterpillar", url=CAT_URL):
        return parse_catalog_html(html, url, {"brand": brand, "model": model})

    def ritchie(self, html, model="330D L", brand="Caterpillar", url=RITCHIE_URL):
        return parse_catalog_html(html, url, {"brand": brand, "model": model})

    def test_shared_cat_heading_keeps_document_rows_without_unit_or_variant_candidates(self):
        html = cat_html("420F2/420F2 IT", table("Engine", [("Net Power - SAE J1349:2011", metric("70&nbsp;kW"))]))
        for model in ("420F2", "420F2 IT"):
            with self.subTest(model=model):
                result = self.cat(html, model)
                self.assertEqual(result["status"], "ambiguous_models")
                self.assertEqual(result["fields"], [])
                self.assertEqual(result["model_info"]["document_models"], ["420F2", "420F2 IT"])
                self.assertEqual(result["rows"][0]["value"], "70 kW")

    def test_single_cat_model_preserves_metric_standard_and_maximum_qualifiers(self):
        content = table("Engine", [("Net Power - SAE J1349:2011", metric("70&nbsp;kW"))])
        content += table("Engine - Standard", [("Engine Model", "Cat C7.1"), ("Net Power - ISO", metric("71 kW"))])
        content += table("Engine - Optional", [("Engine Model", "Cat C9"), ("Net Power", metric("99 kW"))])
        content += table("Weights", [("Operating Weight - Maximum", metric("11000 kg")), ("Note", "Standard configuration.")])
        content += table("Hydraulic System", [("Pump Capacity", "163 L/min")])
        result = self.cat(cat_html(content=content))
        self.assertEqual(result["status"], "matched")
        fields = {field.key: field for field in result["fields"]}
        self.assertEqual(fields["power"].value, "70 kW")
        self.assertEqual(fields["weight"].value, "Operating Weight - Maximum: 11000 kg")
        self.assertIn("Standard configuration.", fields["weight"].evidence)
        self.assertEqual(fields["engine"].value, "Engine - Standard. Engine Model: Cat C7.1")
        self.assertNotIn("capacity", fields)
        self.assertTrue(all(field.scope == "model" and field.matched_serial is None for field in fields.values()))

    def test_brand_and_exact_model_must_be_proven_not_guessed_from_url(self):
        html = cat_html("420F2 IT", table("Engine", [("Net Power", metric("70 kW"))]))
        for model, brand in (("420F2", "Caterpillar"), ("420F2 IT", "Komatsu"), ("420F2 IT II", "Caterpillar")):
            with self.subTest(model=model, brand=brand):
                self.assertEqual(self.cat(html, model, brand)["fields"], [])
        result = self.cat(cat_html("320", table("Engine", [("Net Power", metric("70 kW"))]), title="Unknown catalogue"))
        self.assertEqual(result["status"], "identity_mismatch")
        self.assertFalse(result["model_info"]["brand_verified"])

    def test_ritchie_rejects_conflicting_ratings_but_keeps_weight_and_reference_capacity(self):
        content = ritchie_section("Engine", [("Net Power", "270", "hp"), ("Net Power - Iso 9249", "268", "hp"),
            ("Net Power - Sae J1349", "266", "hp"), ("Engine Model", "C9 ACERT", ""), ("Engine Model", "Cat C9 ACERT", "")])
        content += ritchie_section("Operational", [("Operating Weight", "79700", "lb")])
        content += ritchie_section("Weights", [("Operating Weight", "79700", "lb")])
        content += ritchie_section("Buckets", [("Reference Bucket Capacity", "1.6", "yd3")])
        result = self.ritchie(ritchie_html(content))
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["title"], "Caterpillar 330D L Hydraulic Excavator")
        self.assertEqual({field.key: field.value for field in result["fields"]},
                         {"weight": "79700 lb", "capacity": "Reference Bucket Capacity: 1.6 yd3"})
        self.assertEqual(set(result["conflicting_fields"]), {"engine", "power"})

    def test_ritchie_does_not_borrow_compare_models_or_boom_options(self):
        content = ritchie_section("Operational", [("Operating Weight", "79700", "lb")])
        content += ritchie_section("Boom/Stick Option (Hex) 1", [("Operating Weight", "99999", "lb")])
        other = '<div class="compare-block"><h1>Compare similar models</h1>' + ritchie_section("Operational", [("Operating Weight", "22222", "lb")]) + '</div>'
        result = self.ritchie(ritchie_html(content, other=other))
        self.assertEqual([(field.key, field.value) for field in result["fields"]], [("weight", "79700 lb")])
        self.assertFalse(any("99999" in row["value"] or "22222" in row["value"] for row in result["rows"]))
        for model in ("330D", "330D LR", "330D L II"):
            with self.subTest(model=model):
                self.assertEqual(self.ritchie(ritchie_html(content), model=model)["status"], "identity_mismatch")

    def test_parser_outputs_flow_through_real_literal_normalization_without_fake_identity_prose(self):
        result = self.ritchie(ritchie_html(ritchie_section("Operational", [("Operating Weight", "79700", "lb")])))
        field = result["fields"][0]
        self.assertNotIn("Caterpillar", field.evidence)
        research = normalize_research(ResearchExtraction(fields=result["fields"]),
            {"brand": "Caterpillar", "model": "330D L", "serial": None}, "model",
            [{"url": RITCHIE_URL, "title": result["title"]}], field.evidence,
            citations={RITCHIE_URL: [field.evidence]}, source_titles={RITCHIE_URL: result["title"]})
        self.assertEqual([(item["key"], item["value"]) for item in research["fields"]], [("weight", "79700 lb")])

    def test_scripts_comments_hidden_markup_and_foreign_urls_cannot_supply_values(self):
        content = '<script>' + table("Engine", [("Net Power", "999 kW")]) + '</script>'
        content += '<!--' + table("Engine", [("Net Power", "888 kW")]) + '-->'
        content += '<div hidden>' + table("Engine", [("Net Power", "777 kW")]) + '</div>'
        content += table("Engine", [("Net Power", metric("70 kW"))])
        result = self.cat(cat_html(content=content))
        self.assertEqual([(field.key, field.value) for field in result["fields"]], [("power", "70 kW")])
        for url in ("http://h-cpc.cat.com/cmms/v2", "https://h-cpc.cat.com.evil.invalid/cmms/v2",
                    "https://user:pass@h-cpc.cat.com/cmms/v2", "https://127.0.0.1/cmms/v2", "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertEqual(self.cat(cat_html(content=content), url=url)["status"], "unsupported_source")

    def test_oversized_deep_or_excessive_row_documents_fail_closed(self):
        for html in ("x" * (MAX_HTML_BYTES + 1), "<div>" * 82,
                     cat_html(content=table("Engine", [("Net Power", "70 kW")] * (MAX_ROWS + 1)))):
            with self.subTest(size=len(html)):
                result = self.cat(html)
                self.assertEqual(result["status"], "invalid_document")
                self.assertEqual(result["fields"], [])

    def test_non_numeric_placeholders_and_encoded_html_are_not_technical_values(self):
        content = table("Engine", [("Net Power", metric("—")), ("Engine Model", "&lt;script&gt;run()&lt;/script&gt;")])
        result = self.cat(cat_html(content=content))
        self.assertEqual(result["fields"], [])

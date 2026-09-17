"""Synthetic commercial sheet checks: no external sources, AI, or production data."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader

from portal.commercial import ESTIMATE_LABEL, ESTIMATE_LABELS, VISUAL_LABELS
from portal.models import Machine, User
from portal.pdf import build_pdf
from portal.valuation import VALUATION_VERSION, _seal
from portal.views import sheet_context


def commercial_snapshot(*, long=False, reference_count=2):
    """Signed synthetic fixture; domains are reserved examples, never fetched."""
    data = {
        "brand": "MARCA PRUEBA", "model": "MODELO QA", "serial": "SERIE-PRIVADA-QA-7788",
        "description": "PRUEBA NO INVENTARIO. Equipo ficticio para verificar el documento.",
        "usage_condition": "Usada", "preservation_condition": "Aceptable",
        "preservation_notes": "Pintura con desgaste visible. La inspección mecánica está pendiente.",
        "operating_status": "Pendiente de confirmar", "visible_defects": "Rayones visibles en el bastidor.",
        "visible_components": "Mástil, horquillas y neumáticos.", "attachments": "Horquillas de prueba.",
        "applications": "Manipulación de cargas; confirmar capacidad y condiciones del lugar.",
        "estimate_min": "1000.25", "estimate_max": "2000.75", "estimate_currency": "USD",
        "estimate_market": "Mercado sintético de prueba", "estimate_basis": "Comparables ficticios para probar el diseño.",
        "estimate_missing_info": "Confirmar horas de uso y estado de funcionamiento.",
        "price": "1500.50", "currency": "USD", "location": "Ubicación de PRUEBA",
        "notes": "NOTA-INTERNA-QA", "plate_transcription": "TRANSCRIPCION-PRIVADA-QA",
    }
    if long:
        for key in ("preservation_notes", "visible_defects", "visible_components", "applications"):
            data[key] = "INICIO-" + key + "\n" + ("Observación sintética, editable y pendiente de confirmar. " * 22) + "\nFIN-" + key
        data["estimate_basis"] = "BASE-INICIO " + "Referencia sintética para verificar saltos de página. " * 22 + " BASE-FIN"
    analysis_id = str(uuid4())
    provenance = {key: {"source": "visual_proposal", "review": "needs_review"} for key in VISUAL_LABELS}
    provenance.update({key: {"source": "valuation", "review": "needs_review", "analysis_id": analysis_id}
                       for key in (*ESTIMATE_LABELS, "price", "currency")})
    provenance["serial"] = {"source": "plate", "review": "clear", "component": "machine"}
    valuation = _seal({"version": VALUATION_VERSION, "label": ESTIMATE_LABEL, "status": "estimated",
        "fields": {key: data[key] for key in ESTIMATE_LABELS}, "suggested_price": data["price"],
        "identity": {"brand": data["brand"], "model": data["model"]},
        "comparables": [{"url": f"https://catalog.example/qa/{index}",
            "title": f"PRUEBA NO INVENTARIO - Referencia {index:02}", "price": str(1200 + index * 10),
            "currency": "USD", "market": "Mercado sintético", "price_type": "asking" if index % 2 else "sold"}
            for index in range(1, reference_count + 1)]})
    return {"title": "PRUEBA NO INVENTARIO - Ficha comercial", "data": data, "provenance": provenance,
        "category_name": "Equipo de prueba", "valuations": {analysis_id: valuation}, "web_research": {},
        "asset_ids": [], "public_asset_ids": [], "contact_authorized": False}


def pdf_links(document):
    return [str(annotation.get_object().get("/A", {}).get("/URI", ""))
            for page in document.pages for annotation in page.get("/Annots", [])
            if annotation.get_object().get("/A", {}).get("/URI")]


@override_settings(SECURE_SSL_REDIRECT=False, STAFF_MFA_REQUIRED=False, PRIVATE_S3_BUCKET="",
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class CommercialSheetTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="commercial-sheet@example.invalid",
            email="commercial-sheet@example.invalid", is_test=True)
        self.machine = Machine.objects.create(owner=self.owner, title="BORRADOR-ACTUAL-PRIVADO",
            data={"price": "99999999", "applications": "APLICACION-BORRADOR-PRIVADO"})

    def render(self, snapshot, *, public=False):
        version = SimpleNamespace(pk=1, number=1, created_at=timezone.now(), data=deepcopy(snapshot))
        context = sheet_context(self.machine, version, public=public, token="qa-token")
        context["user"] = self.owner
        html = render_to_string("portal/sheet.html", context)
        document = PdfReader(BytesIO(build_pdf(self.machine, context["data"], [], public=public, version=version)))
        text = "\n".join(page.extract_text() for page in document.pages)
        return html, document, text

    def test_visual_fields_estimate_and_asking_vs_sold_are_present_in_both_documents(self):
        fixture = commercial_snapshot()
        for public in (False, True):
            with self.subTest(public=public):
                html, document, text = self.render(fixture, public=public)
                for key in (*VISUAL_LABELS, *ESTIMATE_LABELS):
                    self.assertIn(fixture["data"][key], html)
                    self.assertIn(fixture["data"][key], " ".join(text.split()))
                for output in (html, " ".join(text.split())):
                    self.assertIn(ESTIMATE_LABEL, output)
                    self.assertIn("Precio de anuncio", output)
                    self.assertIn("Venta registrada", output)
                    self.assertNotIn("BORRADOR-ACTUAL-PRIVADO", output)
                    self.assertNotIn("APLICACION-BORRADOR-PRIVADO", output)
                    self.assertNotIn("99999999", output)
                self.assertEqual(pdf_links(document), ["https://catalog.example/qa/1", "https://catalog.example/qa/2"])

    def test_public_snapshot_filters_serial_from_new_fields_and_comparable_titles_and_urls(self):
        fixture = commercial_snapshot()
        serial = fixture["data"]["serial"]
        fixture["data"]["visible_defects"] = "Dato privado " + serial
        fixture["data"]["estimate_missing_info"] = "Consultar " + serial
        valuation = next(iter(fixture["valuations"].values()))
        valuation["comparables"].extend([
            {"url": "https://catalog.example/qa/" + serial, "title": "Enlace privado", "price": "1500", "currency": "USD"},
            {"url": "https://catalog.example/qa/private-title", "title": serial, "price": "1500", "currency": "USD"}])
        _seal(valuation)
        public_html, document, public_text = self.render(fixture, public=True)
        for output in (public_html, public_text, " ".join(pdf_links(document))):
            for private in (serial, "NOTA-INTERNA-QA", "TRANSCRIPCION-PRIVADA-QA", "Enlace privado", "private-title"):
                self.assertNotIn(private, output)
        internal_html, _, internal_text = self.render(fixture)
        self.assertIn(serial, internal_html)
        self.assertIn(serial, internal_text)
        self.assertIn("NOTA-INTERNA-QA", internal_text)

    def test_safe_links_escaped_text_and_signature_or_identity_gates(self):
        fixture = commercial_snapshot()
        fixture["data"]["applications"] = '<img src=x onerror=alert(1)> PRUEBA'
        valuation = next(iter(fixture["valuations"].values()))
        valuation["comparables"][0]["title"] = '<script>alert(1)</script> PRUEBA'
        valuation["comparables"].extend([
            {"url": url, "title": "URL INSEGURA", "price": "1", "currency": "USD"}
            for url in ("javascript:alert(1)", "https://user:pass@catalog.example/qa", "https://127.0.0.1/qa")])
        _seal(valuation)
        html, document, text = self.render(fixture, public=True)
        self.assertIn("&lt;img", html)
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('<img src=x onerror=alert(1)> PRUEBA', text)
        self.assertEqual(pdf_links(document), ["https://catalog.example/qa/1", "https://catalog.example/qa/2"])
        self.assertNotIn("URL INSEGURA", html)
        for mismatch in ("signature", "identity"):
            with self.subTest(mismatch=mismatch):
                changed = deepcopy(fixture)
                if mismatch == "signature":
                    next(iter(changed["valuations"].values()))["proof"] = "invalid"
                else:
                    changed["data"]["model"] = "OTRO MODELO"
                html, document, _ = self.render(changed, public=True)
                self.assertEqual(pdf_links(document), [])
                self.assertNotIn('href="https://catalog.example/', html)

    def test_long_observations_and_many_price_links_remain_complete_inside_pdf_margins(self):
        fixture = commercial_snapshot(long=True, reference_count=12)
        html, document, text = self.render(fixture)
        self.assertGreaterEqual(len(document.pages), 3)
        for key in ("preservation_notes", "visible_defects", "visible_components", "applications"):
            self.assertIn("FIN-" + key, html)
            self.assertIn("FIN-" + key, text)
        self.assertIn("BASE-FIN", text)
        self.assertEqual(len(pdf_links(document)), 12)
        for page in document.pages:
            for annotation in page.get("/Annots", []):
                link = annotation.get_object()
                if not link.get("/A", {}).get("/URI"):
                    continue
                x0, y0, x1, y1 = map(float, link["/Rect"])
                self.assertGreaterEqual(x0, 40)
                self.assertLessEqual(x1, float(page.mediabox.width) - 40)
                self.assertGreaterEqual(y0, 59, "Reference link must remain above the footer/body margin")
                self.assertLessEqual(y1, float(page.mediabox.height) - 105)

    def test_clearing_one_range_end_keeps_the_other_visible_and_zero_range_is_not_hidden(self):
        for minimum, maximum, remaining in ((None, "4321.25", "4321.25"),
                                             ("1234.75", None, "1234.75"), (0, 0, None)):
            with self.subTest(minimum=minimum, maximum=maximum):
                fixture = commercial_snapshot()
                fixture["data"].update({key: None for key in ESTIMATE_LABELS})
                fixture["data"].update(estimate_min=minimum, estimate_max=maximum, estimate_currency="USD")
                html, _, text = self.render(fixture, public=True)
                self.assertIn('id="sheet-valuation"', html)
                self.assertIn(ESTIMATE_LABEL, html)
                self.assertIn(ESTIMATE_LABEL, " ".join(text.split()))
                if remaining:
                    self.assertIn(remaining, html)
                    self.assertIn(remaining, text)
                else:
                    self.assertIn("Valor orientativo mínimo: 0 USD", html)
                    self.assertIn("Valor orientativo máximo: 0 USD", html)
                    self.assertRegex(text, r"0\s*-\s*0\s+USD")


    def test_approximate_year_is_separate_from_exact_year_in_snapshot_web_and_pdf(self):
        fixture = commercial_snapshot()
        fixture["data"].update(year=2007, estimated_year_from=2004, estimated_year_to=2009,
            estimated_year_basis="Indicios documentales de la familia; confirmar en esta unidad.")
        self.machine.data.update(estimated_year_from=2024, estimated_year_to=2025,
            estimated_year_basis="BORRADOR-ACTUAL-NO-AUTORIZADO")
        for public in (False, True):
            with self.subTest(public=public):
                html, _, text = self.render(fixture, public=public)
                for output in (html, text):
                    self.assertIn("Año aproximado · por confirmar", output)
                    self.assertIn("2004–2009", output)
                    self.assertIn("2007", output)
                    self.assertIn("Rango orientativo; no sustituye el año exacto de fabricación.", output)
                    self.assertIn(fixture["data"]["estimated_year_basis"], output)
                    self.assertNotIn("BORRADOR-ACTUAL-NO-AUTORIZADO", output)
                self.assertIn('id="sheet-age"', html)
                technical = html.split('id="sheet-technical"', 1)[1].split('</section>', 1)[0]
                self.assertNotIn("Año aproximado", technical)
        self.assertEqual(fixture["data"]["year"], 2007)

    def test_partial_age_endpoints_remain_visible_but_basis_alone_is_not_a_range(self):
        for start, end, expected in ((2004, None, "Desde 2004"), (None, 2009, "Hasta 2009"),
                                     (None, None, None)):
            with self.subTest(start=start, end=end):
                fixture = commercial_snapshot()
                fixture["data"].update(estimated_year_from=start, estimated_year_to=end,
                    estimated_year_basis="INDICIO-ANTERIOR-A-RANGO-BORRADO")
                html, _, text = self.render(fixture, public=True)
                if expected:
                    self.assertIn(expected, html)
                    self.assertIn(expected, text)
                else:
                    self.assertNotIn('id="sheet-age"', html)
                    self.assertNotIn("Año aproximado · por confirmar", text)
                    self.assertNotIn("INDICIO-ANTERIOR-A-RANGO-BORRADO", html)
                    self.assertNotIn("INDICIO-ANTERIOR-A-RANGO-BORRADO", text)

    def test_age_basis_is_escaped_and_private_serial_stays_out_of_public_documents(self):
        fixture = commercial_snapshot()
        fixture["data"].update(estimated_year_from=2000, estimated_year_to=2005,
            estimated_year_basis='<img src=x onerror=alert(1)> Indicio de prueba')
        html, _, text = self.render(fixture)
        self.assertIn('&lt;img', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('<img src=x onerror=alert(1)> Indicio de prueba', text)
        fixture["data"]["estimated_year_basis"] = "Consulta privada " + fixture["data"]["serial"]
        html, _, text = self.render(fixture, public=True)
        for output in (html, text):
            self.assertNotIn(fixture["data"]["serial"], output)
            self.assertIn("2000–2005", output)

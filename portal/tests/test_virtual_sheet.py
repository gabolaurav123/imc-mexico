"""The screen document is useful without exposing private sections publicly."""
from types import SimpleNamespace
from datetime import datetime, timezone

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from portal.models import Machine, User
from portal.sheet_details import build_sheet_details


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class VirtualSheetTests(SimpleTestCase):
    def context(self):
        owner = User(email="screen-fixture@example.invalid")
        data = {"brand": "Marca de prueba", "model": "Modelo de prueba", "serial": "PRIVATE-SERIAL",
                "power": "4.5 kW", "hours": 0, "price": 0, "country_of_origin": "País de fabricación de prueba",
                "location": "Ubicación actual declarada", "notes": "PRIVATE-NOTE",
                "plate_transcription": "PRIVATE-TRANSCRIPTION", "description": "Descripción <script>bad()</script>"}
        machine = Machine(owner=owner, title="Equipo de prueba", data=data)
        return {"machine": machine, "data": data, "assets": [], "category_name": "Compactadoras",
                "technical_interpretation": build_sheet_details(data),
                "extra_fields": [{"key": "power", "label": "Potencia", "value": "4.5 kW", "source_label": "Leído en placa"}],
                "field_origins": {"brand": "Leído en placa"}, "public": False, "user": owner}

    def test_internal_sheet_shows_identification_specs_context_and_private_notes(self):
        html = render_to_string("portal/sheet.html", self.context())
        for value in ("Ficha en pantalla", "Identificación", "Características técnicas", "4.5 kW",
                      "Cómo interpretar estos datos", "Ubicación actual declarada", "País de fabricación de prueba",
                      "PRIVATE-SERIAL", "PRIVATE-NOTE", "PRIVATE-TRANSCRIPTION", "Leído en placa"):
            self.assertIn(value, html)
        self.assertIn("Horas de uso</dt><dd>0", html)
        self.assertIn("0 <small>MXN</small>", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()</script>", html)

    def test_public_template_never_renders_private_sections_or_management_actions(self):
        context = self.context()
        context.update(public=True, token="example-token")
        html = render_to_string("portal/sheet.html", context)
        for private in ("PRIVATE-SERIAL", "PRIVATE-NOTE", "PRIVATE-TRANSCRIPTION", "Guardar disponibilidad",
                        "Duplicar como nuevo borrador", "Vista interna · datos privados"):
            self.assertNotIn(private, html)
        self.assertIn("/ficha/example-token/pdf/", html)
        self.assertIn("Consultar al equipo", html)

    def test_historical_internal_pdf_link_keeps_the_displayed_version(self):
        context = self.context()
        context["machine"].updated_at = datetime(2026, 9, 16, 18, tzinfo=timezone.utc)
        context["version"] = SimpleNamespace(pk="historical-version", number=3,
                                             created_at=datetime(2026, 8, 12, 18, tzinfo=timezone.utc))
        html = render_to_string("portal/sheet.html", context)
        self.assertIn("/pdf/?version=historical-version", html)
        self.assertIn("Versión 3 · 12/08/2026", html)
        self.assertNotIn("16/09/2026", html)
        context.pop("version")
        current = render_to_string("portal/sheet.html", context)
        self.assertIn("Revisión 1 · 16/09/2026", current)
        self.assertNotIn("12/08/2026", current)

    def test_coded_values_use_spanish_labels_and_free_text_is_preserved_escaped(self):
        for condition, label in (("new", "Nueva"), ("used", "Usada"), ("refurbished", "Reacondicionada"), ("for_repair", "Para reparación")):
            with self.subTest(condition=condition):
                context = self.context()
                context["data"].update(condition=condition, plate_kind="machine")
                html = render_to_string("portal/sheet.html", context)
                self.assertIn("Condición declarada</dt><dd>" + label, html)
                self.assertIn("Componente identificado en la placa</dt><dd>La máquina completa", html)
        for component, label in (("engine", "El motor"), ("transmission", "La transmisión"), ("other", "Otro componente")):
            with self.subTest(component=component):
                context = self.context()
                context["data"].update(condition="Usada con mantenimiento <b>registrado</b>", plate_kind=component)
                html = render_to_string("portal/sheet.html", context)
                self.assertIn("Componente identificado en la placa</dt><dd>" + label, html)
                self.assertIn("Usada con mantenimiento &lt;b&gt;registrado&lt;/b&gt;", html)
        context = self.context()
        context["data"]["plate_kind"] = "Placa auxiliar descrita por propietario"
        self.assertIn("Placa auxiliar descrita por propietario", render_to_string("portal/sheet.html", context))

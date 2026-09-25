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
                "power": "4.5 kW", "hours": 0, "price": 0, "currency": "MXN", "country_of_origin": "País de fabricación de prueba",
                "location": "Ubicación actual declarada", "notes": "PRIVATE-NOTE",
                "plate_transcription": "PRIVATE-TRANSCRIPTION", "description": "Descripción <script>bad()</script>"}
        machine = Machine(owner=owner, title="Equipo de prueba", data=data)
        return {"machine": machine, "data": data, "assets": [], "category_name": "Compactadoras", "has_identification": True,
                "technical_interpretation": build_sheet_details(data),
                "extra_fields": [{"key": "power", "label": "Potencia", "value": "4.5 kW", "source_label": "Leído en placa"}],
                "essential_fields": [{"key": "power", "label": "Potencia", "value": "4.5 kW"}],
                "field_origins": {"brand": "Leído en placa"}, "public": False, "user": owner}

    def test_owner_sheet_shows_essential_data_and_omits_administrative_details(self):
        html = render_to_string("portal/sheet.html", self.context())
        for value in ("Datos del equipo", "Información adicional", "4.5 kW",
                      "Ubicación actual declarada", "PRIVATE-SERIAL"):
            self.assertIn(value, html)
        for value in ("PRIVATE-NOTE", "PRIVATE-TRANSCRIPTION", "Leído en placa", "Cómo interpretar estos datos",
                      "País de fabricación de prueba"):
            self.assertNotIn(value, html)
        self.assertIn("Horas de uso</dt><dd>0", html)
        self.assertIn("<dt>Precio</dt><dd>0 MXN", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()</script>", html)

    def test_public_template_never_renders_private_sections_or_management_actions(self):
        context = self.context()
        context.update(public=True, token="example-token")
        html = render_to_string("portal/sheet.html", context)
        for private in ("PRIVATE-SERIAL", "PRIVATE-NOTE", "PRIVATE-TRANSCRIPTION", "Guardar disponibilidad",
                        "Duplicar como nuevo borrador", "Vista interna · datos privados"):
            self.assertNotIn(private, html)
        self.assertNotIn("/ficha/example-token/pdf/", html)
        self.assertEqual(html.count('data-share-sheet='), 2)
        self.assertIn("Ver máquinas similares", html)
        self.assertIn("https://www.imcmexico.com.mx/catalogo-de-maquinaria", html)
        self.assertIn("Solicitar información", html)

    def test_partial_price_ranges_and_zero_remain_unambiguous_in_owner_sheet(self):
        for minimum, maximum, expected in ((None, '4321.25', 'Hasta 4321.25 USD'),
                                            ('1234.75', None, 'Desde 1234.75 USD'),
                                            (0, 0, '0–0 USD'), (0, '2000', '0–2000 USD'),
                                            (0, None, 'Desde 0 USD'), (None, None, None)):
            with self.subTest(minimum=minimum, maximum=maximum):
                context = self.context()
                context['data'].update(price=None, estimate_min=minimum, estimate_max=maximum, estimate_currency='USD')
                html = render_to_string('portal/sheet.html', context)
                if expected:
                    self.assertIn('<dt>Precio estimado</dt>', html)
                    self.assertIn(expected, html)
                else:
                    self.assertNotIn('<dt>Precio estimado</dt>', html)

    def test_public_serial_requires_explicit_authorization_flag(self):
        context = self.context()
        context.update(public=True, public_serial_authorized=False)
        self.assertNotIn('PRIVATE-SERIAL', render_to_string('portal/sheet.html', context))
        context['public_serial_authorized'] = True
        html = render_to_string('portal/sheet.html', context)
        self.assertIn('PRIVATE-SERIAL', html)
        self.assertNotIn('PRIVATE-NOTE', html)
        self.assertNotIn('PRIVATE-TRANSCRIPTION', html)

    def test_historical_internal_pdf_link_keeps_the_displayed_version(self):
        context = self.context()
        context['can_export'] = True
        context["machine"].updated_at = datetime(2026, 9, 16, 18, tzinfo=timezone.utc)
        context["version"] = SimpleNamespace(pk="historical-version", number=3,
                                             created_at=datetime(2026, 8, 12, 18, tzinfo=timezone.utc))
        html = render_to_string("portal/sheet.html", context)
        self.assertIn("/pdf/?version=historical-version", html)
        self.assertIn("PDF administrativo", html)
        self.assertNotIn("16/09/2026", html)
        context.pop("version")
        current = render_to_string("portal/sheet.html", context)
        self.assertIn('/pdf/" download', current)
        self.assertNotIn("?version=historical-version", current)
        self.assertNotIn("12/08/2026", current)

    def test_coded_values_use_spanish_labels_and_free_text_is_preserved_escaped(self):
        for condition, label in (("new", "Nueva"), ("used", "Usada"), ("refurbished", "Reacondicionada"), ("for_repair", "Para reparación")):
            with self.subTest(condition=condition):
                context = self.context()
                context["data"].update(condition=condition, plate_kind="machine")
                html = render_to_string("portal/sheet.html", context)
                self.assertIn("Estado de uso</dt><dd>" + label, html)
                self.assertNotIn("Componente identificado en la placa", html)
        for component, label in (("engine", "El motor"), ("transmission", "La transmisión"), ("other", "Otro componente")):
            with self.subTest(component=component):
                context = self.context()
                context["data"].update(condition="Usada con mantenimiento <b>registrado</b>", plate_kind=component)
                html = render_to_string("portal/sheet.html", context)
                self.assertNotIn("Componente identificado en la placa", html)
                self.assertIn("Usada con mantenimiento &lt;b&gt;registrado&lt;/b&gt;", html)
        context = self.context()
        context["data"]["plate_kind"] = "Placa auxiliar descrita por propietario"
        self.assertNotIn("Placa auxiliar descrita por propietario", render_to_string("portal/sheet.html", context))

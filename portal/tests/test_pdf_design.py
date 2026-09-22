"""Render real PDF bytes from isolated objects; never connect to the database."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from tempfile import TemporaryDirectory
from pathlib import Path

from django.test import SimpleTestCase
from django.utils import timezone
from pypdf import PdfReader
from PIL import Image

from portal.pdf import _price, build_pdf


class PdfDesignTests(SimpleTestCase):
    def build(self, data, *, public=False, provenance=None, category=None, snapshot_data=None, assets=()):
        values = deepcopy(data)
        version_id = uuid4()
        machine = SimpleNamespace(title="PRUEBA de documentación técnica", folio="IMC-PRUEBA", revision=1,
            data=values, provenance=provenance or {}, category=category, availability="available",
            approved_version_id=version_id)
        snapshot = {"title": machine.title, "data": deepcopy(snapshot_data if snapshot_data is not None else values),
                    "provenance": deepcopy(provenance or {}), "category_name": "",
                    "web_research": {}, "asset_ids": [str(asset.pk) for asset in assets],
                    "public_asset_ids": [str(asset.pk) for asset in assets], "contact_authorized": False}
        version = SimpleNamespace(pk=version_id, number=1, created_at=timezone.now(), data=snapshot)
        document = PdfReader(BytesIO(build_pdf(machine, values, assets, public=public, version=version)))
        return document, "\n".join(page.extract_text() for page in document.pages)

    def test_plate_specifications_render_without_category_and_do_not_become_location(self):
        data = {"brand": "PRUEBA", "model": "016-9020", "power": "4.8 kW / 6.5 HP", "weight": "90 kg",
                "vibration_frequency": "4200 VPM", "centrifugal_force": "13 kN", "compaction_depth": "30 cm",
                "country_of_origin": "País sintético", "location": "Almacén de PRUEBA"}
        provenance = {key: {"source": "plate", "review": "clear", "component": "machine"} for key in data if key != "location"}
        for public in (False, True):
            with self.subTest(public=public):
                _, text = self.build(data, public=public, provenance=provenance)
                for value in data.values():
                    self.assertIn(value, text)
                self.assertIn("País de fabricación", " ".join(text.split()))
                self.assertNotIn("Lectura clara", text)
                self.assertNotIn("Confirmado por el anunciante", text)

    def test_public_copy_keeps_specs_but_never_prints_plate_evidence_transcription_or_private_fields(self):
        values = {"power": "8 kW", "serial": "PRIVATE-SERIAL", "plate_transcription": "PRIVATE-TRANSCRIPTION",
                  "notes": "PRIVATE-NOTE", "owner_email": "private@example.invalid"}
        provenance = {"power": {"source": "plate", "review": "clear", "evidence": "PRIVATE-EVIDENCE"}}
        _, public = self.build(values, public=True, provenance=provenance)
        self.assertIn("8 kW", public)
        self.assertNotIn("PRIVATE-", public)
        self.assertNotIn("private@example.invalid", public)
        _, internal = self.build(values, provenance=provenance)
        for value in ("PRIVATE-SERIAL", "PRIVATE-TRANSCRIPTION", "PRIVATE-NOTE"):
            self.assertIn(value, internal)
        self.assertNotIn("PRIVATE-EVIDENCE", internal)

    def test_downloadable_pdf_uses_plain_estimate_labels_and_starts_visual_block_on_page_two(self):
        values = {
            "brand": "PRUEBA", "model": "MODELO PDF", "description": "Excavadora CAT 320D L. Año aproximado: 2006–2014 (por Periodos catalogados 2006–2014; año de esta unidad por confirmar). Condición de uso aparente: Usada. Desgaste y detalles visibles: Desgaste superficial visible.",
            "estimated_year_from": 2004, "estimated_year_to": 2009,
            "estimated_year_basis": "Periodos publicados 2004–2009; año de esta unidad por confirmar.",
            "estimate_min": "1000", "estimate_max": "2000", "estimate_currency": "USD",
            "estimate_market": "Mercado de prueba", "estimate_basis": "Estimación orientativa, editable y sujeta a confirmación. Precios publicados no acreditan una venta cerrada. Sin conversión disponible. Comparables de mercado para equipos similares.",
            "visible_defects": "Rayones visibles en el bastidor.", "visible_components": "Mástil y horquillas.",
            "applications": "Manipulación de cargas.",
        }
        document, text = self.build(values, provenance={"description": {"source": "system"}})
        self.assertGreaterEqual(len(document.pages), 2)
        first_page, second_page = (page.extract_text() or "" for page in document.pages[:2])
        self.assertNotIn("Estado aparente, componentes y aplicaciones", first_page)
        self.assertIn("Estado aparente, componentes y aplicaciones", second_page)
        self.assertIn("IMC MÉXICO", second_page)
        self.assertIn("Excavadora CAT 320D L.", first_page)
        self.assertLess(first_page.index("Valor estimado"), first_page.index("Descripción del equipo"))
        self.assertLess(first_page.index("Año aproximado"), first_page.index("Descripción del equipo"))
        for heading in ("Valor estimado", "Año aproximado"):
            self.assertEqual(text.count(heading), 1)
            self.assertNotIn(heading, second_page)
        for expected in ("1,000–2,000 USD", "2004–2009", "Referencia de mercado: Mercado de prueba",
                         "Comparables de mercado para equipos similares", "Periodos publicados 2004–2009"):
            self.assertIn(expected, " ".join(first_page.split()))
        self.assertNotIn("Descripción del equipo", second_page)
        for expected in ("Año aproximado", "2004–2009", "Valor estimado", "1,000–2,000 USD",
                         "Referencia de mercado: Mercado de prueba", "Comparables de mercado para equipos similares", "Rayones visibles en el bastidor."):
            self.assertIn(expected, " ".join(text.split()))
        self.assertIn("Excavadora CAT 320D L.", text)
        self.assertNotIn("(por", text)
        for forbidden in ("por revisar", "sujeto a verificaci", "pendiente de revisar", "confirm", "verific", "comprob", "inspección pendiente", "sin estimar", "sin conversi", "no acreditan una venta cerrada", "uso interno",
                          "Trazabilidad de la información", "PDF INTERNO"):
            self.assertNotIn(forbidden.lower(), text.lower())

    def test_pending_operating_status_is_omitted_and_owner_declaration_stays_readable(self):
        _, pending = self.build({"operating_status": "Pendiente de confirmar", "visible_defects": "Fuga visible."})
        self.assertNotIn("Estado de funcionamiento", pending)
        self.assertIn("Fuga visible.", pending)
        _, declared = self.build({"operating_status": "Confirmado por el propietario"})
        self.assertIn("Funcionamiento declarado por el propietario", declared)
        self.assertNotIn("Confirmado", declared)

    def test_owner_description_keeps_its_own_year_and_hours_context(self):
        description = "Mantenimiento realizado en 2020. Año aproximado: referencia del propietario. Horas de uso: lectura al recibirlo."
        _, text = self.build({"description": description}, provenance={"description": {"source": "user"}})
        for phrase in ("Mantenimiento realizado en 2020.", "Año aproximado: referencia del propietario.", "Horas de uso: lectura al"):
            self.assertIn(phrase, text)

    def test_manual_parenthetical_review_phrase_does_not_leave_a_broken_fragment(self):
        description = "Año aproximado: 2010 (por confirmar). Motor sustituido en 2020."
        _, text = self.build({"description": description}, provenance={"description": {"source": "user"}})
        self.assertIn("Año aproximado: 2010.", text)
        self.assertIn("Motor sustituido en 2020.", text)
        self.assertNotIn("(por", text)

    def test_long_description_and_many_specs_do_not_push_visual_condition_past_page_two(self):
        values = {
            "brand": "PRUEBA", "model": "MODELO EXTENSO", "description": "INICIO-DESCRIPCION " + ("Detalle técnico documentado. " * 72) + "FIN-DESCRIPCION",
            "power": "100 kW", "weight": "20,000 kg", "capacity": "1.2 m³", "dimensions": "6 x 3 x 3 m",
            "engine": "Diésel", "transmission": "Hidrostática", "fuel": "Diésel", "vibration_frequency": "4,000 VPM",
            "centrifugal_force": "20 kN", "compaction_depth": "30 cm", "digging_depth": "5 m", "hydraulic_system": "Variable",
            "front_tire_size": "12.5/80-18", "rear_tire_size": "16.9-28", "mast_tilt": "6°", "load_tire_tread": "Neumático",
            "voltage": "48 V", "lift_height": "4.5 m", "load_center": "500 mm", "battery_weight": "700 kg",
            "battery_capacity": "600 Ah", "fork_length": "1.2 m", "hours": "5,000 h", "kilometers": "2,000 km",
            "condition": "En uso", "usage_condition": "Usada", "preservation_condition": "Aceptable",
            "visible_defects": "Desgaste objetivo visible.", "visible_components": "Componentes principales visibles.",
            "applications": "Carga y excavación.",
        }
        document, text = self.build(values)
        self.assertGreaterEqual(len(document.pages), 3)
        first_page, second_page = (page.extract_text() or "" for page in document.pages[:2])
        self.assertNotIn("Estado aparente, componentes y aplicaciones", first_page)
        self.assertIn("Estado aparente, componentes y aplicaciones", second_page)
        self.assertIn("Desgaste objetivo visible.", second_page)
        self.assertIn("INICIO-DESCRIPCION", first_page)
        self.assertNotIn("FIN-DESCRIPCION", first_page)
        self.assertIn("Descripción ampliada", text)
        self.assertIn("FIN-DESCRIPCION", text)

    def test_cover_estimates_stay_on_page_one_with_photo_and_long_notes(self):
        values = {
            "brand": "PRUEBA", "model": "MODELO DE PORTADA", "year": 2010, "hours": "5000 h",
            "price": "75000", "currency": "USD", "location": "Almacén de prueba",
            "power": "100 kW", "weight": "20000 kg", "capacity": "1.2 m³",
            "estimated_year_from": 2008, "estimated_year_to": 2012,
            "estimated_year_basis": "PERIODO-INICIO " + "Documentación histórica del modelo. " * 35 + " PERIODO-FIN",
            "estimate_min": "60000", "estimate_max": "80000", "estimate_currency": "USD",
            "estimate_market": "Estados Unidos",
            "estimate_basis": "MERCADO-INICIO " + "Precios de maquinaria comparable. " * 35 + " MERCADO-FIN",
            "description": "DESCRIPCION-INICIO " + "Características documentadas del equipo. " * 35 + " DESCRIPCION-FIN",
            "visible_defects": "Desgaste superficial.", "visible_components": "Brazo y cucharón.",
            "applications": "Excavación de tierra.",
        }
        with TemporaryDirectory(prefix="imc-cover-layout-") as directory:
            photo = Path(directory) / "machine.png"
            Image.new("RGB", (600, 900), "navy").save(photo)
            asset = SimpleNamespace(pk=uuid4(), kind="image", purpose="general", processing_status="ready",
                                    public_authorized=True, preview=photo, is_cover=True, position=0)
            document, text = self.build(values, assets=[asset])
        first_page, second_page = (" ".join(page.extract_text().split()) for page in document.pages[:2])
        for expected in ("Año aproximado", "2008–2012", "Valor estimado", "60,000–80,000 USD",
                         "PERIODO-INICIO", "MERCADO-INICIO", "DESCRIPCION-INICIO"):
            self.assertIn(expected, first_page)
        self.assertIn((600, 900), [image.image.size for image in document.pages[0].images])
        self.assertIn("Estado aparente, componentes y aplicaciones", second_page)
        self.assertNotIn("Valor estimado", second_page)
        self.assertNotIn("Año aproximado", second_page)
        for expected in ("PERIODO-FIN", "MERCADO-FIN", "DESCRIPCION-FIN"):
            self.assertIn(expected, text)

    def test_snapshot_values_take_precedence_over_live_machine_values(self):
        _, text = self.build({"power": "PRIVATE-DRAFT", "country_of_origin": "PRIVATE-DRAFT"}, public=True,
                            snapshot_data={"power": "5 kW", "country_of_origin": "Origen aprobado"})
        self.assertIn("5 kW", text)
        self.assertIn("Origen aprobado", text)
        self.assertNotIn("PRIVATE-DRAFT", text)

    def test_zero_is_a_real_value_and_empty_specs_do_not_create_invented_sections(self):
        _, text = self.build({"hours": 0, "price": "1234567.50", "currency": "MXN", "weight": None})
        self.assertIn("1,234,567.50 MXN", text)
        self.assertIn("Horas de uso", text)
        self.assertNotIn("Especificaciones técnicas", text)
        document, empty = self.build({})
        self.assertEqual(len(document.pages), 1)
        self.assertNotIn("Identificación del equipo", empty)
        self.assertNotIn("Datos adicionales", empty)
        self.assertNotIn("Consultar precio", empty)
        self.assertEqual(_price("1e1000000", "MXN"), "1e1000000 MXN")

    def test_long_technical_values_and_untrusted_markup_remain_complete_plain_text(self):
        values = {"vibration_frequency": "INICIO\n" + "registro de prueba\n" * 70 + "FIN",
                  "country_of_origin": '<a href="https://example.invalid">PRUEBA</a>'}
        document, text = self.build(values, public=True)
        self.assertGreaterEqual(len(document.pages), 2)
        self.assertIn("INICIO", text)
        self.assertIn("FIN", text)
        self.assertIn('<a href="https://example.invalid">PRUEBA</a>', text)
        links = [annotation.get_object() for page in document.pages for annotation in page.get("/Annots", [])]
        self.assertFalse(any(annotation.get("/A", {}).get("/URI") for annotation in links))

    def test_detected_plate_is_private_even_when_upload_was_marked_general(self):
        with TemporaryDirectory(prefix="imc-pdf-plate-") as directory:
            photo = Path(directory) / "test-plate.png"
            Image.new("RGB", (97, 61), "purple").save(photo)
            asset = SimpleNamespace(pk=uuid4(), kind="image", purpose="general", processing_status="ready",
                                    public_authorized=True, preview=photo, is_cover=True, position=0)
            machine = SimpleNamespace(title="PRUEBA", folio="IMC-PRUEBA", revision=1, provenance={}, category=None,
                                      availability="available", approved_version_id=None,
                                      _detected_plate_asset_ids={str(asset.pk)})
            snapshot = {"title":machine.title,"data":{},"provenance":{},"web_research":{},
                        "asset_ids":[str(asset.pk)],"public_asset_ids":[str(asset.pk)],
                        "private_plate_asset_ids":[str(asset.pk)],"contact_authorized":False}
            version = SimpleNamespace(pk=uuid4(),number=1,created_at=timezone.now(),data=snapshot)
            public = PdfReader(BytesIO(build_pdf(machine, {}, [asset], public=True, version=version)))
            self.assertNotIn((97,61), [item.image.size for page in public.pages for item in page.images])
            internal = PdfReader(BytesIO(build_pdf(machine, {}, [asset])))
            self.assertIn((97,61), [item.image.size for page in internal.pages for item in page.images])
            self.assertIn("PLACA DE IDENTIFICACIÓN", " ".join(page.extract_text() for page in internal.pages))
            self.assertEqual(asset.purpose, "general")
            values = {"serial": "PRIVATE-QA-123", "description": "Descripción de PRUEBA. " * 150}
            machine.provenance = {"serial": {"source": "plate", "review": "clear", "component": "machine"}}
            internal = PdfReader(BytesIO(build_pdf(machine, values, [asset])))
            self.assertIn("PRIVATE-QA-123", internal.pages[0].extract_text())
            machine.provenance["serial"]["review"] = "needs_review"
            uncertain = PdfReader(BytesIO(build_pdf(machine, values, [asset])))
            self.assertNotIn("PRIVATE-QA-123", uncertain.pages[0].extract_text())

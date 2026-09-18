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
    def build(self, data, *, public=False, provenance=None, category=None, snapshot_data=None):
        values = deepcopy(data)
        version_id = uuid4()
        machine = SimpleNamespace(title="PRUEBA de documentación técnica", folio="IMC-PRUEBA", revision=1,
            data=values, provenance=provenance or {}, category=category, availability="available",
            approved_version_id=version_id)
        snapshot = {"title": machine.title, "data": deepcopy(snapshot_data if snapshot_data is not None else values),
                    "provenance": deepcopy(provenance or {}), "category_name": "",
                    "web_research": {}, "asset_ids": [], "public_asset_ids": [], "contact_authorized": False}
        version = SimpleNamespace(pk=version_id, number=1, created_at=timezone.now(), data=snapshot)
        document = PdfReader(BytesIO(build_pdf(machine, values, [], public=public, version=version)))
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
                if not public:
                    self.assertIn("Lectura de placa", text)
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
        for value in ("PRIVATE-SERIAL", "PRIVATE-TRANSCRIPTION", "PRIVATE-NOTE", "PRIVATE-EVIDENCE"):
            self.assertIn(value, internal)

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

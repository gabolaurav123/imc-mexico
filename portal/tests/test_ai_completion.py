from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from portal.ai_completion import (MachineReference, ai_reference_identity_matches, complete_machine_reference,
    completion_reservation, is_validated_ai_field, is_validated_ai_reference, merge_machine_reference,
    missing_fields, normalize_reference)
from portal.models import Category, Machine, PlatformSettings, User
from portal.processing import _reservation, enqueue_analysis, process_next_job
from portal.research import (ResearchExtraction, ResearchField, UsageTotals, empty_research,
                             normalize_research, research_reservation)
from portal.valuation import _empty, _seal, valuation_reservation


IDENTITY = {"brand": "Caterpillar", "model": "320D", "condition": None, "configurations": {},
            "compatibility": {}, "market_hint": None}
DATA = {"brand": "Caterpillar", "model": "320D"}
META = {"source": "ai_reference", "review": "needs_review", "component": "machine"}


def proposal(**changes):
    values = dict(category="Excavadoras", year_from=2006, year_to=2015,
        year_basis="Referencia general de la generación del modelo.", price_min="45000", price_max="90000",
        currency="USD", market="Estados Unidos", price_basis="Intervalo amplio basado en conocimiento general del modelo.",
        technical_lines=["Excavadora hidráulica de orugas para excavación y carga de materiales.",
                         "Superestructura giratoria con pluma y brazo articulados.",
                         "Equipo de referencia para movimiento de tierras y construcción."])
    # model_copy also permits malformed historical/provider values in the
    # local normalizer's defense-in-depth regression cases below.
    return MachineReference(**values).model_copy(update=changes)


def reference(**changes):
    return normalize_reference(proposal(**changes), IDENTITY, DATA, None, ["Excavadoras"])


class AICompletionBoundaryTests(SimpleTestCase):
    def test_price_schema_requires_canonical_amounts_and_explicit_currency(self):
        from openai.lib._pydantic import to_strict_json_schema
        from pydantic import ValidationError
        schema = to_strict_json_schema(MachineReference)
        self.assertEqual(schema["properties"]["price_min"]["anyOf"][0]["pattern"], r"^\d{1,10}(?:\.\d{1,2})?$")
        for update in ({"price_min": "45,000"}, {"price_max": "USD 90000"}, {"currency": "CAD"}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                MachineReference.model_validate({**proposal().model_dump(), **update})

    def test_historical_unambiguous_grouping_and_uncertainty_keep_the_price_range(self):
        value = reference(price_min="45,000", price_max="90,000.00",
            price_basis="Referencia del modelo usado; condición de la unidad por confirmar.")
        self.assertEqual(value["fields"]["estimate_min"], "45000.00")
        self.assertEqual(value["fields"]["estimate_max"], "90000.00")
        self.assertIn("modelo usado", value["fields"]["estimate_basis"])
        self.assertNotIn("por confirmar", value["fields"]["estimate_basis"])
        self.assertEqual(value["diagnostics"]["price"], {"status": "accepted", "reasons": []})
        self.assertTrue(is_validated_ai_reference(value))

    def test_price_diagnostics_distinguish_omission_and_rejection_without_raw_data(self):
        omitted = reference(price_min=None, price_max=None, currency=None, market=None, price_basis=None)
        self.assertIn("minimum_omitted", omitted["diagnostics"]["price"]["reasons"])
        for raw in ("45,50", "45.000", "45k", "USD 45000", "45000-90000", "45,000,50", "0,500", "00,500"):
            with self.subTest(raw=raw):
                rejected = reference(price_min=raw)
                self.assertNotIn("estimate_min", rejected["fields"])
                self.assertIn("minimum_invalid", rejected["diagnostics"]["price"]["reasons"])
                self.assertNotIn(raw, str(rejected["diagnostics"]))
        private = normalize_reference(proposal(price_basis="Serie PRIVATE123 por confirmar"),
            IDENTITY, DATA, None, ["Excavadoras"], ["PRIVATE123"])
        self.assertIn("basis_rejected", private["diagnostics"]["price"]["reasons"])
        self.assertNotIn("PRIVATE123", str(private))

    def test_signed_range_has_clear_estimate_labels_and_four_line_summary(self):
        value = reference()
        self.assertTrue(is_validated_ai_reference(value))
        self.assertEqual(value["fields"]["estimate_min"], "45000.00")
        self.assertIn("Estimación orientativa de IA", value["fields"]["estimate_basis"])
        self.assertIn("no año exacto", value["fields"]["estimated_year_basis"])
        self.assertEqual(len(value["fields"]["description"].splitlines()), 4)

    def test_accepted_technical_lines_reach_the_sheet_without_losing_the_last_feature(self):
        from portal.sheet_details import build_technical_summary

        lines = [
            "Excavadora hidráulica sobre orugas con pluma y brazo articulados para excavar, cargar material y hacer movimientos de tierra en obras de construcción.",
            "Superestructura giratoria que permite orientar el implemento hacia distintas zonas de trabajo sin cambiar la posición del tren de rodaje.",
            "Cabina elevada con controles para accionar los movimientos de la pluma, del brazo y del cucharón durante las tareas de excavación.",
        ]
        self.assertEqual(len(lines[0]), 150)
        value = reference(technical_lines=lines)
        self.assertIn("description", value["fields"])
        summary = build_technical_summary(value["fields"])
        self.assertEqual(len(summary), 4)
        self.assertEqual(summary[1:], lines)
        self.assertEqual(value["missing_fields"], [])
        self.assertTrue(is_validated_ai_field({"ai_reference": value}, "estimate_min", "45000.00", META))
        value["fields"]["estimate_min"] = "1.00"
        self.assertFalse(is_validated_ai_reference(value))

    def test_invalid_or_inverted_ranges_and_unknown_currency_are_not_published(self):
        for changes in ({"price_min": "NaN"}, {"price_min": "90001"}, {"price_max": "1000000001"},
                        {"currency": "CAD"}, {"price_min": "-5"}):
            with self.subTest(changes=changes):
                value = reference(**changes)
                self.assertNotIn("estimate_min", value["fields"])
                self.assertIn("price_range", value["missing_fields"])
        for changes in ({"year_from": 2016}, {"year_to": timezone.localdate().year + 1}, {"year_from": 1899}):
            with self.subTest(changes=changes):
                self.assertNotIn("estimated_year_from", reference(**changes)["fields"])

    def test_summary_cannot_invent_numeric_specs_leak_serial_or_promise_condition(self):
        value = normalize_reference(proposal(technical_lines=["Potencia: 123 kW.", "Serie ABC12345.", "Lista para trabajar."]),
            IDENTITY, DATA, None, ["Excavadoras"], ["ABC12345"])
        self.assertNotIn("description", value["fields"])
        value = reference(technical_lines=["Potencia de 320 kW.", "Motor con gran capacidad.", "Equipo para movimiento de tierras."])
        self.assertNotIn("description", value["fields"])
        value = normalize_reference(proposal(technical_lines=["Potencia nominal: 320 kW.", "Motor con gran capacidad.",
            "Equipo para movimiento de tierras."]), {**IDENTITY, "model": "320"}, {**DATA, "model": "320"}, None, ["Excavadoras"])
        self.assertNotIn("description", value["fields"])
        value = reference(technical_lines=["Funcionamiento pendiente de confirmar.", "Sin datos.", "Perfecto estado."])
        self.assertNotIn("description", value["fields"])

    def test_summary_can_quote_one_printed_measurement_from_an_accepted_dual_unit_field(self):
        cases = (
            ("weight", "8240 lb; 3740 kg", "Peso operativo declarado de 3740 kg para la configuración documentada."),
            ("capacity", "500 lbs; 227 kg", "Capacidad de plataforma declarada de 227 kg para la configuración documentada."),
            ("lift_height", "189 in; 4800 mm", "Altura de elevación documentada de 4800 mm en la configuración de placa."),
            ("weight", "8240 lb / 3740 kg", "Peso operativo declarado de 3740 kg para la configuración documentada."),
            ("weight", "8240 lb / 3740 kg", "Peso operativo declarado de 8240 lb para la configuración documentada."),
            ("weight", "2742 lbs / 1244 kg", "Peso operativo declarado de 1244 kg para la configuración documentada."),
            ("weight", "2742 lbs / 1244 kg", "Peso operativo declarado de 2742 lbs para la configuración documentada."),
            ("capacity", "500 lbs / 227 kg", "Capacidad de plataforma declarada de 227 kg para la configuración documentada."),
            ("capacity", "500 lbs / 227 kg", "Capacidad de plataforma declarada de 500 lbs para la configuración documentada."),
            ("lift_height", "C: 189 in / 4800 mm", "Altura de elevación documentada de 4800 mm en la configuración de placa."),
            ("lift_height", "C: 189 in / 4800 mm", "Altura de elevación documentada de 189 in en la configuración de placa."),
        )
        for key, literal, line in cases:
            with self.subTest(key=key, line=line):
                lines = [line, *proposal().technical_lines[1:]]
                value = normalize_reference(proposal(technical_lines=lines), IDENTITY,
                    {**DATA, key: literal}, "Excavadoras", ["Excavadoras"])
                self.assertIn(line, value["fields"]["description"])
                self.assertEqual(value["identity"]["technical_context"][key], literal)

    def test_dual_units_do_not_license_conversion_changed_values_or_wrong_labels(self):
        cases = (
            ("weight", "8240 lb / 3740 kg", "Peso operativo declarado de 3.74 t para la configuración documentada."),
            ("weight", "8240 lb / 3740 kg", "Peso operativo declarado de 3750 kg para la configuración documentada."),
            ("weight", "8240 lb / 3740 kg", "Capacidad de carga declarada de 3740 kg para la configuración documentada."),
            ("lift_height", "C: 189 in / 4800 mm", "Altura de elevación documentada de 4.8 m en la configuración de placa."),
            ("lift_height", "MAX 189 in / 4800 mm", "Altura de elevación documentada de 4800 mm en la configuración de placa."),
            ("weight", "3740 kg / 4200 kg", "Peso operativo declarado de 3740 kg para la configuración documentada."),
            ("capacity", "500 lbs / 227 kg", "Capacidad de plataforma declarada de 0.227 t para la configuración documentada."),
            ("capacity", "500 lbs / 227 kg", "Capacidad de plataforma declarada de 250 kg para la configuración documentada."),
            ("capacity", "500 lbs / 227 kg", "Peso operativo declarado de 227 kg para la configuración documentada."),
            ("capacity", "MAX 500 lbs / 227 kg", "Capacidad de plataforma declarada de 227 kg para la configuración documentada."),
            ("capacity", "2250 kg / 1950 kg", "Capacidad de carga declarada de 2250 kg para la configuración documentada."),
            ("capacity", "2250 kg a 3300 mm / 1950 kg a 4800 mm", "Capacidad de carga declarada de 2250 kg para la configuración documentada."),
            ("capacity", "2250 kg a 600 mm; 1950 kg a 760 mm", "Capacidad de carga declarada de 2250 kg para la configuración documentada."),
            ("lift_height", "MAX 189 in; 4800 mm", "Altura de elevación documentada de 4800 mm en la configuración de placa."),
        )
        for key, literal, line in cases:
            with self.subTest(key=key, literal=literal, line=line):
                value = normalize_reference(proposal(technical_lines=[line, *proposal().technical_lines[1:]]),
                    IDENTITY, {**DATA, key: literal}, "Excavadoras", ["Excavadoras"])
                self.assertNotIn("description", value["fields"])

    def test_owner_range_and_description_are_preserved_as_groups(self):
        result = {"data": {}, "provenance": {}}
        snapshot = {"data": {"estimated_year_from": 2010, "estimate_currency": "MXN", "description": "Texto del dueño"},
                    "provenance": {key: {"source": "user"} for key in ("estimated_year_from", "estimate_currency", "description")}}
        merge_machine_reference(result, reference(), snapshot)
        self.assertEqual(result["data"], {})
        self.assertEqual(result["category"], "Excavadoras")

    def test_new_owner_identity_or_market_invalidates_a_prior_reference(self):
        value = reference()
        self.assertTrue(ai_reference_identity_matches(DATA, value))
        self.assertFalse(ai_reference_identity_matches({**DATA, "model": "320DL"}, value))
        self.assertFalse(ai_reference_identity_matches({**DATA, "location_country": "México"}, value))
        self.assertFalse(ai_reference_identity_matches({**DATA, "condition": "Para reparación"}, value))
        self.assertFalse(ai_reference_identity_matches({**DATA, "operating_status": "No funciona (declarado por el propietario)"}, value))
        self.assertFalse(ai_reference_identity_matches({**DATA, "hours": 5500}, value))
        self.assertFalse(ai_reference_identity_matches({**DATA, "hours": 0}, value))

    def test_technical_correction_invalidates_a_prior_summary_and_estimate(self):
        data = {**DATA, "power": "100 kW"}
        value = normalize_reference(proposal(), IDENTITY, data, None, ["Excavadoras"])
        self.assertTrue(ai_reference_identity_matches(data, value))
        self.assertFalse(ai_reference_identity_matches({**data, "power": "90 kW"}, value))

    def test_ambiguous_serial_never_causes_model_or_price_invention(self):
        client = Mock()
        snapshot = {"data": {"serial": "001234567"}, "provenance": {"serial": {"source": "user"}}}
        value, usage = complete_machine_reference(client, "gpt-4.1-mini", {"data": {}, "provenance": {}}, snapshot)
        self.assertIsNone(value)
        self.assertEqual(usage.input_tokens, 0)
        client.responses.parse.assert_not_called()
        self.assertIn("model", missing_fields(snapshot["data"]))

    def test_final_call_is_bounded_and_rechecks_consent(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=proposal(),
            usage=SimpleNamespace(input_tokens=100, output_tokens=60))
        snapshot = {"data": DATA, "provenance": {key: {"source": "user"} for key in DATA}}
        value, usage = complete_machine_reference(client, "gpt-4.1-mini", {"data": {}, "provenance": {}}, snapshot,
            allowed=Mock(side_effect=[True, False]), allowed_categories=["Excavadoras"])
        self.assertIsNone(value)
        self.assertEqual((usage.input_tokens, usage.output_tokens), (100, 60))
        self.assertFalse(client.responses.parse.call_args.kwargs["store"])

    def test_complete_human_fields_do_not_purchase_an_unusable_summary(self):
        client = Mock()
        values = {**DATA, "estimated_year_from": 2006, "estimated_year_to": 2015,
                  "estimate_min": 40000, "estimate_max": 80000, "estimate_currency": "USD",
                  "description": "Descripción aprobada por el propietario."}
        snapshot = {"category": "Excavadoras", "data": values,
                    "provenance": {key: {"source": "user"} for key in values}}
        value, usage = complete_machine_reference(client, "gpt-4.1-mini", {"data": {}, "provenance": {}}, snapshot,
            allowed_categories=["Excavadoras"])
        self.assertIsNone(value)
        self.assertEqual(usage.input_tokens, 0)
        client.responses.parse.assert_not_called()

    def test_ambiguous_technical_reading_cannot_anchor_or_block_model_estimates(self):
        import json
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=proposal(),
            usage=SimpleNamespace(input_tokens=100, output_tokens=60))
        result = {"data": {**DATA, "power": "100 kW"}, "provenance": {
            key: {"source": "image", "review": "clear" if key != "power" else "needs_review", "component": "machine"}
            for key in (*DATA, "power")}}
        value, _ = complete_machine_reference(client, "gpt-4.1-mini", result, allowed_categories=["Excavadoras"])
        self.assertNotIn("power", json.loads(client.responses.parse.call_args.kwargs["input"])["accepted_data"])
        self.assertIsNone(value["identity"]["technical_context"]["power"])
        self.assertTrue(ai_reference_identity_matches(DATA, value))
        self.assertEqual(value["fields"]["estimate_min"], "45000.00")


@override_settings(OPENAI_API_KEY="test-only", OPENAI_MODEL="gpt-4.1-mini")
class SerialCompletionPipelineTests(TestCase):
    def setUp(self):
        Category.objects.create(name="Excavadoras", slug="excavadoras", active=True)
        self.user = User.objects.create_user(email="serial-completion@example.com", password="test-only-password")
        self.machine = Machine.objects.create(owner=self.user,
            data={**DATA, "serial": "CAT0320DTEST12345"},
            provenance={key: {"source": "user", "review": "confirmed"} for key in (*DATA, "serial")})
        PlatformSettings.objects.create(pk=1, ai_enabled=True, ai_daily_token_limit=500000)

    def test_serial_description_route_now_runs_valuation_and_fills_missing_reference(self):
        with patch("openai.OpenAI") as provider, patch("portal.processing.research_machine",
                return_value=(empty_research("no_results"), UsageTotals())), patch("portal.processing.estimate_machine",
                return_value=(_seal(_empty(IDENTITY, "No comparables")), UsageTotals())) as estimate:
            provider.return_value.responses.parse.return_value = SimpleNamespace(status="completed",
                output_parsed=proposal(), usage=SimpleNamespace(input_tokens=140, output_tokens=80))
            job = enqueue_analysis(self.machine, self.user, mode="description", research=True, authorize_ai=True)
            self.assertTrue(process_next_job())
            job.refresh_from_db()
            self.assertEqual(job.status, "completed")
            estimate.assert_called_once()
            self.assertTrue(job.result["identifier_only"])
            self.assertEqual(job.result["data"]["estimate_min"], "45000.00")
            self.assertEqual(job.result["data"]["estimated_year_from"], 2006)
            self.assertEqual(job.result["completion"]["missing_fields"], [])
            self.assertEqual(provider.return_value.responses.parse.call_count, 1)
            self.assertNotIn("CAT0320DTEST12345", provider.return_value.responses.parse.call_args.kwargs["input"])

    def test_reservation_covers_each_serial_completion_request(self):
        for model in ("gpt-4.1-mini", "gpt-5.6-luna"):
            self.assertEqual(_reservation(0, "description", True, research_description_only=True, model=model),
                             research_reservation(model) + valuation_reservation(model) + completion_reservation(model))

    @override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_URL="https://example.invalid", STORAGES={
        "default": {"BACKEND": "portal.storage.PrivateStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_serial_alone_recovers_identity_applies_ranges_and_shares_complete_sheet(self):
        import json
        from portal.models import PreparedShare
        serial = self.machine.data["serial"]
        self.machine.data = {"serial": serial}
        self.machine.provenance = {"serial": {"source": "user", "review": "confirmed"}}
        self.machine.save()
        evidence = f"Caterpillar 320D, número de serie {serial}."
        url = "https://www.cat.com/equipment/320d.html"
        identity = {"brand": None, "model": None, "serial": serial}
        fields = [ResearchField(key=key, value=value, scope="exact_serial", source_url=url,
            evidence=evidence, matched_serial=serial, matched_brand="Caterpillar", matched_model="320D")
            for key, value in DATA.items()]
        researched = normalize_research(ResearchExtraction(fields=fields), identity, "exact_serial",
            [{"url": url, "title": "Caterpillar 320D"}], evidence, citations={url: [evidence]})
        self.assertEqual({field["key"] for field in researched["fields"]}, {"brand", "model"})
        with patch("openai.OpenAI") as provider, patch("portal.processing.research_machine",
                return_value=(researched, UsageTotals())), patch("portal.processing.estimate_machine",
                return_value=(_seal(_empty(IDENTITY, "No comparables")), UsageTotals())):
            provider.return_value.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=proposal(),
                usage=SimpleNamespace(input_tokens=180, output_tokens=90))
            job = enqueue_analysis(self.machine, self.user, mode="description", research=True, authorize_ai=True,
                auto_apply=True, expected_revision=self.machine.revision)
            self.assertTrue(process_next_job())
        job.refresh_from_db()
        self.machine.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(self.machine.data["brand"], "Caterpillar")
        self.assertEqual(self.machine.data["model"], "320D")
        self.assertEqual(self.machine.data["estimate_min"], 45000)
        self.assertEqual(self.machine.data["estimated_year_from"], 2006)
        self.assertEqual(self.machine.category.name, "Excavadoras")
        self.assertEqual(len(self.machine.data["description"].splitlines()), 4)
        self.client.force_login(self.user)
        preview = self.client.get(f"/panel/maquinarias/{self.machine.pk}/ficha/")
        self.assertContains(preview, "Rango de precio estimado")
        shared = self.client.post(f"/api/maquinarias/{self.machine.pk}/compartir/",
            json.dumps({"revision": self.machine.revision}), content_type="application/json")
        self.assertEqual(shared.status_code, 200, shared.content)
        public = self.client.get(f"/s/{PreparedShare.objects.get().code}/")
        self.assertContains(public, "Rango de año estimado")
        self.assertNotContains(public, "Pendiente")

    def test_three_photos_fit_the_unchanged_default_daily_budget(self):
        from portal.tests.test_processing import photo
        from portal.processing import ingest_asset
        import tempfile
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media, OPENAI_MODEL="gpt-5.6-luna"):
            for color in ("navy", "red", "white"):
                ingest_asset(self.machine, self.user, photo(color=color))
            PlatformSettings.objects.filter(pk=1).update(ai_daily_token_limit=200000)
            job = enqueue_analysis(self.machine, self.user, research=True, authorize_ai=True)
            self.assertEqual(len(job.asset_ids), 3)
            self.assertEqual(job.reserved_tokens, 199100)
            self.assertEqual(PlatformSettings.objects.get(pk=1).ai_daily_token_limit, 200000)

    def test_applied_visual_classification_keeps_complete_ranges_and_summary(self):
        from portal.models import Asset
        from portal.tests.test_image_relevance import field, observation, parsed
        self.machine.category = Category.objects.get(slug="excavadoras")
        self.machine.save()
        Asset.objects.create(machine=self.machine, kind="image", purpose="general", processing_status="ready",
            original="test/unused.jpg", preview="test/unused.jpg", size=1, mime_type="image/jpeg", sha256="a" * 64)
        classification = {**field("undercarriage", "crawler", "image_001", "visual_proposal"), "review": "needs_review"}
        reading = parsed([observation("image_001", category="Excavadoras")],
            [field("brand", "Caterpillar", "image_001"), field("model", "320D", "image_001"), classification])
        with patch("openai.OpenAI") as provider, patch("portal.processing._image_input",
                return_value={"type": "input_image", "image_url": "data:test"}), patch("portal.processing.research_machine",
                return_value=(empty_research("no_results"), UsageTotals())), patch("portal.processing.estimate_machine",
                return_value=(_seal(_empty(IDENTITY, "No comparables")), UsageTotals())):
            provider.return_value.responses.parse.side_effect = [
                SimpleNamespace(status="completed", output_parsed=reading, usage=SimpleNamespace(input_tokens=180, output_tokens=90)),
                SimpleNamespace(status="completed", output_parsed=proposal(), usage=SimpleNamespace(input_tokens=180, output_tokens=90))]
            job = enqueue_analysis(self.machine, self.user, research=True, authorize_ai=True,
                auto_apply=True, expected_revision=self.machine.revision)
            self.assertTrue(process_next_job())
        self.machine.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(self.machine.data["undercarriage"], "crawler")
        self.assertEqual(job.result["ai_reference"]["identity"]["completion_context"]["undercarriage"], "crawler")
        self.assertEqual(self.machine.data["estimate_min"], 45000)
        self.assertEqual(self.machine.data["estimated_year_from"], 2006)
        self.assertEqual(len(self.machine.data["description"].splitlines()), 4)

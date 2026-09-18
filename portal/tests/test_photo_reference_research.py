from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from portal.research import UsageTotals, empty_research, is_validated_web_field, merge_research, research_machine


PRODUCT_URL = "https://develon-ce.cl/product/excavadora-sobre-orugas-dx300lc-7-develon/"
IMAGE_URL = "https://develon-ce.cl/wp-content/uploads/dx300.png"


def visual_result(model="", *, model_meta=None):
    provenance = {"brand": {"source": "image", "review": "clear", "component": "machine"}}
    if model_meta is not None:
        provenance["model"] = model_meta
    data = {"brand": "DEVELON"}
    if model:
        data["model"] = model
    else:
        data["model"] = ""
    return {"data": data, "provenance": provenance, "category": "Excavadoras",
            "fields": [], "warnings": []}


def photo_match(model="DX300LC-7", *, asset_id="42", source_url=PRODUCT_URL):
    return {"model": model, "source_url": source_url, "image_url": IMAGE_URL,
            "score": 0.998, "photo_sha256": "a" * 64, "image_sha256": "b" * 64,
            "source_title": "Índice público", "origin": "direct_verified_catalog_photo_match",
            "asset_id": asset_id}


def product_reference(model="DX300LC-7"):
    from portal.research import ResearchField
    title = "Excavadora Sobre Orugas DX300LC-7 - DEVELON Chile"
    evidence = f"{title}; ficha técnica visible en la página del producto."
    return {"model": model, "source_url": PRODUCT_URL, "source_title": title,
            "evidence": evidence, "fields": [ResearchField(
                key="power", value="266.9 hp", scope="model", source_url=PRODUCT_URL,
                evidence=f"{title}: Potencia del motor: 266.9 hp", matched_serial=None,
                matched_brand="DEVELON", matched_model=model)]}


def regional_product_reference(model="DX300LC-7"):
    from portal.research import ResearchField
    title = "Excavadora Sobre Orugas DX300LC-7 - DEVELON Chile"
    rows = {
        "weight": ("Peso Operativo", "31.5 t"),
        "capacity": ("Capacidad del Balde", "1.60 m3"),
        "power": ("Potencia del Motor", "266.9 hp @ 1,900 rpm"),
        "engine": ("Motor", "DEVELON DL08 (6 cilindros)"),
        "digging_depth": ("Profundidad máxima de excavación", "7.4 m"),
        "hydraulic_system": ("Sistema hidráulico", "Closed center"),
    }
    return {"model": model, "source_url": PRODUCT_URL, "source_title": title,
            "evidence": f"{title}; ficha técnica visible en la página del producto.",
            "fields": [ResearchField(
                key=key, value=value, scope="model", source_url=PRODUCT_URL,
                evidence=f"{title}: {label}: {value}", matched_serial=None,
                matched_brand="DEVELON", matched_model=model)
                for key, (label, value) in rows.items()]}


class PhotoReferenceResearchTests(SimpleTestCase):
    def followup(self, *args, **kwargs):
        return ({"status": "completed", "identity": {"brand": "DEVELON", "model": "DX300LC-7"},
                 "fields": [], "sources": [], "warnings": [], "usage": UsageTotals().as_dict()}, UsageTotals())

    def test_match_becomes_signed_model_web_reference_and_runs_specs_followup(self):
        client = Mock()
        with patch("portal.research_photo_match.match_catalog_photo", return_value=photo_match()), \
             patch("portal.research_catalog.catalog_product_fields", return_value=product_reference()), \
             patch("portal.research_pipeline.research_identified_machine", side_effect=self.followup):
            research, _ = research_machine(
                client, "gpt-5.6-luna", visual_result(),
                allowed_categories=["Excavadoras"],
                photo_inputs=[{"asset_id": "42", "bytes": b"synthetic-png"}],
            )

        model_field = next(field for field in research["fields"] if field["key"] == "model")
        self.assertEqual(model_field["value"], "DX300LC-7")
        self.assertEqual(model_field["scope"], "model")
        self.assertEqual(model_field["source_url"], PRODUCT_URL)
        self.assertEqual(research["photo_match"]["source_url"], PRODUCT_URL)
        self.assertIn("pendiente de confirmar", " ".join(research["warnings"]))
        merged = merge_research({"data": {}, "provenance": {}, "fields": [], "warnings": []}, research)
        meta = merged["provenance"]["model"]
        self.assertEqual(meta["source"], "web")
        self.assertEqual(meta["review"], "needs_review")
        self.assertEqual(meta["scope"], "model")
        self.assertTrue(is_validated_web_field(merged, "model", "DX300LC-7", meta))

    def test_regional_product_rows_remain_signed_without_followup(self):
        with patch("portal.research_photo_match.match_catalog_photo", return_value=photo_match()), \
             patch("portal.research_catalog.catalog_product_fields", return_value=regional_product_reference()), \
             patch("portal.research_pipeline.research_identified_machine", side_effect=self.followup):
            research, _ = research_machine(
                Mock(), "gpt-5.6-luna", visual_result(),
                allowed_categories=["Excavadoras"],
                photo_inputs=[{"asset_id": "42", "bytes": b"synthetic-png"}],
            )
        self.assertEqual(len(research["fields"]), 7)
        self.assertEqual({field["key"] for field in research["fields"]},
                         {"model", "weight", "capacity", "power", "engine",
                          "digging_depth", "hydraulic_system"})
        self.assertTrue(research.get("proof"))

    def test_existing_model_and_confirmed_empty_model_are_never_overwritten(self):
        matcher = Mock(side_effect=AssertionError("photo matcher should not run"))
        with patch("portal.research_photo_match.match_catalog_photo", matcher), \
             patch("portal.research._research_general_context", return_value=(
                 {"fields": [], "warnings": []}, UsageTotals())), \
             patch("portal.research_pipeline.research_identified_machine", return_value=(
                 {"status": "completed", "fields": [], "sources": [], "warnings": [], "usage": UsageTotals().as_dict()}, UsageTotals())):
            research_machine(client=Mock(), model="gpt-5.6-luna", result=visual_result("DX200"),
                             allowed_categories=["Excavadoras"], photo_inputs=[{"bytes": b"x"}])
        with patch("portal.research_photo_match.match_catalog_photo", matcher), \
             patch("portal.research._research_general_context", return_value=(
                 {"fields": [], "warnings": []}, UsageTotals())):
            research_machine(client=Mock(), model="gpt-5.6-luna",
                             result=visual_result(),
                             snapshot={"data": {"model": ""},
                                       "provenance": {"model": {"source": "user", "review": "confirmed"}}},
                             allowed_categories=["Excavadoras"], photo_inputs=[{"bytes": b"x"}])
        matcher.assert_not_called()

    def test_conflicting_photo_models_do_not_apply_a_winner(self):
        client = Mock()
        responses = iter([photo_match("DX300LC-7"), photo_match("DX255LC-7")])
        empty = SimpleNamespace(status="completed", output_text="", output=[], usage=SimpleNamespace(input_tokens=0, output_tokens=0))
        with patch("portal.research_photo_match.match_catalog_photo", side_effect=lambda *args, **kwargs: next(responses)), \
             patch("portal.research_catalog.catalog_product_fields") as product, \
             patch("portal.research._direct_catalog_context", return_value=None), \
             patch.object(client.responses, "create", return_value=empty):
            research, _ = research_machine(
                client, "gpt-5.6-luna", visual_result(), allowed_categories=["Excavadoras"],
                photo_inputs=[{"bytes": b"one"}, {"bytes": b"two"}],
            )
        product.assert_not_called()
        self.assertNotIn("model", {field["key"] for field in research.get("fields", [])})

    def test_cancellation_after_match_discards_reference_before_product_fetch(self):
        allowed = Mock(side_effect=[True, False])
        with patch("portal.research_photo_match.match_catalog_photo", return_value=photo_match()), \
             patch("portal.research_catalog.catalog_product_fields") as product:
            research, _ = research_machine(
                Mock(), "gpt-5.6-luna", visual_result(), allowed=allowed,
                allowed_categories=["Excavadoras"], photo_inputs=[{"bytes": b"one"}],
            )
        product.assert_not_called()
        self.assertTrue(research["diagnostics"]["cancelled"])
        self.assertEqual(research["fields"], [])

    def test_cancellation_after_specs_followup_preserves_consumed_usage(self):
        allowed = Mock(side_effect=[True, True, True, False])
        spent = UsageTotals(input_tokens=123, output_tokens=45)
        followup = ({"status": "completed", "fields": [], "sources": [], "warnings": [],
                     "usage": spent.as_dict()}, spent)
        with patch("portal.research_photo_match.match_catalog_photo", return_value=photo_match()), \
             patch("portal.research_catalog.catalog_product_fields", return_value=product_reference()), \
             patch("portal.research_pipeline.research_identified_machine", return_value=followup):
            research, usage = research_machine(
                Mock(), "gpt-5.6-luna", visual_result(), allowed=allowed,
                allowed_categories=["Excavadoras"], photo_inputs=[{"bytes": b"one"}],
            )
        self.assertTrue(research["diagnostics"]["cancelled"])
        self.assertEqual(research["fields"], [])
        self.assertEqual((usage.input_tokens, usage.output_tokens), (123, 45))
        self.assertEqual((research["usage"]["input_tokens"], research["usage"]["output_tokens"]), (123, 45))

    def test_general_search_runs_before_direct_catalog_fallback(self):
        events = []
        client = Mock()
        client.responses.create.side_effect = lambda **kwargs: (
            events.append("general"),
            SimpleNamespace(status="completed", output_text="", output=[],
                             usage=SimpleNamespace(input_tokens=0, output_tokens=0)),
        )[1]
        direct = empty_research("general_context", {"brand": "DEVELON", "model": None,
                                                      "category": "Excavadoras"}, "category")

        def fallback(*args, **kwargs):
            events.append("direct")
            return direct

        with patch("portal.research._direct_catalog_context", side_effect=fallback):
            research_machine(client, "gpt-5.6-luna", visual_result(),
                             allowed_categories=["Excavadoras"])
        self.assertEqual(events, ["general", "direct"])

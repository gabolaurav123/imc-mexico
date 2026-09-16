"""Public reading aids and citations must not reintroduce a private identifier."""
from copy import deepcopy
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from portal.models import Machine, MachineVersion, Publication, User
from portal.views import safe_public_data, sheet_context


@override_settings(SECURE_SSL_REDIRECT=False, PRIVATE_S3_BUCKET="",
    STORAGES={"default": {"BACKEND": "portal.storage.PrivateStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PublicSheetIdentifierTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="public-identifiers@example.invalid",
                                              is_test=True, advertiser_status="approved")
        self.original_data = {"serial": "SYNTHETIC1234", "power": "70 kW SYNTHETIC1234",
                              "weight": "90 kg", "hours": 0,
                              "description": "Equipo sintético para verificar la privacidad."}
        self.machine = Machine.objects.create(owner=self.owner, title="Equipo de prueba aprobado",
                                              data=deepcopy(self.original_data))
        self.snapshot = {"title": self.machine.title, "data": deepcopy(self.original_data),
                         "provenance": {"power": {"source": "plate", "review": "clear"}},
                         "asset_ids": [], "public_asset_ids": [], "contact_authorized": False}
        self.version = MachineVersion.objects.create(machine=self.machine, number=1,
                                                       created_by=self.owner, data=deepcopy(self.snapshot))
        self.machine.approved_version = self.version
        self.machine.save(update_fields=["approved_version"])
        self.publication = Publication.objects.create(machine=self.machine, version=self.version,
            destination="share", enabled=True, status="published")

    def test_public_render_uses_approved_exclusions_and_omits_embedded_serial_everywhere(self):
        # Live changes must neither expose draft values nor erase snapshot exclusions.
        self.machine.title = "Título privado posterior"
        self.machine.data = {"serial": "LIVEDRAFT5678", "power": "88 kW", "weight": "200 kg"}
        self.machine.save(update_fields=["title", "data"])
        response = self.client.get(f"/ficha/{self.publication.token}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Equipo de prueba aprobado")
        self.assertContains(response, "90 kg")
        for private in ("SYNTHETIC1234", "LIVEDRAFT5678", "Título privado posterior", "88 kW", "200 kg"):
            self.assertNotContains(response, private)
        context = response.context
        self.assertNotIn("power", context["data"])
        self.assertNotIn("power", context["field_origins"])
        self.assertNotIn("serial", context["data"])
        self.assertEqual(context["data"]["hours"], 0)
        self.assertEqual(context["provenance"], {})
        for collection in ("extra_fields", "technical_interpretation", "web_references"):
            self.assertNotIn("SYNTHETIC1234", json.dumps(context[collection]))
        self.assertEqual([item["key"] for item in context["technical_interpretation"]], ["weight"])
        self.version.refresh_from_db()
        self.assertEqual(self.version.data, self.snapshot)

    def test_internal_snapshot_and_current_draft_remain_intact(self):
        context = sheet_context(self.machine, self.version)
        self.assertEqual(context["data"], self.original_data)
        self.assertEqual(next(item["value"] for item in context["extra_fields"] if item["key"] == "power"),
                         "70 kW SYNTHETIC1234")
        self.assertEqual(context["provenance"], self.snapshot["provenance"])
        self.assertEqual([item["key"] for item in context["technical_interpretation"]], ["weight"])
        self.machine.refresh_from_db()
        self.version.refresh_from_db()
        self.assertEqual(self.machine.data, self.original_data)
        self.assertEqual(self.version.data, self.snapshot)

    def test_normalized_serial_and_vin_are_excluded_without_losing_safe_zero_values(self):
        snapshot = {"data": {"serial": "UNIT-12345", "vin": "VIN-98765",
            "power": "70 kW ｕｎｉｔ １２３４５", "engine": "motor vin 98765",
            "country_of_origin": "UNIT%2D12345", "weight": 0, "hours": 0, "capacity": "5 L"}}
        original = deepcopy(snapshot)
        self.assertEqual(safe_public_data(snapshot), {"weight": 0, "hours": 0, "capacity": "5 L"})
        self.assertEqual(snapshot, original)

    def test_filtered_technical_field_cannot_reappear_in_public_web_references(self):
        references = [{"field": "power", "value": self.original_data["power"]},
                      {"field": "weight", "value": "90 kg"}]
        with patch("portal.services.public_web_references", return_value=references) as helper:
            context = sheet_context(self.machine, self.version, public=True)
        # Source validation still receives the original immutable identifiers.
        self.assertEqual(helper.call_args.args[0], self.snapshot)
        self.assertEqual(context["web_references"], [{"field": "weight", "value": "90 kg"}])
        self.assertNotIn("SYNTHETIC1234", json.dumps(context["web_references"]))

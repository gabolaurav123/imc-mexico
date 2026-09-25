from django.core.management import call_command
from django.test import TestCase

from portal.knowledge import retrieve_technical_references
from portal.models import Category, Machine, TechnicalReference, User
from portal.public_data import public_projection
from portal.services import DATA_FIELDS, save_draft
from portal.category_profiles import PROFILES


class TechnicalKnowledgeAliasTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(slug="plataformas-elevadoras", name="Plataformas", active=True)
        self.reference = TechnicalReference.objects.create(
            category=self.category, brand="JLG", model="450AJ", variant="", market="US",
            source="https://manufacturer.example/450aj", source_title="Manufacturer 450AJ",
            retrieved_at="2026-09-25", review=TechnicalReference.Review.APPROVED, active=True,
            provenance={"authority": "manufacturer", "scope": "model", "model_aliases": ["450 AJ"]},
            specs={"capacity": {"value": "550 lb", "evidence": "JLG 450AJ: 550 lb."}},
        )

    def snapshot(self, model, variant=""):
        return {"data": {"brand": "JLG", "model": model, "variant": variant,
                          "location_country": "United States"},
                "provenance": {"variant": {"source": "user", "review": "confirmed"},
                               "location_country": {"source": "user", "review": "confirmed"}}}

    def test_exact_documented_alias_retrieves_the_same_model(self):
        self.assertEqual(retrieve_technical_references(self.snapshot("450 AJ"), self.category), [self.reference])

    def test_partial_or_variant_like_strings_never_match_an_alias(self):
        self.assertEqual(retrieve_technical_references(self.snapshot("450AJ HC3"), self.category), [])
        self.assertEqual(retrieve_technical_references(self.snapshot("450"), self.category), [])

    def test_alias_does_not_bypass_market_or_variant_compatibility(self):
        mexico = self.snapshot("450 AJ")
        mexico["data"]["location_country"] = "México"
        self.assertEqual(retrieve_technical_references(mexico, self.category), [])
        self.reference.variant = "HC3"
        self.reference.save(update_fields=["variant"])
        self.assertEqual(retrieve_technical_references(self.snapshot("450 AJ"), self.category), [])


class TechnicalKnowledgeExpansionImportTests(TestCase):
    def test_profile_fields_use_the_storable_catalogue_schema(self):
        profile_fields = {field["key"] for profile in PROFILES.values() for field in profile["fields"]}
        self.assertLessEqual(profile_fields, DATA_FIELDS)

    def test_new_manufacturer_files_import_pending_and_inactive(self):
        for slug in (
            "excavadoras", "compactadores", "plataformas-elevadoras",
            "montacargas", "minicargadores", "motoniveladoras",
        ):
            Category.objects.create(slug=slug, name=slug, active=True)

        call_command("import_technical_knowledge", path="knowledge/catalogo_tecnico_ampliado_2026-09-25.json")
        call_command("import_technical_knowledge", path="knowledge/catalogo_tecnico_cobertura_2026-09-25.json")

        references = TechnicalReference.objects.all()
        self.assertEqual(references.count(), 50)
        self.assertEqual(references.filter(active=True).count(), 0)
        self.assertEqual(references.filter(review=TechnicalReference.Review.PENDING).count(), 50)
        self.assertEqual(sum(len(reference.specs) for reference in references), 204)

    def test_catalogue_fields_are_storable_and_publicly_allowlisted(self):
        user = User.objects.create_user(email="catalogue-fields@example.invalid", password=None)
        machine = Machine.objects.create(owner=user, data={})
        values = {"platform_height": "45 ft", "horizontal_outreach": "25 ft",
                  "drum_diameter": "42 in", "blade_width": "14 ft"}

        machine = save_draft(machine, user, {"data": values}, machine.revision)

        self.assertEqual({key: machine.data[key] for key in values}, values)
        self.assertEqual(public_projection({"data": machine.data}), values)

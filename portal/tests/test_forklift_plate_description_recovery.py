"""Plate facts can recover a useful forklift description without re-running AI."""
from copy import deepcopy

from django.test import SimpleTestCase

from portal.technical_description import description_projection, recovered_technical_description


PLATE_DATA = {
    # The model remains deliberately absent: the final character of the OCR
    # candidate was uncertain in the real plate result that motivated this case.
    "brand": "CATERPILLAR",
    "serial": "A2EC262313",
    "front_tire_size": "21X7X15",
    "rear_tire_size": "16X6X10.5",
    "mast_tilt": "MAX REARWARD 6 deg.",
    "load_tire_tread": "34.5 in.",
    "description": "Montacargas CATERPILLAR.",
}
PLATE_PROVENANCE = {
    key: {"source": "plate", "review": "clear", "component": "machine"}
    for key in ("front_tire_size", "rear_tire_size", "mast_tilt", "load_tire_tread")
}
PLATE_PROVENANCE.update({
    "brand": {"source": "plate", "review": "clear", "component": "machine"},
    "serial": {"source": "plate", "review": "clear", "component": "machine"},
    "description": {"source": "system", "review": "needs_review"},
    # An uncertain OCR model is intentionally not usable as a plate fact.
    "model": {"source": "plate", "review": "uncertain", "component": "machine"},
})


class ForkliftPlateDescriptionRecoveryTests(SimpleTestCase):
    def test_clear_forklift_plate_fields_replace_generic_automatic_copy(self):
        original = deepcopy((PLATE_DATA, PLATE_PROVENANCE))

        description = recovered_technical_description(
            PLATE_DATA, PLATE_PROVENANCE, category="Montacargas"
        )

        self.assertEqual(description.splitlines(), [
            "Llantas delanteras según la placa: 21X7X15.",
            "Llantas traseras según la placa: 16X6X10.5.",
            "Inclinación del mástil según la placa: MAX REARWARD 6 deg.",
            "Entrecentros de llantas de carga según la placa: 34.5 in.",
        ])
        self.assertEqual(
            description_projection(PLATE_DATA, PLATE_PROVENANCE, category="Montacargas")["description"],
            description,
        )
        self.assertNotIn("CATERPILLAR", description)
        self.assertNotIn("A2EC262313", description)
        self.assertEqual((PLATE_DATA, PLATE_PROVENANCE), original)

    def test_removal_correction_and_conflict_recompute_only_current_accepted_plate_facts(self):
        removed = {**PLATE_DATA, "front_tire_size": None}
        without_front = recovered_technical_description(removed, PLATE_PROVENANCE, category="Montacargas")
        self.assertEqual(without_front.splitlines(), [
            "Llantas traseras según la placa: 16X6X10.5.",
            "Inclinación del mástil según la placa: MAX REARWARD 6 deg.",
            "Entrecentros de llantas de carga según la placa: 34.5 in.",
        ])
        self.assertNotIn("21X7X15", without_front)

        corrected_meta = deepcopy(PLATE_PROVENANCE)
        corrected_meta["front_tire_size"] = {"source": "user", "review": "confirmed"}
        corrected = recovered_technical_description(
            {**PLATE_DATA, "front_tire_size": "22X7X15"}, corrected_meta, category="Montacargas"
        )
        self.assertIn("Llantas delanteras según la ficha del anunciante: 22X7X15.", corrected)
        self.assertNotIn("21X7X15", corrected)

        conflicted_meta = deepcopy(PLATE_PROVENANCE)
        conflicted_meta["mast_tilt"]["review_reason"] = "conflicting_reading"
        self.assertNotIn(
            "Inclinación del mástil",
            recovered_technical_description(removed, conflicted_meta, category="Montacargas"),
        )
        self.assertEqual(
            recovered_technical_description(
                {**removed, "load_tire_tread": None}, conflicted_meta, category="Montacargas"
            ),
            "",
        )

"""Correct two untouched bundled electric-platform references without reapproval."""
from copy import deepcopy

from django.db import migrations


# Exact pre-correction release records. Do not read the live bundle from a
# historical migration: later catalogue changes must not change this repair.
ORIGINAL_RECORDS = [{'category_slug': 'plataformas-elevadoras',
  'brand': 'JLG',
  'model': 'E450AJ',
  'market': 'US',
  'source': 'https://www.jlg.com/equipment/boom-lifts/articulating/electric-hybrid/e450-series/E450AJ',
  'source_title': 'E450AJ Electric Boom Lift | JLG',
  'source_version': 'US product page; E450AJ',
  'retrieved_at': '2026-09-25',
  'provenance': {'authority': 'manufacturer',
                 'scope': 'model',
                 'type_es': 'plataforma articulada eléctrica',
                 'type_en': 'electric articulating boom lift',
                 'model_aliases': ['E 450 AJ'],
                 'market_scope': 'US product configuration',
                 'note': 'La página describe una plataforma de brazo articulado eléctrica y menciona jib '
                         'opcional. Capacidad, alcance, altura, pendiente y giro son límites de la '
                         'configuración publicada; no prueban que una unidad tenga el jib u otras opciones.'},
  'specs': {'power': {'value': 'electric', 'evidence': 'JLG E450AJ: Electric Boom Lift.'},
            'capacity': {'value': '500 lb', 'evidence': 'JLG E450AJ: Platform Capacity Unrestricted 500 lb.'},
            'platform_height': {'value': '45 ft', 'evidence': 'JLG E450AJ: Max Platform Height 45 ft 0 in.'},
            'horizontal_outreach': {'value': '22 ft 5 in',
                                    'evidence': 'JLG E450AJ: Horizontal Outreach 22 ft 5 in.'},
            'gradeability': {'value': '30%', 'evidence': 'JLG E450AJ: Gradeability 30%.'},
            'swing': {'value': '360°', 'evidence': 'JLG E450AJ: Swing 360°.'}}},
 {'category_slug': 'plataformas-elevadoras',
  'brand': 'JLG',
  'model': 'EC600SJ',
  'market': 'US',
  'source': 'https://www.jlg.com/en-br/equipment/boom-lifts/telescopic/electric-hybrid/ec600-and-h600-series/ec600sj',
  'source_title': 'EC600SJ Electric Boom Lift | JLG',
  'source_version': 'Brazil product page; model data shown in imperial',
  'retrieved_at': '2026-09-25',
  'provenance': {'authority': 'manufacturer',
                 'scope': 'model',
                 'type_es': 'plataforma telescópica eléctrica',
                 'type_en': 'electric telescopic boom lift',
                 'model_aliases': ['EC 600 SJ'],
                 'note': 'La página consultada es regional Brasil; se conserva esa cobertura y sus valores '
                         'originales. No acredita disponibilidad en México.'},
  'specs': {'power': {'value': 'electric',
                      'evidence': 'JLG EC600SJ: environmentally-friendly electric boom lift with zero '
                                  'emissions.'},
            'capacity': {'value': '500 lb',
                         'evidence': 'JLG EC600SJ: Platform Capacity Unrestricted 500 lb.'},
            'platform_height': {'value': '60 ft 3 in',
                                'evidence': 'JLG EC600SJ: Max Platform Height 60 ft 3 in.'},
            'horizontal_outreach': {'value': '43 ft 3 in',
                                    'evidence': 'JLG EC600SJ: Horizontal Outreach 43 ft 3 in.'},
            'gradeability': {'value': '45%', 'evidence': 'JLG EC600SJ: Gradeability 45%.'},
            'swing': {'value': '400°', 'evidence': 'JLG EC600SJ: Swing 400°.'}}}]


def correct_electric_power_fields(apps, schema_editor):
    Reference = apps.get_model("portal", "TechnicalReference")
    for original in ORIGINAL_RECORDS:
        expected = {
            "category__slug": original["category_slug"],
            **{key: original.get(key, "") for key in (
                "brand", "model", "variant", "generation", "market", "source",
                "source_title", "source_version", "retrieved_at")},
            "period_from": None, "period_to": None,
            "review": "approved", "active": True, "reviewed_by__isnull": True,
        }
        for reference in Reference.objects.using(schema_editor.connection.alias).select_for_update().filter(**expected):
            if reference.specs != original["specs"] or reference.provenance != original["provenance"]:
                continue
            corrected = deepcopy(reference.specs)
            corrected["fuel"] = corrected.pop("power")
            reference.specs = corrected
            reference.save(update_fields=["specs", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("portal", "0022_ai_usage_reset_50")]
    operations = [migrations.RunPython(correct_electric_power_fields, migrations.RunPython.noop)]

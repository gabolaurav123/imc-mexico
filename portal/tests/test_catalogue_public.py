from io import BytesIO

from django.test import TestCase
from pypdf import PdfReader

from portal.models import Category, Machine, MachineVersion, Publication, User


class PublicCatalogueTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="catalogue-owner@example.invalid",
                                              advertiser_status="approved", is_test=True)
        self.category = Category.objects.create(name="Excavadoras", slug="excavadoras", active=True)
        self.machine = Machine.objects.create(owner=self.owner, category=self.category, title="CAT 320", data={
            "brand": "CAT", "model": "320", "hours": 0, "year": 2018,
            "estimated_year_from": 2017, "estimated_year_to": 2019,
            "price": "125000", "currency": "USD", "location_country": "MX",
            "location_region": "Quintana Roo", "location_city": "Cancún", "undercarriage": "crawler",
            "preservation_condition": "good", "weight": "22000 kg", "digging_depth": "6.7 m", "description": "Equipo publicado.",
            "provenance": {"price": {"source": "user", "review": "confirmed"}},
        })
        self.version = self.make_version(1, self.machine.data)
        self.machine.approved_version = self.version
        self.machine.save(update_fields=["approved_version"])
        self.publication = Publication.objects.create(machine=self.machine, version=self.version,
                                                       destination="share", enabled=True, status="published")

    def make_version(self, number, data):
        return MachineVersion.objects.create(machine=self.machine, number=number, created_by=self.owner,
            data={"title": data.get("brand", "") + " " + data.get("model", ""), "category_name": "Excavadora",
                  "data": data, "provenance": data.get("provenance", {}), "public_asset_ids": []})

    def test_only_approved_enabled_public_snapshot_is_visible(self):
        response = self.client.get("/maquinaria/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CAT 320")
        # A later draft does not replace the approved snapshot in the catalogue.
        draft = self.make_version(2, {"brand": "DRAFT", "model": "999", "hours": 99})
        self.assertNotEqual(draft.pk, self.machine.approved_version_id)
        self.assertContains(self.client.get("/maquinaria/"), "CAT 320")
        self.assertNotContains(self.client.get("/maquinaria/"), "DRAFT 999")

    def test_public_empty_fields_have_no_rows_or_empty_headings(self):
        version = MachineVersion.objects.create(machine=self.machine, number=20, created_by=self.owner,
            data={'title':'Equipo', 'category_name':'', 'data':{'serial':'SECRET-UNIT',
                'location':'No indicada', 'operating_status':'Pendiente de confirmar'}, 'public_asset_ids':[]})
        self.machine.approved_version=version; self.machine.save(update_fields=['approved_version'])
        self.publication.version=version; self.publication.save(update_fields=['version'])
        response=self.client.get(f'/ficha/{self.publication.token}/')
        self.assertEqual(response.status_code,200)
        self.assertNotRegex(response.content.decode(),r'<h[1-6][^>]*>\s*</h[1-6]>')
        for text in ('SECRET-UNIT','No indicada','Pendiente de confirmar','País de fabricación'):
            self.assertNotContains(response,text)
        self.assertNotContains(response,'id="sheet-identification"')

    def test_public_partial_identification_displays_available_values_without_private_placeholders(self):
        examples=(
            ({'hours':0},'Horas de uso','0'),
            ({'price':0,'currency':'USD'},'Precio','0 USD'),
            ({'estimate_min':1000,'estimate_max':2000,'estimate_currency':'USD'},'Precio estimado','1000–2000 USD'),
            ({'estimated_year_from':2004},'Año aproximado','Desde 2004'),
            ({'estimated_year_to':2009},'Año aproximado','Hasta 2009'),
            ({'usage_condition':'Usada'},'Estado de uso aparente','Usada'),
            ({'location_country':'MX'},'País','MX'),
            ({'location_region':'Quintana Roo'},'Estado / provincia','Quintana Roo'),
            ({'location_city':'Cancún'},'Ciudad','Cancún'),
            ({'location':'Cancún, México'},'Ubicación','Cancún, México'),
        )
        for number,(values,label,value) in enumerate(examples,start=30):
            with self.subTest(values=values):
                version=MachineVersion.objects.create(machine=self.machine,number=number,created_by=self.owner,
                    data={'title':'Equipo','category_name':'','data':{**values,'serial':'PRIVATE-UNIT',
                        'notes':'PRIVATE-NOTES','operating_status':'Pendiente de confirmar'},'public_asset_ids':[]})
                self.machine.approved_version=version;self.machine.save(update_fields=['approved_version'])
                self.publication.version=version;self.publication.save(update_fields=['version'])
                response=self.client.get(f'/ficha/{self.publication.token}/')
                self.assertEqual(response.status_code,200)
                self.assertContains(response,'id="sheet-identification"')
                self.assertContains(response,f'<dt>{label}</dt>',html=True)
                self.assertContains(response,f'<dd>{value}</dd>',html=True)
                for hidden in ('PRIVATE-UNIT','PRIVATE-NOTES','Pendiente de confirmar'):
                    self.assertNotContains(response,hidden)

    def test_brief_sheet_keeps_essential_fields_and_structured_location_without_losing_specialized_data(self):
        self.client.force_login(self.owner)
        self.machine.data={**self.machine.data,'boom_configuration':'two_piece','power_type':'net'}
        self.machine.save(update_fields=['data'])
        response=self.client.get(f'/panel/maquinarias/{self.machine.pk}/ficha/')
        self.assertEqual(response.status_code,200)
        for label,value in (('País','MX'),('Estado / provincia','Quintana Roo'),('Ciudad','Cancún'),
                            ('Peso','22000 kg'),('Profundidad máxima de excavación','6.7 m'),('Horas de uso','0')):
            self.assertContains(response,f'<div><dt>{label}</dt><dd>{value}</dd></div>',html=True)
        # Specialized attributes remain translated and available to the editor,
        # snapshots and catalogue filters; the shared sheet presents essentials.
        fields={field['key']:field['value'] for field in response.context['extra_fields']}
        for key,value in (('undercarriage','Orugas'),('boom_configuration','Pluma de dos piezas'),('power_type','Potencia neta')):
            self.assertEqual(fields[key],value)
            self.assertNotContains(response,value)
        self.assertEqual(response.context['display_location'],'Cancún, Quintana Roo, MX')
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.data['boom_configuration'],'two_piece')
        self.assertEqual(self.machine.data['power_type'],'net')
        self.assertEqual(self.machine.data['undercarriage'],'crawler')

    def test_revoked_disabled_and_mismatched_publications_are_hidden(self):
        self.publication.enabled = False
        self.publication.save(update_fields=["enabled"])
        self.assertNotContains(self.client.get("/maquinaria/"), "CAT 320")
        self.publication.enabled = True
        self.publication.status = "disabled"
        self.publication.save(update_fields=["enabled", "status"])
        self.assertNotContains(self.client.get("/maquinaria/"), "CAT 320")

    def test_zero_hours_is_filterable_and_null_hours_is_not_zero(self):
        self.assertContains(self.client.get("/maquinaria/?hours_min=0"), "CAT 320")
        self.assertContains(self.client.get("/maquinaria/?year=2018&year_mode=exact"), "CAT 320")
        self.assertContains(self.client.get("/maquinaria/?year=2018&year_mode=approx"), "CAT 320")

    def test_year_range_filters_use_explicit_exact_or_approximate_semantics(self):
        self.assertContains(self.client.get("/maquinaria/?year_min=2018&year_max=2018"), "CAT 320")
        self.assertNotContains(self.client.get("/maquinaria/?year_min=2019&year_max=2020"), "CAT 320")
        # The declared 2017-2019 approximate period overlaps 2019, but not 2020.
        self.assertContains(self.client.get("/maquinaria/?year_min=2019&year_max=2020&year_mode=approx"), "CAT 320")
        self.assertNotContains(self.client.get("/maquinaria/?year_min=2020&year_max=2021&year_mode=approx"), "CAT 320")

    def test_invalid_year_ranges_and_price_without_currency_are_visible_and_safe(self):
        response = self.client.get("/maquinaria/?year=1650.5")
        self.assertContains(response, "El año debe ser un número entero.")
        self.assertNotContains(response, "CAT 320")
        response = self.client.get("/maquinaria/?year_min=2020&year_max=2019")
        self.assertContains(response, "El año desde no puede ser posterior al año hasta.")
        self.assertNotContains(response, "CAT 320")
        response = self.client.get("/maquinaria/?price_min=100000")
        self.assertContains(response, "Para filtrar por precio, elige una moneda.")
        self.assertNotContains(response, "CAT 320")
        response = self.client.get("/maquinaria/?hours_min=2&hours_max=1")
        self.assertContains(response, "El mínimo de horas no puede superar el máximo.")
        self.assertNotContains(response, "CAT 320")
        response = self.client.get("/maquinaria/?hours_min=-1")
        self.assertContains(response, "El mínimo de horas no puede ser negativo.")
        self.assertNotContains(response, "CAT 320")
        response = self.client.get("/maquinaria/?year=1e999999999")
        self.assertContains(response, "El año debe estar entre 1800 y 2200.")
        self.assertNotContains(response, "CAT 320")

    def test_enormous_numeric_exponents_return_a_warning_without_decimalfield_overflow(self):
        fields = (("hours_min", "horas"), ("price_min", "precio"),
                  ("weight_min", "peso"), ("depth_min", "profundidad"))
        for field, label in fields:
            with self.subTest(field=field):
                response = self.client.get("/maquinaria/", {field: "1e999999999", "currency": "USD"})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"El mínimo de {label} excede el límite permitido.")
                self.assertEqual(response.context["result_count"], 0)

    def test_catalogue_defaults_to_available_and_exposes_other_states_only_on_request(self):
        self.machine.availability = "sold"
        self.machine.save(update_fields=["availability"])
        default_response = self.client.get("/maquinaria/")
        self.assertNotContains(default_response, "CAT 320")
        self.assertContains(default_response, '<option value="available" selected>Disponibles</option>', html=True)
        self.assertContains(self.client.get("/maquinaria/?availability=sold"), "CAT 320")
        response = self.client.get("/maquinaria/?availability=all")
        self.assertContains(response, "CAT 320")

    def test_explicit_reserved_state_has_a_card_label_and_invalid_availability_defaults_safely(self):
        self.machine.availability = "reserved"
        self.machine.save(update_fields=["availability"])
        reserved = self.client.get("/maquinaria/?availability=reserved")
        self.assertEqual([card["publication"].pk for card in reserved.context["cards"]], [self.publication.pk])
        self.assertContains(reserved, "Reservada")
        invalid = self.client.get("/maquinaria/?availability=unknown")
        self.assertEqual(invalid.context["filters"]["availability"], "available")
        self.assertContains(invalid, "La disponibilidad solicitada no es válida")
        self.assertNotContains(invalid, "CAT 320")

    def test_price_currency_and_sort_fallback_warnings_are_visible(self):
        unknown_currency = self.client.get("/maquinaria/?currency=GBP&price_min=100000")
        self.assertContains(unknown_currency, "La moneda solicitada no es válida.")
        self.assertNotContains(unknown_currency, "CAT 320")
        no_currency_sort = self.client.get("/maquinaria/?sort=price_asc")
        self.assertEqual(no_currency_sort.context["filters"]["sort"], "latest")
        self.assertContains(no_currency_sort, "Para ordenar por precio, elige una moneda.")

    def test_catalogue_renders_canonical_selects_and_preserves_normalized_filters(self):
        response = self.client.get(f"/maquinaria/?category={self.category.pk}&currency=usd&preservation_condition=Buena&location_country=MX&location_region=Quintana%20Roo")
        self.assertContains(response, f'<option value="{self.category.pk}" selected>Excavadoras</option>', html=True)
        self.assertContains(response, '<option value="USD" selected>USD</option>', html=True)
        self.assertContains(response, '<option value="good" selected>Buena</option>', html=True)
        self.assertIn(b'id="location_country" name="location_country" value="MX"', response.content)
        self.assertIn(b'id="location_region" name="location_region" value="Quintana Roo"', response.content)
        self.assertIn(b'name="weight_max"', response.content)
        self.assertIn(b'name="depth_max"', response.content)
        self.assertIn(b'id="variant" name="variant"', response.content)
        self.assertIn(b'id="sort" name="sort"', response.content)

    def test_variant_filter_result_count_and_safe_sorting(self):
        lower_hours = Machine.objects.create(owner=self.owner, category=self.category,
            title="CAT 321", data={"brand": "CAT", "model": "321", "hours": 10,
                "variant": "LC", "year": 2020, "price": "50000", "currency": "USD",
                "provenance": {"price": {"source": "user", "review": "confirmed"}}})
        lower_version = MachineVersion.objects.create(machine=lower_hours, number=1,
            created_by=self.owner, data={"title": "CAT 321", "data": lower_hours.data,
                "provenance": lower_hours.data["provenance"], "public_asset_ids": []})
        lower_hours.approved_version = lower_version
        lower_hours.save(update_fields=["approved_version"])
        Publication.objects.create(machine=lower_hours, version=lower_version,
            destination="share", enabled=True, status="published")

        variant_response = self.client.get("/maquinaria/?variant=LC")
        self.assertContains(variant_response, "1 resultado")
        self.assertContains(variant_response, "CAT 321")

        sorted_response = self.client.get("/maquinaria/?sort=hours_asc")
        html = sorted_response.content.decode()
        self.assertContains(sorted_response, "2 resultados")
        self.assertLess(html.index("CAT 320"), html.index("CAT 321"))

        # Price order is only enabled within an explicitly selected currency;
        # the unscoped request falls back to recency instead of mixing MXN/USD.
        mixed_response = self.client.get("/maquinaria/?sort=price_asc")
        self.assertIn(b'<option value="latest" selected>', mixed_response.content)
        usd_response = self.client.get("/maquinaria/?sort=price_asc&currency=USD")
        usd_html = usd_response.content.decode()
        self.assertLess(usd_html.index("CAT 321"), usd_html.index("CAT 320"))

    def test_combined_numeric_filters_and_currency_are_applied_together(self):
        self.version.refresh_from_db()
        self.assertEqual(self.version.brand, "CAT")
        self.assertEqual(self.version.currency, "USD")
        self.assertEqual(str(self.version.price), "125000.00")
        self.assertEqual(str(self.version.weight_kg), "22000.000")
        self.assertEqual(str(self.version.digging_depth_m), "6.700")
        self.assertEqual(self.version.undercarriage, "crawler")
        self.assertContains(self.client.get("/maquinaria/?brand=CAT&model=320&undercarriage=crawler"), "CAT 320")
        query = "/maquinaria/?brand=CAT&model=320&undercarriage=crawler&hours_max=0&year_mode=exact&year=2018&price_min=100000&price_max=130000&currency=USD&weight_min=22000&weight_max=22000&depth_min=6.7&depth_max=6.7"
        self.assertContains(self.client.get(query), "CAT 320")
        self.assertNotContains(self.client.get(query.replace("currency=USD", "currency=MXN")), "CAT 320")
        self.assertNotContains(self.client.get(query.replace("hours_max=0", "hours_max=-1")), "CAT 320")

    def test_card_uses_sanitized_snapshot_title_when_identifiers_are_unknown(self):
        unknown = Machine.objects.create(owner=self.owner, category=self.category, title="Excavadora de respaldo", data={})
        version = MachineVersion.objects.create(machine=unknown, number=1, created_by=self.owner,
            data={"title": "Excavadora de respaldo", "data": {"description": "Ficha aprobada."}, "provenance": {}, "public_asset_ids": []})
        unknown.approved_version = version
        unknown.save(update_fields=["approved_version"])
        Publication.objects.create(machine=unknown, version=version, destination="share", enabled=True, status="published")
        response = self.client.get("/maquinaria/")
        self.assertContains(response, "Excavadora de respaldo")
        self.assertNotContains(response, "<h2></h2>", html=True)

    def test_currency_is_required_for_public_price_and_no_cross_currency_order(self):
        self.assertContains(self.client.get("/maquinaria/"), "125000 USD")
        self.machine.data["price"] = "999999"
        self.machine.data["currency"] = ""
        self.machine.save(update_fields=["data"])
        self.assertNotContains(self.client.get("/maquinaria/"), "999999")

    def test_public_sheet_and_pdf_omit_internal_values_and_placeholders(self):
        self.machine.data.update({"serial": "PRIVATE-SERIAL", "notes": "PRIVATE-NOTE",
                                  "estimate_missing_info": "FALTA-INTERNA"})
        self.machine.save(update_fields=["data"])
        sheet = self.client.get(f"/ficha/{self.publication.token}/")
        self.assertEqual(sheet.status_code, 200)
        self.assertNotContains(sheet, "PRIVATE-SERIAL")
        self.assertNotContains(sheet, "PRIVATE-NOTE")
        self.assertNotContains(sheet, "No indicada")
        self.assertNotContains(sheet, "Consultar precio")
        self.assertEqual(self.client.get(f"/ficha/{self.publication.token}/pdf/").status_code, 403)

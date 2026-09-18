from dataclasses import FrozenInstanceError
from urllib.parse import urlsplit

from django.test import SimpleTestCase

from portal.research_sources import (
    MANUFACTURERS, TECHNICAL_CATALOGS, VERIFIED_ON, lookup_brand, source_kind,
)


class ResearchSourceCatalogTests(SimpleTestCase):
    def test_exact_brand_aliases_supply_the_same_verified_profile(self):
        aliases = {
            ' cat ': 'Caterpillar', 'CATERPILLAR': 'Caterpillar',
            'Ｋｏｍａｔｓｕ': 'Komatsu', 'Volvo CE': 'Volvo Construction Equipment',
            'volvo construction equipment': 'Volvo Construction Equipment',
            'JOHN-DEERE': 'John Deere', 'Deere': 'John Deere',
            'JLG Industries': 'JLG', 'Bobcat Company': 'Bobcat',
            'develon ce': 'DEVELON',
        }
        for alias, expected in aliases.items():
            with self.subTest(alias=alias):
                profile = lookup_brand(alias)
                self.assertEqual(profile.brand, expected)
                self.assertIs(profile, lookup_brand(expected))

    def test_unknown_brands_and_embedded_names_do_not_borrow_authority(self):
        for brand in ('HESSEN', 'HESSEN 016-9020', '016-9030', 'CAT 320', 'Bobcat 320',
                      'Volvo Trucks', 'Case IH', 'my Caterpillar', 'https://cat.com',
                      'CAT/Komatsu', '', None, {'brand': 'Cat'}):
            with self.subTest(brand=brand):
                self.assertIsNone(lookup_brand(brand))
        self.assertEqual(lookup_brand('Bobcat').manufacturer_domains, ('bobcat.com',))

    def test_catalog_is_immutable_and_contains_only_public_https_starting_points(self):
        self.assertEqual(len(MANUFACTURERS), 7)
        self.assertEqual(len(TECHNICAL_CATALOGS), 2)
        with self.assertRaises(FrozenInstanceError):
            MANUFACTURERS[0].brand = 'changed'
        with self.assertRaises(TypeError):
            MANUFACTURERS[0].manufacturer_domains[0] = 'changed'
        for profile in (*MANUFACTURERS, *TECHNICAL_CATALOGS):
            expected_date = '2026-09-18' if getattr(profile, 'brand', None) == 'DEVELON' else VERIFIED_ON
            self.assertEqual(profile.verified_on, expected_date)
            self.assertTrue(profile.access_note)
            for url in profile.documentation_urls:
                with self.subTest(url=url):
                    parsed = urlsplit(url)
                    self.assertEqual(parsed.scheme, 'https')
                    self.assertIsNone(parsed.username)
                    self.assertIsNone(parsed.password)
                    self.assertFalse(parsed.query)
                    self.assertFalse(parsed.fragment)
                    self.assertEqual(source_kind(url), profile.source_kind)

        self.assertEqual(lookup_brand('DEVELON').verified_on, '2026-09-18')

    def test_manufacturer_classification_is_scoped_to_the_requested_brand(self):
        self.assertEqual(source_kind('https://parts.cat.com/manual.pdf', 'CAT'), 'manufacturer')
        self.assertEqual(source_kind('https://www.cat.com/manual.pdf'), 'manufacturer')
        self.assertEqual(source_kind('https://manuals.deere.com/example', 'Deere'), 'manufacturer')
        self.assertEqual(source_kind('https://www.cat.com/manual.pdf', 'Komatsu'), 'public_documentation')
        self.assertEqual(source_kind('https://www.cat.com/manual.pdf', 'HESSEN'), 'public_documentation')
        self.assertEqual(source_kind('https://www.cat.com/manual.pdf', ''), 'public_documentation')

    def test_catalogs_never_become_manufacturers_even_for_a_serial_year_url(self):
        for profile in TECHNICAL_CATALOGS:
            for domain in profile.domains:
                for brand in ('CAT', 'Komatsu', 'HESSEN', None):
                    with self.subTest(domain=domain, brand=brand):
                        self.assertEqual(
                            source_kind(f'https://www.{domain}/year-by-serial?serial=SYNTHETIC', brand),
                            'technical_catalog',
                        )

    def test_domain_spoofing_does_not_promote_a_result(self):
        for url in ('https://cat.com.attacker.example/manual', 'https://notcat.com/manual',
                    'https://www.cat.com.evil.example/', 'https://cat-com.example/',
                    'https://evil.example/manual?source=https://cat.com',
                    'https://lectura-specs.com.attacker.example/',
                    'https://notritchiespecs.com/', 'https://hessen.com.br/produtos/hessen/'):
            with self.subTest(url=url):
                self.assertEqual(source_kind(url, 'CAT'), 'public_documentation')

    def test_invalid_or_non_public_urls_are_not_classified(self):
        for url in ('javascript:alert(1)', 'file:///manual.pdf', '//cat.com/manual.pdf',
                    'https://cat.com@evil.example/', 'https://user:pass@cat.com/',
                    'https://cat.com\\@evil.example/', 'https://cat.com\n.evil.example/',
                    'https://cat.com:invalid/', 'https://cat.com:8443/', 'https://[::1]/',
                    'http://127.0.0.1/', 'https://localhost/', 'https://server.local/',
                    'https://host.internal/', 'https://test.invalid/', '', None, {}):
            with self.subTest(url=url):
                self.assertIsNone(source_kind(url))

    def test_result_classification_does_not_inherit_a_redirect_origins_authority(self):
        self.assertEqual(source_kind('https://www.cat.com/manual', 'CAT'), 'manufacturer')
        self.assertEqual(source_kind('https://unverified.example/manual.pdf', 'CAT'), 'public_documentation')
        self.assertEqual(source_kind('HTTPS://WWW.CAT.COM./manual', 'CAT'), 'manufacturer')

    def test_profile_aliases_are_unambiguous(self):
        for profile in MANUFACTURERS:
            for alias in (profile.brand, *profile.aliases):
                with self.subTest(alias=alias):
                    self.assertIs(lookup_brand(alias), profile)
        manufacturer_domains = {domain for profile in MANUFACTURERS for domain in profile.manufacturer_domains}
        catalog_domains = {domain for profile in TECHNICAL_CATALOGS for domain in profile.domains}
        self.assertFalse(manufacturer_domains & catalog_domains)

from django.test import TestCase

from portal.forms import ProfileForm, RegisterForm
from portal.models import User


class RegistrationPhoneTests(TestCase):
    def payload(self, **overrides):
        data = {
            "first_name": "Ana", "last_name": "Prueba", "email": "phone@example.invalid",
            "phone_prefix": "+52", "phone_national": "55 1234 5678",
            "contact_preference": "email", "password1": "Phone-test-password-123!",
            "password2": "Phone-test-password-123!", "terms": "on",
        }
        data.update(overrides)
        return data

    def test_valid_mexico_and_bolivia_numbers_are_stored_e164(self):
        for prefix, national, expected in (("+52", "55 1234 5678", "+525512345678"), ("+591", "7 1234567", "+59171234567")):
            form = RegisterForm(self.payload(email=f"{prefix[1:]}@example.invalid", phone_prefix=prefix, phone_national=national))
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["phone"], expected)

    def test_pasted_international_number_matches_prefix_without_doubling(self):
        form = RegisterForm(self.payload(phone_prefix="+52", phone_national="+52 55 1234 5678"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone"], "+525512345678")

    def test_prefix_can_be_typed_without_plus_and_national_start_is_not_removed(self):
        form = RegisterForm(self.payload(phone_prefix="52", phone_national="5212345678"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone"], "+525212345678")

    def test_non_ascii_digits_do_not_produce_a_non_e164_contact(self):
        form = RegisterForm(self.payload(phone_national="٥٥١٢٣٤٥٦٧٨"))
        self.assertFalse(form.is_valid())
        self.assertIn("phone_national", form.errors)

    def test_pasted_international_number_with_mismatched_prefix_is_rejected(self):
        form = RegisterForm(self.payload(phone_prefix="+591", phone_national="+52 55 1234 5678"))
        self.assertFalse(form.is_valid())
        self.assertIn("phone_national", form.errors)

    def test_phone_parts_and_surname_are_required_for_new_registration(self):
        form = RegisterForm(self.payload(last_name="", phone_prefix="", phone_national=""))
        self.assertFalse(form.is_valid())
        self.assertIn("last_name", form.errors)
        self.assertIn("phone_prefix", form.errors)
        self.assertIn("phone_national", form.errors)

    def test_invalid_country_code_and_e164_length_are_rejected(self):
        unknown = RegisterForm(self.payload(phone_prefix="+999", phone_national="1234567"))
        self.assertFalse(unknown.is_valid())
        self.assertIn("phone_prefix", unknown.errors)
        too_long = RegisterForm(self.payload(phone_national="12345678901234"))
        self.assertFalse(too_long.is_valid())
        self.assertIn("phone_national", too_long.errors)

    def test_legacy_full_phone_post_and_profile_reload_preserve_value(self):
        form = RegisterForm(self.payload(phone_prefix="", phone_national="", phone="+591 71234567"))
        self.assertTrue(form.is_valid(), form.errors)
        user = User.objects.create_user(email="legacy@example.invalid", phone=form.cleaned_data["phone"])
        profile = ProfileForm(instance=user)
        self.assertEqual(profile.initial["phone_prefix"], "+591")
        self.assertEqual(profile.initial["phone_national"], "71234567")
        submitted = ProfileForm({"first_name": "Ana", "last_name": "Prueba", "phone": "+591 71234567", "company": "", "contact_preference": "email"}, instance=user)
        self.assertTrue(submitted.is_valid(), submitted.errors)
        self.assertEqual(submitted.cleaned_data["phone"], "+59171234567")

"""Small-image preprocessing is local, bounded and does not change saved media."""
import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from PIL import Image

from portal.processing import _image_input, MAX_ANALYSIS_IMAGE_BYTES


class AnalysisImageInputTests(SimpleTestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix="imc-image-request-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def asset(self, size):
        # Distinct bands let us check that enlargement is not a crop/stretch.
        image = Image.new("RGB", size, "white")
        image.paste("black", (0, 0, size[0] // 3, size[1]))
        image.paste("red", (size[0] * 2 // 3, 0, size[0], size[1]))
        original, preview = self.folder / "original.jpg", self.folder / "preview.jpg"
        image.save(original, "JPEG", quality=95)
        preview.write_bytes(original.read_bytes())
        return SimpleNamespace(original=original, preview=preview)

    def decoded(self, request):
        self.assertEqual(request["type"], "input_image")
        self.assertEqual(request["detail"], "high")
        self.assertTrue(request["image_url"].startswith("data:image/jpeg;base64,"))
        payload = base64.b64decode(request["image_url"].split(",", 1)[1], validate=True)
        self.assertLessEqual(len(payload), MAX_ANALYSIS_IMAGE_BYTES)
        return payload, Image.open(BytesIO(payload))

    def test_small_portrait_and_landscape_are_enlarged_with_aspect_and_originals_unchanged(self):
        for size in ((360, 288), (240, 360)):
            with self.subTest(size=size):
                asset = self.asset(size)
                before = (asset.original.read_bytes(), asset.preview.read_bytes())
                _, image = self.decoded(_image_input(asset))
                self.assertEqual(max(image.size), 1280)
                self.assertLessEqual(abs(image.width * size[1] - image.height * size[0]), max(size))
                self.assertLess(max(image.getpixel((image.width // 6, image.height // 2))), 10)
                self.assertGreater(min(image.getpixel((image.width // 2, image.height // 2))), 240)
                red = image.getpixel((image.width * 5 // 6, image.height // 2))
                self.assertGreater(red[0], 240)
                self.assertLess(max(red[1:]), 15)
                self.assertEqual((asset.original.read_bytes(), asset.preview.read_bytes()), before)

    def test_already_large_preview_is_sent_without_reencoding(self):
        asset = self.asset((1600, 800))
        raw, image = self.decoded(_image_input(asset))
        self.assertEqual(image.size, (1600, 800))
        self.assertEqual(raw, asset.preview.read_bytes())

    def test_request_byte_limit_applies_before_and_after_preprocessing_and_corrupt_input_is_rejected(self):
        asset = self.asset((360, 288))
        original = asset.preview.read_bytes()
        asset.preview.write_bytes(b"x" * (MAX_ANALYSIS_IMAGE_BYTES + 1))
        with self.assertRaises(ValidationError):
            _image_input(asset)
        asset.preview.write_bytes(b"not an image")
        with self.assertRaises(ValidationError):
            _image_input(asset)
        asset.preview.write_bytes(original)
        with patch("PIL.Image.Image.save", side_effect=lambda stream, **kwargs: stream.write(b"x" * (MAX_ANALYSIS_IMAGE_BYTES + 1))):
            with self.assertRaises(ValidationError):
                _image_input(asset)
        self.assertEqual(asset.preview.read_bytes(), original)

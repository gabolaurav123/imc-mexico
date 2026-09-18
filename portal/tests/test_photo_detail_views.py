"""Small label views stay bound to their original photo and never add paid calls."""
import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image
from portal.processing import _image_detail_inputs, SYSTEM_PROMPT, enqueue_analysis, process_analysis
from portal.tests.test_image_relevance import observation, parsed


class PhotoDetailViewTests(SimpleTestCase):
    def photo(self):
        image = Image.new('RGB', (1280, 1280), 'white')
        for box, color in [((0, 0, 640, 640), 'red'), ((640, 0, 1280, 640), 'blue'),
                           ((0, 640, 640, 1280), 'green'), ((640, 640, 1280, 1280), 'yellow')]:
            image.paste(color, box)
        raw = BytesIO(); image.save(raw, format='PNG')
        return {'type':'input_image','detail':'high','image_url':'data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()}

    def test_views_preserve_pixels_order_and_one_photo_identity(self):
        source=self.photo(); before=dict(source)
        views=_image_detail_inputs(source,'general')
        self.assertEqual(len(views),8)
        for index,color in enumerate(((255,0,0),(0,0,255),(0,128,0),(255,255,0))):
            self.assertIn('MISMA FOTO image_001',views[index*2]['text'])
            data=base64.b64decode(views[index*2+1]['image_url'].split(',',1)[1])
            image=Image.open(BytesIO(data))
            self.assertEqual(image.size,(768,768))
            self.assertEqual(image.getpixel((384,384)),color)
            self.assertFalse(image.getexif())
        self.assertEqual(source,before)
        self.assertIn('no otras máquinas ni otras vistas',SYSTEM_PROMPT)

    def test_no_crops_for_plates_private_documents_or_external_urls(self):
        for purpose in ('plate','document','detail'):
            self.assertEqual(_image_detail_inputs(self.photo(),purpose),[])
        for url in ('https://example.org/photo.jpg','data:image/png;base64,not-valid'):
            self.assertEqual(_image_detail_inputs({'image_url':url},'general'),[])


@override_settings(OPENAI_API_KEY='test-only-no-network', OPENAI_MODEL='gpt-5.6-luna')
class PhotoDetailPipelineTests(TestCase):
    def test_five_views_remain_one_paid_call_and_one_observation_per_photo(self):
        from portal.tests.test_image_bindings import ImageMessageBindingTests
        ImageMessageBindingTests.setUp(self)
        job = enqueue_analysis(self.machine, self.owner, authorize_ai=True)
        def response(**kwargs):
            manifest = json.loads(kwargs['input'][0]['content'][0]['text'])['image_manifest']
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]['asset_id'], 'image_001')
            self.assertEqual(sum(item['type'] == 'input_image' for item in kwargs['input'][1]['content']), 5)
            return SimpleNamespace(status='completed',
                output_parsed=parsed([observation('image_001', 'related', 'machine', category='Montacargas')], []),
                usage=SimpleNamespace(input_tokens=1000, output_tokens=200))
        with patch('portal.processing._image_input', return_value=PhotoDetailViewTests().photo()), patch('openai.OpenAI') as provider:
            provider.return_value.responses.parse.side_effect = response
            result, _ = process_analysis(job)
        self.assertEqual(provider.return_value.responses.parse.call_count, 2)
        provider.return_value.responses.create.assert_not_called()
        self.assertEqual(len(result['image_observations']), 2)
        self.assertEqual(len({item['asset_id'] for item in result['image_observations']}), 2)

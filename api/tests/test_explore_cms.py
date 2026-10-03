import importlib.util
import tempfile
import unittest
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from PIL import Image

spec = importlib.util.spec_from_file_location('explore_cms', Path(__file__).resolve().parents[2] / 'scripts' / 'explore_cms.py')
cms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cms)

class Upload(BytesIO):
    name = 'photo.jpg'

class CmsSaveTest(unittest.TestCase):
    def test_delete_keeps_non_default_route_and_remaining_photo_visible(self):
        from streamlit.testing.v1 import AppTest
        catalog = [dict(stop_name='test', routes=[
            dict(route_id='first', route_label='First', pole_ids=['1']),
            dict(route_id='second', route_label='Second', pole_ids=['2']),
        ])]
        groups = [dict(stop_name='test', route_id='second', comment='', comment_en='', images=[
            dict(file='one.jpg', caption='one', caption_en=''),
            dict(file='two.jpg', caption='two', caption_en=''),
        ])]
        def remove_image(**kwargs):
            groups[0]['images'] = [image for image in groups[0]['images'] if image['file'] != kwargs['filename']]
        with tempfile.TemporaryDirectory() as directory:
            images = Path(directory)
            for name in ('one.jpg', 'two.jpg'):
                Image.new('RGB', (3, 3)).save(images / name)
            with patch.dict(sys.modules, {'explore_cms_test_target': cms}), patch.object(cms, 'load_catalog', return_value=catalog), patch.object(cms, 'load_groups', side_effect=lambda: groups), patch.object(cms, 'IMAGES_DIR', images), patch.object(cms, 'delete_group_image', side_effect=remove_image):
                app = AppTest.from_string('import explore_cms_test_target as cms\ncms.main()').run()
                app.button(key='open_existing_entry').click().run()
                self.assertEqual(app.selectbox(key='explore_cms_selected_route::test').value, 'second')
                app.button(key='delete::test::second::one.jpg').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.selectbox(key='explore_cms_selected_route::test').value, 'second')
                self.assertEqual(app.text_input(key='existing_caption::test::second::two.jpg').value, 'two')
                self.assertEqual(len(groups[0]['images']), 1)

    def test_repeated_upload_does_not_duplicate_or_lose_caption_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            images = root / 'images'
            cms.write_authoring_groups(root / 'spots.csv', [])
            output = BytesIO()
            Image.new('RGB', (3, 3), 'blue').save(output, format='JPEG')
            upload = Upload(output.getvalue())
            with patch.object(cms, 'CSV_PATH', root / 'spots.csv'), patch.object(cms, 'IMAGES_DIR', images), patch.object(cms, 'compile_csv'):
                args = dict(stop_name='test', route_id='route', comment='first', comment_en='', uploaded_files=[upload, upload], captions=['original', 'original'], captions_en=['', ''], existing_captions={}, existing_captions_en={})
                filenames = cms.save_group(**args)
                self.assertEqual(len(filenames), 1)
                args.update(comment='edited', uploaded_files=[upload], captions=['original'], captions_en=[''], existing_captions={filenames[0]: 'edited caption'}, existing_captions_en={filenames[0]: ''})
                self.assertEqual(cms.save_group(**args), [])
                group = cms.load_groups()[0]
                self.assertEqual(group['comment'], 'edited')
                self.assertEqual(group['images'][0]['caption'], 'edited caption')
                self.assertEqual(len(group['images']), 1)
                self.assertEqual(len(list(images.iterdir())), 1)

if __name__ == '__main__':
    unittest.main()

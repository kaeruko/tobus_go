import importlib.util
import tempfile
import unittest
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

import tempfile
import unittest
from pathlib import Path

from app.services.explore_editorial_content import (
    ExploreContentError,
    compile_csv,
)


class ExploreEditorialContentTest(unittest.TestCase):
    def _workspace(self):
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name)
        images = root / "images"
        images.mkdir()
        return temp_dir, root / "spots.csv", images

    def test_compiles_multiple_images_for_same_stop(self):
        temp_dir, csv_path, images = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        (images / "river_01.jpg").write_bytes(b"one")
        (images / "river_02.webp").write_bytes(b"two")
        csv_path.write_text(
            "stop_id,comment,image,caption\n"
            "stop-a,川沿いが気持ちいい,river_01.jpg,川へ向かう道\n"
            "stop-a,,river_02.webp,夕方の川\n",
            encoding="utf-8",
        )

        payload = compile_csv(csv_path, images)

        self.assertEqual(
            payload,
            {
                "spots": [
                    {
                        "stop_id": "stop-a",
                        "comment": "川沿いが気持ちいい",
                        "images": [
                            {"file": "river_01.jpg", "caption": "川へ向かう道"},
                            {"file": "river_02.webp", "caption": "夕方の川"},
                        ],
                    }
                ]
            },
        )

    def test_rejects_conflicting_comments(self):
        temp_dir, csv_path, images = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_id,comment,image,caption\n"
            "stop-a,first,,\n"
            "stop-a,second,,\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExploreContentError, "conflicting comments"):
            compile_csv(csv_path, images)

    def test_rejects_missing_image_before_publish(self):
        temp_dir, csv_path, images = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_id,comment,image,caption\n"
            "stop-a,,missing.jpg,photo\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExploreContentError, "image was not found"):
            compile_csv(csv_path, images)

    def test_rejects_unreferenced_image(self):
        temp_dir, csv_path, images = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        (images / "unused.jpg").write_bytes(b"unused")
        csv_path.write_text(
            "stop_id,comment,image,caption\n"
            "stop-a,comment,,\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExploreContentError, "unreferenced files"):
            compile_csv(csv_path, images)

    def test_rejects_changed_csv_shape(self):
        temp_dir, csv_path, images = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_id,comment,image\n"
            "stop-a,comment,\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExploreContentError, "CSV columns must be exactly"):
            compile_csv(csv_path, images)


if __name__ == "__main__":
    unittest.main()

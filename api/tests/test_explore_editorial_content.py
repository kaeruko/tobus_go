import json
import tempfile
import unittest
from pathlib import Path

from app.services.explore_editorial_content import (
    ExploreContentError,
    build_stop_route_catalog,
    compile_csv,
)


UE23 = "odpt.Busroute:Toei.Ue23"
MON33 = "odpt.Busroute:Toei.Mon33"

POLE_UP = "odpt.BusstopPole:Toei.OshiageStation.100.1"
POLE_DOWN = "odpt.BusstopPole:Toei.OshiageStation.100.2"
POLE_MON = "odpt.BusstopPole:Toei.OshiageStation.100.3"
POLE_OTHER = "odpt.BusstopPole:Toei.Narihira.101.1"


class ExploreEditorialContentTest(unittest.TestCase):
    def _workspace(self):
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name)
        images = root / "images"
        images.mkdir()
        data = root / "data"
        data.mkdir()

        poles = [
            {
                "owl:sameAs": POLE_UP,
                "dc:title": "押上駅前",
                "odpt:note": "noteは識別に使わない",
            },
            {
                "owl:sameAs": POLE_DOWN,
                "dc:title": "押上駅前",
                "odpt:note": "上り下りで違うnote",
            },
            {
                "owl:sameAs": POLE_MON,
                "dc:title": "押上駅前",
                "odpt:note": "門33だけの乗り場",
            },
            {
                "owl:sameAs": POLE_OTHER,
                "dc:title": "業平橋",
                "odpt:note": "押上駅前",
            },
        ]
        patterns = [
            {
                "odpt:busroute": UE23,
                "dc:title": "上２３ 平井駅前行",
                "odpt:note": "任意のnote",
                "odpt:busstopPoleOrder": [
                    {"odpt:index": 1, "odpt:busstopPole": POLE_UP},
                    {"odpt:index": 2, "odpt:busstopPole": POLE_OTHER},
                ],
            },
            {
                "odpt:busroute": UE23,
                "dc:title": "上２３ 東墨田二丁目行",
                "odpt:note": "逆方向",
                "odpt:busstopPoleOrder": [
                    {"odpt:index": 1, "odpt:busstopPole": POLE_DOWN},
                ],
            },
            {
                "odpt:busroute": MON33,
                "dc:title": "門３３ 豊海水産埠頭行",
                "odpt:note": "別系統",
                "odpt:busstopPoleOrder": [
                    {"odpt:index": 1, "odpt:busstopPole": POLE_MON},
                ],
            },
        ]

        (data / "odpt_BusstopPole.json").write_text(
            json.dumps(poles, ensure_ascii=False),
            encoding="utf-8",
        )
        (data / "odpt_BusroutePattern.json").write_text(
            json.dumps(patterns, ensure_ascii=False),
            encoding="utf-8",
        )

        return temp_dir, root / "spots.csv", images, data

    def test_same_name_and_route_expands_both_directions(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        (images / "oshiage_01.jpg").write_bytes(b"one")
        (images / "oshiage_02.webp").write_bytes(b"two")
        csv_path.write_text(
            "stop_name,route_id,comment,image,caption\n"
            f"押上駅前,{UE23},スカイツリーが近い,oshiage_01.jpg,駅前\n"
            f"押上駅前,{UE23},,oshiage_02.webp,夕方\n",
            encoding="utf-8",
        )

        payload = compile_csv(csv_path, images, data_dir=data)

        self.assertEqual(
            {spot["stop_id"] for spot in payload["spots"]},
            {POLE_UP, POLE_DOWN},
        )
        for spot in payload["spots"]:
            self.assertEqual(spot["comment"], "スカイツリーが近い")
            self.assertEqual(
                spot["images"],
                [
                    {"file": "oshiage_01.jpg", "caption": "駅前"},
                    {"file": "oshiage_02.webp", "caption": "夕方"},
                ],
            )

    def test_route_filters_same_stop_name(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_name,route_id,comment,image,caption\n"
            f"押上駅前,{MON33},門33側のメモ,,\n",
            encoding="utf-8",
        )

        payload = compile_csv(csv_path, images, data_dir=data)

        self.assertEqual(
            payload,
            {
                "spots": [
                    {
                        "stop_id": POLE_MON,
                        "comment": "門33側のメモ",
                        "images": [],
                    }
                ]
            },
        )

    def test_catalog_uses_name_and_route_and_ignores_note(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)

        catalog = build_stop_route_catalog(data)
        oshiage = next(item for item in catalog if item["stop_name"] == "押上駅前")
        labels = {
            route["route_id"]: route["route_label"]
            for route in oshiage["routes"]
        }

        self.assertEqual(labels[UE23], "上23")
        self.assertEqual(labels[MON33], "門33")
        self.assertEqual(
            next(
                route["pole_ids"]
                for route in oshiage["routes"]
                if route["route_id"] == UE23
            ),
            [POLE_UP, POLE_DOWN],
        )

        # POLE_OTHER has odpt:note="押上駅前" but dc:title="業平橋".
        # It must never be grouped into 押上駅前.
        all_oshiage_poles = {
            pole_id
            for route in oshiage["routes"]
            for pole_id in route["pole_ids"]
        }
        self.assertNotIn(POLE_OTHER, all_oshiage_poles)

    def test_rejects_unknown_stop_route_pair(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_name,route_id,comment,image,caption\n"
            f"業平橋,{MON33},存在しない組み合わせ,,\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ExploreContentError,
            "no BusstopPole matched exact stop_name \+ route_id",
        ):
            compile_csv(csv_path, images, data_dir=data)

    def test_rejects_conflicting_comments(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_name,route_id,comment,image,caption\n"
            f"押上駅前,{UE23},first,,\n"
            f"押上駅前,{UE23},second,,\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExploreContentError, "conflicting comments"):
            compile_csv(csv_path, images, data_dir=data)

    def test_rejects_missing_image_before_publish(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_name,route_id,comment,image,caption\n"
            f"押上駅前,{UE23},,missing.jpg,photo\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExploreContentError, "image was not found"):
            compile_csv(csv_path, images, data_dir=data)

    def test_rejects_unreferenced_image(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        (images / "unused.jpg").write_bytes(b"unused")
        csv_path.write_text(
            "stop_name,route_id,comment,image,caption\n"
            f"押上駅前,{UE23},comment,,\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExploreContentError, "unreferenced files"):
            compile_csv(csv_path, images, data_dir=data)

    def test_rejects_changed_csv_shape(self):
        temp_dir, csv_path, images, data = self._workspace()
        self.addCleanup(temp_dir.cleanup)
        csv_path.write_text(
            "stop_name,route_id,comment,image\n"
            f"押上駅前,{UE23},comment,\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ExploreContentError,
            "CSV columns must be exactly",
        ):
            compile_csv(csv_path, images, data_dir=data)


if __name__ == "__main__":
    unittest.main()

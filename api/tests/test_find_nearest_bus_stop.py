from __future__ import annotations

import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import find_nearest_bus_stop as locator  # noqa: E402


def _rational_triplet(values: tuple[tuple[int, int], ...], endian: str) -> bytes:
    return b"".join(struct.pack(f"{endian}II", numerator, denominator) for numerator, denominator in values)


def _build_test_jpeg_with_gps(
    *,
    lat_values: tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
    lat_ref: bytes,
    lon_values: tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
    lon_ref: bytes,
) -> bytes:
    endian = "<"
    header = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)

    ifd0_count = 1
    ifd0_size = 2 + ifd0_count * 12 + 4
    gps_ifd_offset = 8 + ifd0_size

    gps_count = 4
    gps_ifd_size = 2 + gps_count * 12 + 4
    lat_data_offset = gps_ifd_offset + gps_ifd_size
    lon_data_offset = lat_data_offset + 24

    ifd0 = bytearray()
    ifd0 += struct.pack("<H", ifd0_count)
    ifd0 += struct.pack("<HHI", 0x8825, 4, 1)
    ifd0 += struct.pack("<I", gps_ifd_offset)
    ifd0 += struct.pack("<I", 0)

    gps_ifd = bytearray()
    gps_ifd += struct.pack("<H", gps_count)

    gps_ifd += struct.pack("<HHI", 0x0001, 2, 2)
    gps_ifd += lat_ref + b"\x00" + b"\x00\x00"

    gps_ifd += struct.pack("<HHI", 0x0002, 5, 3)
    gps_ifd += struct.pack("<I", lat_data_offset)

    gps_ifd += struct.pack("<HHI", 0x0003, 2, 2)
    gps_ifd += lon_ref + b"\x00" + b"\x00\x00"

    gps_ifd += struct.pack("<HHI", 0x0004, 5, 3)
    gps_ifd += struct.pack("<I", lon_data_offset)

    gps_ifd += struct.pack("<I", 0)

    tiff = (
        header
        + bytes(ifd0)
        + bytes(gps_ifd)
        + _rational_triplet(lat_values, endian)
        + _rational_triplet(lon_values, endian)
    )
    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + app1 + b"\xff\xd9"


class FindNearestBusStopTest(unittest.TestCase):
    def test_extract_gps_from_jpeg(self):
        jpeg = _build_test_jpeg_with_gps(
            lat_values=((35, 1), (39, 1), (3649, 100)),
            lat_ref=b"N",
            lon_values=((139, 1), (43, 1), (2860, 100)),
            lon_ref=b"E",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "photo.jpg"
            path.write_bytes(jpeg)
            lat, lon = locator.extract_gps_from_jpeg(path)

        self.assertAlmostEqual(lat, 35 + 39 / 60 + 36.49 / 3600, places=8)
        self.assertAlmostEqual(lon, 139 + 43 / 60 + 28.60 / 3600, places=8)

    def test_extract_gps_requires_exif(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "photo.jpg"
            path.write_bytes(b"\xff\xd8\xff\xd9")

            with self.assertRaisesRegex(locator.LocatorError, "no EXIF"):
                locator.extract_gps_from_jpeg(path)

    def test_select_route_stop_ids_matches_full_width_route_label(self):
        patterns = [
            {
                "owl:sameAs": "pattern-a",
                "dc:title": "渋８８ 新橋駅前行",
                "odpt:busstopPoleOrder": [
                    {"odpt:busstopPole": "pole-a"},
                    {"odpt:busstopPole": "pole-b"},
                ],
            },
            {
                "owl:sameAs": "pattern-b",
                "dc:title": "渋８８ 渋谷駅前行",
                "odpt:busstopPoleOrder": [
                    {"odpt:busstopPole": "pole-b"},
                    {"odpt:busstopPole": "pole-c"},
                ],
            },
            {
                "owl:sameAs": "other",
                "dc:title": "都０１ 新橋駅前行",
                "odpt:busstopPoleOrder": [
                    {"odpt:busstopPole": "pole-x"},
                ],
            },
        ]

        ids, count = locator.select_route_stop_ids(patterns, "渋88")

        self.assertEqual(ids, {"pole-a", "pole-b", "pole-c"})
        self.assertEqual(count, 2)

    def test_select_route_stop_ids_fails_when_route_is_missing(self):
        patterns = [
            {
                "owl:sameAs": "pattern-a",
                "dc:title": "都０１ 新橋駅前行",
                "odpt:busstopPoleOrder": [
                    {"odpt:busstopPole": "pole-a"},
                ],
            }
        ]

        with self.assertRaisesRegex(locator.LocatorError, "route not found"):
            locator.select_route_stop_ids(patterns, "渋88")

    def test_rank_candidate_stops_returns_nearest_physical_pole(self):
        poles = [
            {
                "owl:sameAs": "pole-near",
                "odpt:note": "西麻布",
                "odpt:busstopPoleNumber": "2",
                "geo:lat": 35.6602,
                "geo:long": 139.7246,
            },
            {
                "owl:sameAs": "pole-far",
                "odpt:note": "EXシアター六本木前",
                "odpt:busstopPoleNumber": "1",
                "geo:lat": 35.6630,
                "geo:long": 139.7270,
            },
            {
                "owl:sameAs": "pole-unrelated",
                "odpt:note": "対象外",
                "odpt:busstopPoleNumber": "9",
                "geo:lat": 35.660136,
                "geo:long": 139.724611,
            },
        ]

        ranked = locator.rank_candidate_stops(
            poles,
            candidate_ids={"pole-near", "pole-far"},
            photo_lat=35.660136,
            photo_lon=139.724611,
        )

        self.assertEqual(ranked[0].pole_id, "pole-near")
        self.assertEqual(ranked[0].name, "西麻布")
        self.assertGreater(ranked[1].distance_m, ranked[0].distance_m)

    def test_rank_candidate_stops_fails_on_missing_referenced_pole(self):
        poles = [
            {
                "owl:sameAs": "pole-a",
                "odpt:note": "A",
                "geo:lat": 35.0,
                "geo:long": 139.0,
            }
        ]

        with self.assertRaisesRegex(locator.LocatorError, "were not returned"):
            locator.rank_candidate_stops(
                poles,
                candidate_ids={"pole-a", "pole-b"},
                photo_lat=35.0,
                photo_lon=139.0,
            )

    def test_haversine_is_zero_for_same_point(self):
        self.assertTrue(
            math.isclose(
                locator.haversine_m(35.0, 139.0, 35.0, 139.0),
                0.0,
                abs_tol=1e-9,
            )
        )


if __name__ == "__main__":
    unittest.main()

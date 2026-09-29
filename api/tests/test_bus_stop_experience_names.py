import unittest
from unittest.mock import patch

from app.services.bus_stop_experience import build_route_experiences


class BusStopExperienceNamesTest(unittest.TestCase):
    def test_grouping_preserves_official_names_without_translation_requests(self):
        stops = [
            {
                "stop_id": "oshiage",
                "stop_name": "押上駅前",
                "stop_name_en": "Oshiage Sta.",
                "lat": 35.71,
                "lon": 139.81,
            },
            {
                "stop_id": "narihira",
                "stop_name": "業平橋",
                "stop_name_en": "Narihira-bashi",
                "lat": 35.70,
                "lon": 139.81,
            },
        ]
        with patch(
            "app.services.bus_stop_experience.fetch_pois_cached", return_value=[]
        ) as pois:
            groups = build_route_experiences(stops)

        self.assertEqual(pois.call_count, 2)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["representative_stop"]["stop_name"], "押上駅前")
        self.assertEqual(
            groups[0]["representative_stop"]["stop_name_en"], "Oshiage Sta."
        )
        self.assertEqual(
            [stop["stop_name_en"] for stop in groups[0]["stops"]],
            ["Oshiage Sta.", "Narihira-bashi"],
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace

from app.gtfs_bus_realtime_routes import _resolve_from_stop


class GtfsBusRealtimeRoutesTest(unittest.TestCase):
    def test_vehicle_before_first_stop_keeps_exact_vehicle_match(self) -> None:
        dataset = SimpleNamespace(
            stops={
                "yokohama_bus:A": SimpleNamespace(source_id="A"),
            }
        )
        schedule = [
            {
                "sequence": 1,
                "stop_id": "yokohama_bus:A",
                "stop_name": "横浜駅前",
            }
        ]
        row = {
            "stop_id": "A",
            "current_stop_sequence": 1,
            "current_status": 2,
        }

        from_stop, current_stop, before_first_stop = _resolve_from_stop(
            dataset=dataset,
            schedule=schedule,
            row=row,
        )

        self.assertIsNone(from_stop)
        self.assertEqual(current_stop, schedule[0])
        self.assertTrue(before_first_stop)


if __name__ == "__main__":
    unittest.main()

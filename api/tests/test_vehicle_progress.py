import unittest

from app.services.vehicle_progress import (
    normalize_vehicle_stop_status,
    resolve_vehicle_stop_progress,
)


class VehicleProgressTest(unittest.TestCase):
    def test_before_first_stop_has_no_previous_stop(self) -> None:
        for status in (0, 2, "INCOMING_AT", "IN_TRANSIT_TO"):
            with self.subTest(status=status):
                progress = resolve_vehicle_stop_progress(
                    observed_stop_sequence=1,
                    current_status=status,
                    previous_stop_sequence=None,
                )
                self.assertTrue(progress.before_first_stop)
                self.assertIsNone(progress.from_stop_sequence)

    def test_in_transit_uses_previous_static_sequence(self) -> None:
        progress = resolve_vehicle_stop_progress(
            observed_stop_sequence=7,
            current_status=2,
            previous_stop_sequence=4,
        )
        self.assertFalse(progress.before_first_stop)
        self.assertEqual(progress.from_stop_sequence, 4)
        self.assertEqual(progress.status_name, "IN_TRANSIT_TO")

    def test_stopped_at_uses_observed_stop(self) -> None:
        progress = resolve_vehicle_stop_progress(
            observed_stop_sequence=1,
            current_status="STOPPED_AT",
            previous_stop_sequence=None,
        )
        self.assertFalse(progress.before_first_stop)
        self.assertEqual(progress.from_stop_sequence, 1)

    def test_status_normalization_accepts_gtfs_rt_ints_and_names(self) -> None:
        self.assertEqual(normalize_vehicle_stop_status(0), "INCOMING_AT")
        self.assertEqual(normalize_vehicle_stop_status(1), "STOPPED_AT")
        self.assertEqual(normalize_vehicle_stop_status(2), "IN_TRANSIT_TO")
        self.assertEqual(
            normalize_vehicle_stop_status("IN_TRANSIT_TO"),
            "IN_TRANSIT_TO",
        )

    def test_invalid_status_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unsupported VehicleStopStatus"):
            normalize_vehicle_stop_status(9)

    def test_invalid_previous_sequence_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "previous stop sequence"):
            resolve_vehicle_stop_progress(
                observed_stop_sequence=3,
                current_status=2,
                previous_stop_sequence=3,
            )


if __name__ == "__main__":
    unittest.main()

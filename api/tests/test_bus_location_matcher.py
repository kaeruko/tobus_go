import unittest

from app.services.bus_location_matcher import (
    BusLocationMatchError,
    select_bus_candidate,
)


class BusLocationMatcherTest(unittest.TestCase):
    def setUp(self):
        self.buses = [
            {
                "odpt:busroute": "route-a",
                "trip_id": "trip-a",
                "vehicle_id": "vehicle-a",
            },
            {
                "odpt:busroute": "route-a",
                "trip_id": "trip-b",
                "vehicle_id": "vehicle-b",
            },
        ]

    def test_matches_route_and_trip_exactly(self):
        selected = select_bus_candidate(
            self.buses,
            route_id="route-a",
            trip_id="trip-b",
        )
        self.assertEqual(selected["vehicle_id"], "vehicle-b")

    def test_does_not_fall_back_to_another_trip(self):
        with self.assertRaises(BusLocationMatchError) as caught:
            select_bus_candidate(
                self.buses,
                route_id="route-a",
                trip_id="missing",
            )
        self.assertEqual(caught.exception.code, "bus_trip_not_found")

    def test_rejects_multiple_exact_matches(self):
        duplicates = [self.buses[0], dict(self.buses[0], vehicle_id="other")]
        with self.assertRaises(BusLocationMatchError) as caught:
            select_bus_candidate(
                duplicates,
                route_id="route-a",
                trip_id="trip-a",
            )
        self.assertEqual(caught.exception.code, "ambiguous_bus_trip")

    def test_rejects_a_changed_tracked_vehicle(self):
        with self.assertRaises(BusLocationMatchError) as caught:
            select_bus_candidate(
                self.buses,
                route_id="route-a",
                trip_id="trip-a",
                vehicle_id="vehicle-x",
            )
        self.assertEqual(caught.exception.code, "vehicle_not_found")


if __name__ == "__main__":
    unittest.main()

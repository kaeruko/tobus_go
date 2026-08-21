import os
import tempfile
import unittest

from gtfs_loader import GtfsFeedRegistry, GtfsRepository, gtfs_repo


def _write_feed(
    directory: str,
    *,
    route_name: str,
    origin_name: str,
    destination_name: str,
    departure: str = "10:00:00",
    arrival: str = "10:10:00",
) -> None:
    files = {
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WK,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            f"S1,{origin_name},35.0,139.0\n"
            f"S2,{destination_name},35.1,139.1\n"
        ),
        "routes.txt": (
            "route_id,route_short_name,route_type\n"
            f"R1,{route_name},3\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "R1,WK,T1,終点,0\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            f"T1,{departure},{departure},S1,1\n"
            f"T1,{arrival},{arrival},S2,2\n"
        ),
    }
    for filename, content in files.items():
        with open(
            os.path.join(directory, filename),
            "w",
            encoding="utf-8",
            newline="",
        ) as file:
            file.write(content)


class GtfsMultiFeedTest(unittest.TestCase):
    def test_repositories_are_normal_independent_instances(self):
        tokyo = GtfsRepository("toei_bus_test")
        nagoya = GtfsRepository("nagoya_bus_test")

        self.assertIsNot(tokyo, nagoya)
        self.assertEqual(tokyo.feed_id, "toei_bus_test")
        self.assertEqual(nagoya.feed_id, "nagoya_bus_test")

    def test_same_raw_ids_do_not_collide_between_feeds(self):
        with tempfile.TemporaryDirectory() as tokyo_dir, tempfile.TemporaryDirectory() as nagoya_dir:
            _write_feed(
                tokyo_dir,
                route_name="上２３",
                origin_name="平井七丁目",
                destination_name="社会福祉会館前",
            )
            _write_feed(
                nagoya_dir,
                route_name="名駅1",
                origin_name="名古屋駅",
                destination_name="栄",
            )

            registry = GtfsFeedRegistry()
            tokyo = registry.load("toei_bus", tokyo_dir)
            nagoya = registry.load("nagoya_bus", nagoya_dir)

            self.assertEqual(registry.feed_ids(), ("toei_bus", "nagoya_bus"))
            self.assertEqual(tokyo.routes["R1"]["route_short_name"], "上２３")
            self.assertEqual(nagoya.routes["R1"]["route_short_name"], "名駅1")
            self.assertEqual(tokyo.stops["S1"]["name"], "平井七丁目")
            self.assertEqual(nagoya.stops["S1"]["name"], "名古屋駅")
            self.assertEqual(tokyo.find_route_id_by_name("上23"), "R1")
            self.assertEqual(nagoya.find_route_id_by_name("名駅1"), "R1")
            self.assertEqual(tokyo.qualified_id("R1"), "toei_bus:R1")
            self.assertEqual(nagoya.qualified_id("R1"), "nagoya_bus:R1")

    def test_loading_one_feed_does_not_block_another(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            _write_feed(first_dir, route_name="東京", origin_name="A", destination_name="B")
            _write_feed(second_dir, route_name="名古屋", origin_name="C", destination_name="D")

            registry = GtfsFeedRegistry()
            first = registry.load("first", first_dir)
            second = registry.load("second", second_dir)

            self.assertTrue(first.is_loaded)
            self.assertTrue(second.is_loaded)
            self.assertIs(registry.get("first"), first)
            self.assertIs(registry.get("second"), second)

    def test_failed_feed_is_not_registered_and_loaded_feed_is_preserved(self):
        with tempfile.TemporaryDirectory() as good_dir, tempfile.TemporaryDirectory() as bad_dir:
            _write_feed(good_dir, route_name="東京", origin_name="A", destination_name="B")
            _write_feed(bad_dir, route_name="壊れたfeed", origin_name="X", destination_name="Y")
            os.remove(os.path.join(bad_dir, "stop_times.txt"))

            registry = GtfsFeedRegistry()
            good = registry.load("good", good_dir)

            with self.assertRaises(FileNotFoundError):
                registry.load("bad", bad_dir)

            self.assertEqual(registry.feed_ids(), ("good",))
            self.assertIs(registry.get("good"), good)
            self.assertEqual(good.routes["R1"]["route_short_name"], "東京")
            with self.assertRaises(KeyError):
                registry.get("bad")

    def test_parse_failure_leaves_repository_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_feed(directory, route_name="東京", origin_name="A", destination_name="B")
            with open(
                os.path.join(directory, "stop_times.txt"),
                "w",
                encoding="utf-8",
                newline="",
            ) as file:
                file.write(
                    "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                    "T1,10:00:00,10:00:00,UNKNOWN,1\n"
                )

            repository = GtfsRepository("broken")
            with self.assertRaises(ValueError):
                repository.load_data(directory)

            self.assertFalse(repository.is_loaded)
            self.assertIsNone(repository.source_dir)
            self.assertEqual(repository.stops, {})
            self.assertEqual(repository.routes, {})
            self.assertEqual(repository.trips, {})
            self.assertEqual(dict(repository.stop_times), {})

    def test_one_repository_cannot_be_rebound_to_another_source(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            _write_feed(first_dir, route_name="東京", origin_name="A", destination_name="B")
            _write_feed(second_dir, route_name="別feed", origin_name="C", destination_name="D")

            repository = GtfsRepository("fixed")
            repository.load_data(first_dir)
            with self.assertRaises(RuntimeError):
                repository.load_data(second_dir)

            self.assertEqual(repository.routes["R1"]["route_short_name"], "東京")

    def test_tokyo_compatibility_repository_is_feed_scoped(self):
        self.assertEqual(gtfs_repo.feed_id, "toei_bus")
        self.assertIsInstance(gtfs_repo, GtfsRepository)

    def test_tokyo_style_trip_lookup_still_works_with_regular_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_feed(
                directory,
                route_name="上２３",
                origin_name="平井七丁目",
                destination_name="社会福祉会館前",
                departure="13:30:00",
                arrival="13:40:00",
            )
            repository = GtfsRepository("toei_regression")
            repository.load_data(directory)

            leg = repository.find_next_trip_leg(
                "R1",
                "S1",
                "S2",
                earliest_departure_minute=13 * 60 + 19,
                active_service_ids=frozenset({"WK"}),
            )

            self.assertIsNotNone(leg)
            self.assertEqual(leg.trip_id, "T1")
            self.assertEqual(leg.departure_minute, 13 * 60 + 30)
            self.assertEqual(leg.arrival_minute, 13 * 60 + 40)


if __name__ == "__main__":
    unittest.main()

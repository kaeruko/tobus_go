"""Rail identity enrichment must retain the run chosen by the search."""

import copy
import unittest
from types import SimpleNamespace

from app.services.train_realtime import StaticTrainGtfs, StaticTrainStop, StaticTrainTrip
from app.services.train_route_identity import enrich_route_result_train_trip_ids


STATIONS = (
    "odpt.Station:Toei.Asakusa.A",
    "odpt.Station:Toei.Asakusa.B",
    "odpt.Station:Toei.Asakusa.C",
)


def _trip(trip_id, departure):
    def clock(minute):
        return f"{minute // 60:02d}:{minute % 60:02d}:00"
    return StaticTrainTrip(
        trip_id=trip_id,
        route_id="rail-route",
        headsign="C",
        stops=(
            StaticTrainStop(1, "static-A", "A", clock(departure), clock(departure), stop_code="A1"),
            StaticTrainStop(2, "static-B", "B", "10:15:00", "10:16:00", stop_code="A2"),
            StaticTrainStop(3, "static-C", "C", "10:20:00", "10:20:00", stop_code="A3"),
        ),
    )


class TrainSelectedRunIdentityTest(unittest.TestCase):
    def setUp(self):
        self.source = {
            STATIONS[0]: [
                {"dep": 610, "arr": 615, "next_sta": STATIONS[1], "train_num": "N1",
                 "run_key": "run-first", "stop_sequence": 0},
                {"dep": 611, "arr": 615, "next_sta": STATIONS[1], "train_num": "N2",
                 "run_key": "run-selected", "stop_sequence": 0},
            ],
            STATIONS[1]: [
                {"dep": 616, "arr": 620, "next_sta": STATIONS[2], "train_num": "N1",
                 "run_key": "run-first", "stop_sequence": 1},
                {"dep": 616, "arr": 620, "next_sta": STATIONS[2], "train_num": "N2",
                 "run_key": "run-selected", "stop_sequence": 1},
            ],
        }
        self.manager = SimpleNamespace(
            train_patterns_weekday=self.source,
            train_patterns_weekend={},
            realtime_delays={},
            train_status_text={},
        )
        first, selected = _trip("trip-first", 610), _trip("trip-selected", 611)
        self.static = StaticTrainGtfs(trips={first.trip_id: first, selected.trip_id: selected})

    def _candidate(self, *, delay=0):
        records = []
        for origin, source_records in self.source.items():
            record = dict(next(record for record in source_records if record["train_num"] == "N2"))
            record.update(origin_id=origin, actual_dep=record["dep"] + delay,
                          actual_arr=record["arr"] + delay)
            records.append(record)
        selected = {
            "provider": "rail",
            "service_key": "weekday",
            "run_key": "run-selected",
            "train_number": "N2",
            "origin_sequence": 0,
            "destination_sequence": 2,
            "scheduled_departure_minute": 611,
            "scheduled_arrival_minute": 620,
            "actual_departure_minute": 611 + delay,
            "actual_arrival_minute": 620 + delay,
            "segment_records": records,
        }
        return {
            "id": "Fastest",
            "steps": [{
                "step_id": "rail-1", "kind": "rail", "title": "浅草線",
                "from_": "A", "to": "C", "departure_time": "10:02",
                "arrival_time": f"{(620 + delay) // 60:02d}:{(620 + delay) % 60:02d}",
                "boarding_minutes": 2, "route_id": None, "trip_id": None,
                "selected_run": selected,
                "stops": [
                    {"id": f"A{index + 1}", "odpt_id": station, "name": chr(65 + index)}
                    for index, station in enumerate(STATIONS)
                ],
            }],
        }

    def _enrich(self, candidate, *, day_type="weekday"):
        return enrich_route_result_train_trip_ids(
            {"candidates": [candidate], "meta": {}},
            timetable_manager=self.manager,
            day_type=day_type,
            static_gtfs=self.static,
        )

    def test_selected_train_resolves_when_other_train_has_same_arrival(self):
        candidate = self._candidate()
        original = copy.deepcopy(candidate)
        result = self._enrich(candidate)
        self.assertEqual(len(result["candidates"]), 1)
        step = result["candidates"][0]["steps"][0]
        self.assertEqual(step["trip_id"], "trip-selected")
        self.assertEqual(step["departure_time"], "10:11")
        self.assertEqual(step["arrival_time"], "10:20")
        self.assertEqual(step["minutes"], 9)
        self.assertNotIn("selected_run", step)
        self.assertEqual(candidate["steps"][0]["selected_run"], original["steps"][0]["selected_run"])

    def test_live_delay_change_does_not_change_selected_snapshot_clocks(self):
        candidate = self._candidate(delay=5)
        self.manager.realtime_delays = {"N2": 20 * 60}
        self.manager.train_status_text = {"odpt.Railway:Toei.Asakusa": "遅延"}
        result = self._enrich(candidate)
        step = result["candidates"][0]["steps"][0]
        self.assertEqual(step["trip_id"], "trip-selected")
        self.assertEqual(step["departure_time"], "10:16")
        self.assertEqual(step["arrival_time"], "10:25")

    def test_conflicting_selected_identity_or_clocks_are_rejected(self):
        changes = (
            ("provider", "bus"),
            ("run_key", "other-run"),
            ("scheduled_departure_minute", 610),
            ("actual_arrival_minute", 621),
            ("actual_departure_minute", float("nan")),
            ("origin_sequence", 1),
            ("destination_sequence", 3),
        )
        for field, value in changes:
            with self.subTest(field=field):
                candidate = self._candidate()
                candidate["steps"][0]["selected_run"][field] = value
                result = self._enrich(candidate)
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["meta"]["train_identity_rejected_candidates"][0]["code"],
                                 "rail_selected_run_invalid")

    def test_segment_clock_or_train_switch_is_rejected(self):
        for field, value in (("actual_arr", 614), ("train_num", "N1"), ("next_sta", STATIONS[0])):
            with self.subTest(field=field):
                candidate = self._candidate()
                candidate["steps"][0]["selected_run"]["segment_records"][0][field] = value
                self.assertEqual(self._enrich(candidate)["candidates"], [])

    def test_selected_run_cannot_be_replaced_by_same_number_at_another_run_key(self):
        for records in self.source.values():
            for record in records:
                if record["train_num"] == "N2":
                    record["run_key"] = "different-source-run"
        candidate = self._candidate()
        for record in candidate["steps"][0]["selected_run"]["segment_records"]:
            record["run_key"] = "run-selected"
        self.assertEqual(self._enrich(candidate)["candidates"], [])

    def test_selected_run_must_exist_in_requested_service_timetable(self):
        self.assertEqual(self._enrich(self._candidate(), day_type="holiday")["candidates"], [])

    def test_selected_weekend_run_obeys_its_source_calendar(self):
        self.manager.train_patterns_weekend = self.source
        for day, calendar, valid in (
            ("holiday", "Saturday", False),
            ("saturday", "Holiday", False),
            ("holiday", "SaturdayHoliday", True),
            ("saturday", "SaturdayHoliday", True),
        ):
            with self.subTest(day=day, calendar=calendar):
                candidate = self._candidate()
                candidate["steps"][0]["selected_run"]["service_key"] = day
                for records in self.source.values():
                    for record in records:
                        record["calendar"] = f"odpt.Calendar:{calendar}"
                result = self._enrich(candidate, day_type=day)
                self.assertEqual(bool(result["candidates"]), valid)

    def test_legacy_source_without_run_keys_uses_exact_scheduled_records(self):
        candidate = self._candidate()
        for records in self.source.values():
            for record in records:
                record.pop("run_key")
                record.pop("stop_sequence")
        result = self._enrich(candidate)
        self.assertEqual(result["candidates"][0]["steps"][0]["trip_id"], "trip-selected")

    def test_missing_selected_metadata_rejects_instead_of_reselecting(self):
        candidate = self._candidate()
        candidate["steps"][0]["selected_run"] = None
        self.assertEqual(self._enrich(candidate)["candidates"], [])


if __name__ == "__main__":
    unittest.main()

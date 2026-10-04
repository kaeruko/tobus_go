import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from toei_engine import TimetableManager, ensure_train_run_metadata


class TokyoTrainRunMigrationTest(unittest.TestCase):
    def _old_manager(self):
        manager = TimetableManager()
        manager.train_patterns_weekday = {
            "A": [{"dep": 600, "arr": 605, "next_sta": "B", "train_num": "N1"}]
        }
        return manager

    def test_local_source_upgrades_only_rail_and_retains_realtime(self):
        manager = self._old_manager()
        manager.realtime_delays = {"N1": 120}
        manager.bus_departures_weekday = {"bus-stop": {"route": []}}
        realtime = manager.realtime_delays
        bus_data = manager.bus_departures_weekday
        source = [{
            "owl:sameAs": "run:N1", "odpt:trainNumber": "N1",
            "odpt:calendar": "odpt.Calendar:Weekday",
            "odpt:trainTimetableObject": [
                {"odpt:departureStation": "A", "odpt:departureTime": "10:00"},
                {"odpt:arrivalStation": "B", "odpt:arrivalTime": "10:05"},
            ],
        }]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trains.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(ensure_train_run_metadata(manager, str(path)))
        record = manager.train_patterns_weekday["A"][0]
        self.assertEqual(record["run_key"], "run:N1")
        self.assertEqual(record["stop_sequence"], 0)
        self.assertEqual(record["calendar"], "odpt.Calendar:Weekday")
        self.assertIs(manager.realtime_delays, realtime)
        self.assertIs(manager.bus_departures_weekday, bus_data)
        self.assertEqual(manager.train_run_schema_version, 1)
        # Updated artifacts require no raw file on Lambda startup.
        self.assertFalse(ensure_train_run_metadata(manager, None))

    def test_old_artifact_without_source_fails_instead_of_guessing(self):
        manager = self._old_manager()
        original = manager.train_patterns_weekday
        with self.assertRaisesRegex(RuntimeError, "rebuild app_data.pkl"):
            ensure_train_run_metadata(manager, None)
        self.assertIs(manager.train_patterns_weekday, original)

    def test_failed_upgrade_does_not_replace_static_data(self):
        manager = self._old_manager()
        original = manager.train_patterns_weekday
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trains.json"
            path.write_text("invalid json", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                ensure_train_run_metadata(manager, str(path))
        self.assertIs(manager.train_patterns_weekday, original)


if __name__ == "__main__":
    unittest.main()

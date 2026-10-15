"""Tokyo input probe uses synthetic ODPT and explicitly trusted local pickle."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import pickle
import sys
import tempfile
import unittest
from unittest.mock import patch

from toei_engine import TimetableManager

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_tokyo_odpt_local.py"
spec = importlib.util.spec_from_file_location("tokyo_odpt_local_check", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

RAILWAY = "odpt.Railway:Test.Line"
A, B, C = [f"odpt.Station:Test.Line.{s}" for s in "ABC"]


def entry(run="run1", calendar="odpt.Calendar:Weekday"):
    return {"owl:sameAs": run, "odpt:railway": RAILWAY, "odpt:trainNumber": "1",
        "odpt:calendar": calendar, "dc:date": "2026-10-01T00:00:00+09:00",
        "odpt:trainTimetableObject": [
            {"odpt:departureStation": A, "odpt:departureTime": "23:58"},
            {"odpt:arrivalStation": B, "odpt:departureStation": B,
             "odpt:arrivalTime": "00:01", "odpt:departureTime": "00:02"},
            {"odpt:arrivalStation": A, "odpt:arrivalTime": "00:05"}]}


class TokyoOdptLocalCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "trains.json"

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def shared_files(self):
        stations = Path(self.tmp.name) / 'stations.json'
        stations.write_text(json.dumps([{'owl:sameAs': s, 'dc:title': s,
            'geo:lat': 35., 'geo:long': 139.} for s in (A, B)]), encoding='utf-8')
        railways = Path(self.tmp.name) / 'railways.json'
        railways.write_text(json.dumps([{'owl:sameAs': RAILWAY, 'dc:title': 'Rail'}]), encoding='utf-8')
        return stations, railways

    def test_shared_ordered_adapter_and_choices_match_all_legacy_profiles(self):
        self.write([entry(), entry('sat', 'odpt.Calendar:Saturday'),
                    entry('hol', 'odpt.Calendar:Holiday'), entry('both', 'odpt.Calendar:SaturdayHoliday')])
        stations, railways = self.shared_files()
        originals = [p.read_bytes() for p in (self.path, stations, railways)]
        result = probe.inspect(self.path, stations_path=stations, railways_path=railways)
        self.assertTrue(result['shared_adapter_verified'])
        self.assertEqual(result['shared_choices'], result['choices'])
        self.assertEqual(result['calendar_projection'], 'legacy_day_profile_test_only')
        self.assertFalse(result['operational_calendar_verified'])
        self.assertEqual(originals, [p.read_bytes() for p in (self.path, stations, railways)])

    def test_shared_first_after_midnight_run_is_not_shifted_by_fixed_boundary(self):
        data = entry()
        for obj in data['odpt:trainTimetableObject']:
            for key in ('odpt:arrivalTime', 'odpt:departureTime'):
                if key in obj:
                    obj[key] = {'23:58': '00:00', '00:01': '00:01',
                                '00:02': '00:02', '00:05': '00:05'}[obj[key]]
        self.write([data])
        stations, railways = self.shared_files()
        result = probe.inspect(self.path, stations_path=stations, railways_path=railways)
        self.assertTrue(result['shared_adapter_verified'])
        self.assertEqual(result['shared_choices'][0]['intervals'], 2)

    def test_shared_invalid_coordinates_stop_instead_of_dropping_source_station(self):
        self.write([entry()])
        stations, railways = self.shared_files()
        data = json.loads(stations.read_text())
        del data[0]['geo:lat']
        stations.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'invalid coordinates'):
            probe.inspect(self.path, stations_path=stations, railways_path=railways)

    def test_shared_cli_requires_explicit_complete_input_set(self):
        for extra in (['--shared-rail'], ['--stations', 'unused.json']):
            with patch.object(sys, 'argv', [str(SCRIPT), '--train-timetables', str(self.path),
                                           '--expected-sha', 'a'*40, *extra]):
                with patch.object(probe, 'check_repository') as guard:
                    with self.assertRaisesRegex(ValueError, '--shared-rail requires'):
                        probe.main()
                    guard.assert_not_called()

    def test_explicit_dates_include_weekday_saturday_sunday_and_public_holiday(self):
        self.write([entry(), entry('sat', 'odpt.Calendar:Saturday'),
                    entry('hol', 'odpt.Calendar:Holiday'), entry('both', 'odpt.Calendar:SaturdayHoliday')])
        stations, railways = self.shared_files()
        manager = TimetableManager()
        with contextlib.redirect_stdout(io.StringIO()):
            manager.load_train_timetables(str(self.path))
        prebuilt = Path(self.tmp.name) / 'dated.pkl'
        prebuilt.write_bytes(pickle.dumps({'TM': manager}))
        before = prebuilt.read_bytes()
        result = probe.inspect(self.path, prebuilt, stations_path=stations, railways_path=railways,
                               query_dates=('2026-09-04', '2026-09-05', '2026-09-06', '2026-01-01'))
        self.assertTrue(result['legacy_date_policy_verified'])
        self.assertFalse(result['operational_calendar_verified'])
        self.assertEqual(result['date_choices'], result['shared_date_choices'])
        self.assertEqual(result['prebuilt_date_choices'], result['shared_date_choices'])
        self.assertEqual(prebuilt.read_bytes(), before)
        self.assertEqual([r['profile'] for r in result['shared_date_choices']],
                         ['weekday', 'saturday', 'holiday', 'holiday'])
        self.assertEqual([r['intervals'] for r in result['shared_date_choices']], [2, 4, 4, 4])
        self.assertIsInstance(result['holiday_dependency_version'], str)

    def test_date_scope_invalid_duplicate_missing_dependency_and_policy_mismatch_fail(self):
        for values in (('2026-9-4',), ('invalid',), ('2026-09-04', '2026-09-04')):
            with self.subTest(values=values), self.assertRaises(ValueError):
                probe.resolve_probe_dates(values)
        with patch.dict(sys.modules, {'jpholiday': None}):
            with self.assertRaises(ModuleNotFoundError):
                probe.resolve_probe_dates(('2026-09-04',))
        with patch.object(probe, 'determine_day_type', return_value='holiday'):
            with self.assertRaisesRegex(AssertionError, 'date policy disagrees'):
                probe.resolve_probe_dates(('2026-09-04',))
        with self.assertRaisesRegex(ValueError, 'shared rail inputs'):
            probe.inspect(self.path, query_dates=('2026-09-04',))

    def test_unknown_calendar_not_inferred_for_real_date_comparison(self):
        self.write([entry(calendar='odpt.Calendar:Unknown')])
        stations, railways = self.shared_files()
        with self.assertRaisesRegex(ValueError, 'unsupported calendar'):
            probe.inspect(self.path, stations_path=stations, railways_path=railways,
                          query_dates=('2026-09-04',))

    def test_midnight_circular_and_separate_calendars_preserve_occurrences(self):
        self.write([entry(), entry("sat", "odpt.Calendar:Saturday"),
                    entry("hol", "odpt.Calendar:Holiday"),
                    entry("both", "odpt.Calendar:SaturdayHoliday")])
        before = self.path.read_bytes()
        result = probe.inspect(self.path)
        self.assertEqual(result["source_intervals"], 8)
        self.assertEqual(result["runs_with_repeated_stops"], 4)
        self.assertEqual([r["intervals"] for r in result["choices"]], [2, 4, 4])
        self.assertGreater(result["legacy_rollover_additions"], 0)
        self.assertFalse(result["shared_adapter_verified"])
        self.assertFalse(result["operational_calendar_verified"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_source_seconds_never_rewritten_for_legacy_loader(self):
        data = entry()
        data["odpt:trainTimetableObject"][0]["odpt:departureTime"] = "23:58:01"
        self.write([data])
        with patch.object(TimetableManager, "load_train_timetables") as loader:
            with self.assertRaisesRegex(ValueError, "precision must not be rewritten"):
                probe.inspect(self.path)
            loader.assert_not_called()

    def test_bad_clock_preserves_parse_exception(self):
        data = entry()
        data["odpt:trainTimetableObject"][0]["odpt:departureTime"] = "23:88"
        self.write([data])
        with self.assertRaisesRegex(ValueError, "invalid service time") as result:
            probe.inspect(self.path)
        self.assertIsInstance(result.exception.__cause__, ValueError)
        self.assertIn("run1 sequence=0", str(result.exception))

    def test_duplicate_missing_identity_and_station_mismatch_fail(self):
        bad = entry()
        del bad["owl:sameAs"]
        wrong = entry()
        wrong["odpt:trainTimetableObject"][0]["odpt:departureStation"] = "odpt.Station:Other.Line.A"
        for data in ([entry(), entry()], [bad], [wrong]):
            with self.subTest(data=data):
                self.write(data)
                with self.assertRaises(ValueError):
                    probe.inspect(self.path)

    def test_explicit_envelopes_and_invalid_schema(self):
        for value in (entry(), [entry()], {"result": [entry()]}):
            self.write(value)
            self.assertEqual(probe.inspect(self.path)["source_intervals"], 2)
        for value in ([], 0, {"result": {}}, [None]):
            self.write(value)
            with self.assertRaises(ValueError):
                probe.inspect(self.path)

    def test_prebuilt_equal_and_stale_fails_without_repair(self):
        self.write([entry()])
        manager = TimetableManager()
        with contextlib.redirect_stdout(io.StringIO()):
            manager.load_train_timetables(str(self.path))
        path = Path(self.tmp.name) / "trusted.pkl"
        path.write_bytes(pickle.dumps({"TM": manager}))
        before = path.read_bytes()
        self.assertTrue(probe.inspect(self.path, path)["prebuilt_verified"])
        self.assertEqual(path.read_bytes(), before)
        manager.train_patterns_weekday[A][0]["dep"] += 1
        path.write_bytes(pickle.dumps({"TM": manager}))
        stale = path.read_bytes()
        with self.assertRaisesRegex(AssertionError, "prebuilt TM differs"):
            probe.inspect(self.path, path)
        self.assertEqual(path.read_bytes(), stale)
        del manager.train_patterns_weekday[A][0]["stop_sequence"]
        path.write_bytes(pickle.dumps({"TM": manager}))
        with self.assertRaisesRegex(ValueError, "repair is not performed"):
            probe.inspect(self.path, path)

    def test_wrong_sha_stops_before_input_load_and_success_marker(self):
        with patch.object(probe, "git", return_value="b" * 40), patch.object(probe, "inspect") as inspect:
            with patch.object(sys, "argv", [str(SCRIPT), "--train-timetables", str(self.path),
                                           "--expected-sha", "a" * 40]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaisesRegex(ValueError, "clean main"):
                    probe.main()
                self.assertNotIn("READ_ONLY_TOKYO_RAIL_INPUT_OK", output.getvalue())
                inspect.assert_not_called()

    def test_changed_input_stops_without_success_marker(self):
        self.write([entry()])
        with patch.object(probe, "check_repository"), patch.object(probe, "sha256", side_effect=["old", "new"]):
            with patch.object(sys, "argv", [str(SCRIPT), "--train-timetables", str(self.path),
                                           "--expected-sha", "a" * 40]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaisesRegex(AssertionError, "input files changed"):
                    probe.main()
                self.assertNotIn("READ_ONLY_TOKYO_RAIL_INPUT_OK", output.getvalue())

    def test_cli_success_reports_explicit_unverified_gates_and_input_hash(self):
        self.write([entry()])
        with patch.object(probe, "check_repository") as guard:
            with patch.object(sys, "argv", [str(SCRIPT), "--train-timetables", str(self.path),
                                           "--expected-sha", "a" * 40]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    probe.main()
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[-1], "READ_ONLY_TOKYO_RAIL_INPUT_OK")
        report = json.loads(lines[-2])
        self.assertEqual(report["input_hashes"]["train_timetables"], probe.sha256(self.path))
        self.assertFalse(report["shared_adapter_verified"])
        self.assertFalse(report["prebuilt_verified"])
        self.assertEqual(guard.call_count, 2)

    def test_missing_arrival_interior_and_24_hour_clocks_match_explicit_legacy_rules(self):
        data = entry()
        data["odpt:trainTimetableObject"][0]["odpt:departureTime"] = "24:01"
        del data["odpt:trainTimetableObject"][1]["odpt:arrivalTime"]
        data["odpt:trainTimetableObject"][1]["odpt:departureTime"] = "24:03"
        data["odpt:trainTimetableObject"][2]["odpt:arrivalTime"] = "24:05"
        self.write([data])
        result = probe.inspect(self.path)
        self.assertEqual(result["source_intervals"], 1)
        self.assertEqual(result["missing_arrival_clocks"], 2)
        self.assertEqual(result["source_clock_max_seconds"], 24*3600 + 5*60)

    def test_invalid_utf8_and_json_are_original_exceptions(self):
        self.path.write_bytes(b'\xff')
        with self.assertRaises(UnicodeDecodeError):
            probe.inspect(self.path)
        self.path.write_text('[', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            probe.inspect(self.path)


if __name__ == "__main__":
    unittest.main()

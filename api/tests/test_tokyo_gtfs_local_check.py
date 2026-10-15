"""Synthetic Tokyo bus GTFS comparison; no private feed or credentials."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import test_transit_dataset as fixtures

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/check_tokyo_gtfs_local.py'
spec = importlib.util.spec_from_file_location('tokyo_gtfs_local_check', SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TokyoGtfsLocalCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixtures.TransitDatasetTest()._write_gtfs(str(self.root))
        (self.root / 'feed_info.txt').write_text('feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n', encoding='utf-8')
        (self.root / 'calendar_dates.txt').write_text('service_id,date,exception_type\nweekday,20260905,1\n', encoding='utf-8')

    def run_probe(self, *dates):
        return probe.inspect(self.root, 'fixture', dates or ('2026-09-04',))

    def test_all_records_active_calendar_exceptions_and_choices_match_readonly(self):
        before = probe.fingerprints(self.root)
        result = self.run_probe('2026-09-04', '2026-09-05')
        self.assertTrue(result['source_metadata_verified'])
        self.assertTrue(result['bus_choice_parity_verified'])
        self.assertEqual([r['intervals'] for r in result['date_choices']], [3, 3])
        self.assertEqual(result['stop_times'], 6)
        self.assertFalse(result['production_graph_verified'])
        self.assertFalse(result['route_ranking_verified'])
        self.assertEqual(before, probe.fingerprints(self.root))

    def test_seconds_not_rounded_before_legacy_load(self):
        path = self.root / 'stop_times.txt'
        path.write_text(path.read_text().replace('10:00:00', '10:00:01'), encoding='utf-8')
        with patch.object(probe.GtfsRepository, 'load_data') as load:
            with self.assertRaisesRegex(ValueError, 'exact minute-aligned'):
                self.run_probe()
            load.assert_not_called()

    def test_nonzero_boarding_flag_stops_without_disabling_shared_constraint(self):
        path = self.root / 'stop_times.txt'
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + ',pickup_type\n' + '\n'.join(line + ',1' for line in lines[1:]) + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'ignores boarding/alighting flags'):
            self.run_probe()

    def test_terminal_pickup_and_initial_dropoff_restrictions_are_preserved(self):
        path = self.root / 'stop_times.txt'
        lines = path.read_text().splitlines()
        result = [lines[0] + ',pickup_type,drop_off_type']
        for line in lines[1:]:
            first = line.endswith(',1')
            result.append(line + (',0,1' if first else ',1,0'))
        path.write_text('\n'.join(result) + '\n', encoding='utf-8')
        self.assertTrue(self.run_probe()['bus_choice_parity_verified'])

    def test_exception_only_service_is_compared_without_a_fabricated_calendar(self):
        (self.root / 'calendar.txt').unlink()
        result = self.run_probe('2026-09-05')
        self.assertEqual(result['date_choices'][0]['active_services'], 1)
        self.assertTrue(result['bus_choice_parity_verified'])

    def test_version_dates_frequencies_and_no_active_trips_fail(self):
        with self.assertRaisesRegex(ValueError, 'expected feed version'):
            probe.inspect(self.root, 'other', ('2026-09-04',))
        for dates in (('2027-01-01',), ('2026-9-4',), ('2026-09-04', '2026-09-04')):
            with self.subTest(dates=dates), self.assertRaises(ValueError):
                self.run_probe(*dates)
        with self.assertRaisesRegex(ValueError, 'no active source trips'):
            self.run_probe('2026-09-06')
        (self.root / 'frequencies.txt').write_text('trip_id,start_time,end_time,headway_secs\nt1,10:00:00,11:00:00,600\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'frequency-based trips unsupported'):
            self.run_probe()

    def test_cli_hash_change_and_wrong_sha_never_emit_success(self):
        args = [str(SCRIPT), '--gtfs-dir', str(self.root), '--expected-feed-version', 'fixture',
                '--query-date', '2026-09-04', '--expected-sha', 'a'*40]
        with patch.object(sys, 'argv', args), patch.object(probe, 'check_repository'):
            with patch.object(probe, 'fingerprints', side_effect=[{'x': 'old'}, {'x': 'new'}]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaisesRegex(AssertionError, 'input files changed'):
                    probe.main()
                self.assertNotIn('READ_ONLY_TOKYO_BUS_INPUT_OK', output.getvalue())
        with patch.object(sys, 'argv', args), patch.object(probe, 'check_repository', side_effect=ValueError('SHA mismatch')):
            with patch.object(probe, 'inspect') as inspect:
                with self.assertRaisesRegex(ValueError, 'SHA mismatch'):
                    probe.main()
                inspect.assert_not_called()

    def test_cli_success_reports_only_counts_hashes_and_explicit_unverified_gates(self):
        args = [str(SCRIPT), '--gtfs-dir', str(self.root), '--expected-feed-version', 'fixture',
                '--query-date', '2026-09-04', '--expected-sha', 'a'*40]
        with patch.object(sys, 'argv', args), patch.object(probe, 'check_repository') as guard:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                probe.main()
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[-1], 'READ_ONLY_TOKYO_BUS_INPUT_OK')
        result = json.loads(lines[-2])
        self.assertEqual(result['input_hashes'], probe.fingerprints(self.root))
        self.assertFalse(result['compiled_gtfs_verified'])
        self.assertEqual(guard.call_count, 2)


if __name__ == '__main__':
    unittest.main()

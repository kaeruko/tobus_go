"""Synthetic Tokyo bus GTFS comparison; no private feed or credentials."""
import contextlib
import importlib.util
import io
import json
import pickle
from pathlib import Path
import sys
import tempfile
import unittest
import networkx as nx
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

    def test_pickup_one_is_preserved_and_excluded_from_new_boarding(self):
        path = self.root / 'stop_times.txt'
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + ',pickup_type\n' + '\n'.join(line + ',1' for line in lines[1:]) + '\n', encoding='utf-8')
        result = self.run_probe()
        self.assertTrue(result['bus_choice_parity_verified'])
        self.assertTrue(result['compiled_memory_choices_verified'])
        self.assertEqual(result['date_choices'][0]['intervals'], 0)
        self.assertEqual(result['stop_times'], 6)

    def test_contract_error_reports_all_flags_dates_and_bounded_local_examples_before_legacy_load(self):
        path = self.root / 'stop_times.txt'
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + ',pickup_type,drop_off_type\n' +
            '\n'.join(line + ',2,3' for line in lines[1:]) + '\n', encoding='utf-8')
        before = probe.fingerprints(self.root)
        with patch.object(probe.GtfsRepository, 'load_data') as loader:
            with self.assertRaises(probe.TokyoBoardingContractError) as error:
                self.run_probe('2026-09-04', '2026-09-05', '2026-09-06')
            loader.assert_not_called()
        report = error.exception.diagnostics
        self.assertEqual(report['conflicting_rows'], 6)
        self.assertEqual(report['boarding_conflicts'], 3)
        self.assertEqual(report['alighting_conflicts'], 3)
        self.assertEqual(report['affected_trips'], 3)
        self.assertEqual([r['conflicting_rows'] for r in report['dates']], [6, 6, 0])
        self.assertEqual([r['affected_trips'] for r in report['dates']], [3, 3, 0])
        self.assertEqual(len(report['examples']), 5)
        self.assertEqual(report['examples'][0]['pickup_type'], 2)
        self.assertEqual(report['examples'][0]['drop_off_type'], 3)
        self.assertFalse(report['production_graph_reachability_verified'])
        self.assertIsInstance(error.exception, ValueError)
        self.assertEqual(before, probe.fingerprints(self.root))

    def test_contract_error_still_emits_no_success_marker(self):
        path = self.root / 'stop_times.txt'
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + ',pickup_type\n' + '\n'.join(line + ',2' for line in lines[1:]) + '\n', encoding='utf-8')
        args = [str(SCRIPT), '--gtfs-dir', str(self.root), '--expected-feed-version', 'fixture',
                '--query-date', '2026-09-04', '--expected-sha', 'a'*40]
        with patch.object(sys, 'argv', args), patch.object(probe, 'check_repository'):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(probe.TokyoBoardingContractError):
                probe.main()
            self.assertNotIn('READ_ONLY_TOKYO_BUS_INPUT_OK', output.getvalue())

    def audit_fixture(self, *, board=True, mode='bus'):
        path = self.root / 'stop_times.txt'
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + ',pickup_type\n' +
            '\n'.join(line + (',1' if line.startswith('t1,') else ',0') for line in lines[1:]) + '\n', encoding='utf-8')
        graph = nx.DiGraph()
        for stop in ('a', 'b'):
            graph.add_node(('phys', stop))
            graph.add_node(('line', stop, 'fixture'), mode=mode, route_id='r1')
        graph.add_edge(('line', 'a', 'fixture'), ('line', 'b', 'fixture'), etype='ride', mode=mode)
        if board:
            graph.add_edge(('phys', 'a'), ('line', 'a', 'fixture'), etype='board')
        prebuilt = self.root / 'trusted.pkl'
        prebuilt.write_bytes(pickle.dumps({'G': graph, 'TM': probe.TimetableManager()}))
        return prebuilt

    def test_explicit_prebuilt_audit_confirms_pickup_one_blocked_without_marking_parity(self):
        prebuilt = self.audit_fixture()
        before = prebuilt.read_bytes()
        result = probe.audit_production_boarding(self.root, 'fixture', ('2026-09-04',), prebuilt)
        row = result['date_audit'][0]
        self.assertEqual(row['active_conflicting_rows'], 1)
        self.assertEqual(row['boardable_conflicting_rows'], 0)
        self.assertEqual(row['rideable_conflicting_rows'], 0)
        self.assertEqual(row['bound_not_boardable_rows'], 1)
        self.assertFalse(result['bus_choice_parity_verified'])
        self.assertEqual(prebuilt.read_bytes(), before)

    def test_prebuilt_audit_absent_board_edge_is_distinct_from_graph_binding(self):
        prebuilt = self.audit_fixture(board=False)
        row = probe.audit_production_boarding(self.root, 'fixture', ('2026-09-04',), prebuilt)['date_audit'][0]
        self.assertEqual(row['missing_boarding_binding_rows'], 1)
        self.assertEqual(row['boardable_conflicting_rows'], 0)

    def test_prebuilt_audit_preserves_legacy_default_for_missing_ride_mode(self):
        prebuilt = self.audit_fixture()
        with prebuilt.open('rb') as stream:
            data = pickle.load(stream)
        del data['G'][('line', 'a', 'fixture')][('line', 'b', 'fixture')]['mode']
        prebuilt.write_bytes(pickle.dumps(data))
        row = probe.audit_production_boarding(self.root, 'fixture', ('2026-09-04',), prebuilt)['date_audit'][0]
        self.assertEqual(row['rideable_conflicting_rows'], 0)

    def test_prebuilt_audit_terminal_filter_can_prevent_existing_boarding(self):
        prebuilt = self.audit_fixture()
        with prebuilt.open('rb') as stream:
            data = pickle.load(stream)
        graph = nx.relabel_nodes(data['G'], {('line', s, 'fixture'): ('line', s, 'buspat:fixture') for s in ('a', 'b')})
        graph.add_node(('line', 'c', 'buspat:fixture'), mode='bus', route_id='r1')
        graph.add_edge(('line', 'b', 'buspat:fixture'), ('line', 'c', 'buspat:fixture'), etype='ride', mode='bus')
        manager = probe.TimetableManager()
        manager.pattern_stops_map['fixture'] = ['a', 'b', 'c']
        prebuilt.write_bytes(pickle.dumps({'G': graph, 'TM': manager}))
        row = probe.audit_production_boarding(self.root, 'fixture', ('2026-09-04',), prebuilt)['date_audit'][0]
        self.assertEqual(row['bound_not_boardable_rows'], 1)
        self.assertEqual(row['rideable_conflicting_rows'], 0)

    def test_audit_cli_has_distinct_marker_and_hashes_prebuilt_without_claiming_parity(self):
        prebuilt = self.audit_fixture()
        args = [str(SCRIPT), '--gtfs-dir', str(self.root), '--expected-feed-version', 'fixture',
                '--query-date', '2026-09-04', '--expected-sha', 'a'*40,
                '--audit-production-boarding', '--trusted-prebuilt', str(prebuilt)]
        with patch.object(sys, 'argv', args), patch.object(probe, 'check_repository'):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                probe.main()
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[-1], 'READ_ONLY_TOKYO_BOARDING_AUDIT_OK')
        self.assertNotIn('READ_ONLY_TOKYO_BUS_INPUT_OK', lines)
        self.assertEqual(json.loads(lines[-2])['input_hashes']['trusted_prebuilt'], probe.sha256(prebuilt))
        for option in (['--audit-production-boarding'], ['--trusted-prebuilt', str(prebuilt)]):
            with patch.object(sys, 'argv', args[:-3] + option), patch.object(probe, 'check_repository') as guard:
                with self.assertRaisesRegex(ValueError, 'requires explicit'):
                    probe.main()
                guard.assert_not_called()

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

"""The rail A* input audit is static, complete, fail-fast and read-only."""
import contextlib
from dataclasses import replace
from fractions import Fraction
import importlib.util
import io
import json
import math
from pathlib import Path
import pickle
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from route_engine import RouteContractError
from tokyo_dataset_rail_choices import TokyoRailDatasetBinding
import tokyo_rail_interval_audit as audit
from tests import test_tokyo_dataset_rail_choices as shared
from tests import test_tokyo_waiting_contract as rail


SCRIPT = Path(__file__).resolve().parents[2]/'scripts/check_tokyo_rail_bounds_local.py'
spec = importlib.util.spec_from_file_location('rail_bounds_probe', SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TokyoRailIntervalAuditTest(unittest.TestCase):
    def fixture(self, *runs):
        source = shared.TokyoDatasetRailChoicesTest()
        source.fixture(*runs)
        self.source = source
        self.binding, self.manager = source.binding, source.manager
        self.snapshot = source.snapshot

    def verify(self, **kwargs):
        return audit.verify_static_rail_interval_minima(self.binding, self.manager, **kwargs)

    def inputs(self, root):
        paths = tuple(root/name for name in ('train.json', 'stations.json', 'railways.json', 'trusted.pkl'))
        for path, data in zip(paths[:3], (self.source.runs, self.source.stations, self.source.railways)):
            path.write_text(json.dumps(data), encoding='utf-8')
        # This gate needs no G: inspecting/projecting the supplied graph is a
        # separate stage, even if the trusted real artifact also contains one.
        paths[3].write_bytes(pickle.dumps({'TM':self.manager}))
        return paths

    def arguments(self, paths):
        return [str(SCRIPT), '--train-timetables', str(paths[0]), '--stations', str(paths[1]),
                '--railways', str(paths[2]), '--trusted-prebuilt', str(paths[3]), '--expected-sha', 'a'*40]

    def test_all_calendars_and_later_fast_runs_contribute_departure_after_dwell(self):
        dwell = rail._run('dwell', (('A',600), ('B',605), ('C',620)))
        dwell['odpt:trainTimetableObject'][1]['odpt:departureTime'] = '10:15'
        self.fixture(dwell, rail._run('slow', (('A',600), ('B',610))),
                     rail._run('holiday_fast', (('A',601), ('B',604)), calendar='Holiday'))
        minima, trips, stops, intervals = audit._collect_static_rail_minima(self.snapshot, lambda:None)
        self.assertEqual(minima, {(rail._station('A'),rail._station('B')):math.nextafter(3.0,-math.inf),
                                  (rail._station('B'),rail._station('C')):math.nextafter(5.0,-math.inf)})
        self.assertEqual((trips,stops,intervals),(3,7,4))
        report = self.verify()
        self.assertTrue(report['common_rail_interval_minima_verified'])
        self.assertEqual(report['rail_reference_records'],4)
        self.assertEqual(report['rail_source_calendars'],2)
        # The fixture's source calendars are all inactive outside year 2000;
        # there is deliberately no query-date filter in this static audit.
        self.assertTrue(all(not dataset.active_service_ids(self.source.day.service_date)
                            for dataset in self.snapshot.datasets))

    def test_four_source_calendars_are_included_once_without_weekend_double_count(self):
        self.fixture(*(rail._run(name,(('A',600),('B',600+duration)),calendar=name)
            for name,duration in (('Weekday',5),('Saturday',4),('Holiday',3),('SaturdayHoliday',2))))
        report = self.verify()
        self.assertEqual(report['rail_source_calendars'],4)
        self.assertEqual(report['rail_source_trips'],4)
        self.assertEqual(report['rail_source_intervals'],4)
        self.assertEqual(report['rail_reference_records'],4)
        self.assertEqual(report['rail_interval_pairs'],1)

    def test_midnight_revisits_and_pickup1_gap_occurrences_remain_adjacent(self):
        run = rail._run('loop', (('A',1439), ('B',1), ('A',3), ('C',4)))
        run['odpt:trainTimetableObject'][1]['odpt:departureTime'] = '00:02'
        self.fixture(run)
        expected = {(rail._station('A'),rail._station('B')):math.nextafter(2.,-math.inf),
                    (rail._station('B'),rail._station('A')):math.nextafter(1.,-math.inf),
                    (rail._station('A'),rail._station('C')):math.nextafter(1.,-math.inf)}
        self.assertEqual(audit._collect_static_rail_minima(self.snapshot,lambda:None)[0],expected)
        self.assertTrue(self.verify()['common_rail_interval_minima_verified'])
        key = next(iter(self.snapshot.trips))
        rows = tuple(replace(row, source=replace(row.source, sequence=seq,
                     pickup_type=1 if position==1 else 0))
                     for position,(row,seq) in enumerate(zip(self.snapshot.rows_by_trip[key],(1,7,11,15))))
        changed = replace(self.snapshot, rows_by_trip={key:rows})
        # The collector is independent of boarding eligibility. The existing
        # provider binding still rejects unsupported source gaps/boarding flags.
        self.assertEqual(audit._collect_static_rail_minima(changed,lambda:None)[0],expected)
        with self.assertRaises(RouteContractError):
            TokyoRailDatasetBinding(changed,self.manager)

    def test_zero_duration_is_exact_zero_and_incomplete_source_scope_is_rejected(self):
        self.fixture(rail._run('zero', (('A',600), ('B',600))))
        minima,_,_,_ = audit._collect_static_rail_minima(self.snapshot,lambda:None)
        self.assertEqual(list(minima.values()),[0.0])
        self.assertEqual(self.verify()['rail_invalid_intervals'],0)
        self.binding.snapshot = replace(self.snapshot,allowed_trip_ids=frozenset())
        with self.assertRaisesRegex(RouteContractError,'complete rail-only source scope'):
            self.verify()

    def test_invalid_and_fractional_source_clocks_are_not_rounded_or_zeroed(self):
        self.fixture(rail._run('run', (('A',600), ('B',605))))
        key = next(iter(self.snapshot.trips))
        rows = self.snapshot.rows_by_trip[key]
        for clock in (Fraction(1201,2), Fraction(-1), Fraction(2**53+1), None, 600.0):
            changed = replace(self.snapshot,rows_by_trip={key:(replace(rows[0],departure_minute=clock),rows[1])})
            with self.subTest(clock=clock),self.assertRaisesRegex(RouteContractError,'exact integral'):
                audit._collect_static_rail_minima(changed,lambda:None)
        changed = replace(self.snapshot,rows_by_trip={key:(replace(rows[0],departure_minute=Fraction(606)),rows[1])})
        with self.assertRaisesRegex(RouteContractError,'invalid adjacent interval'):
            audit._collect_static_rail_minima(changed,lambda:None)

    def test_same_length_source_edit_stops_even_when_minimum_would_stay_equal(self):
        self.fixture(rail._run('fast', (('A',600), ('B',601))),
                     rail._run('slow', (('A',600), ('B',610))))
        rows = self.manager.train_patterns_weekday[rail._station('A')]
        next(row for row in rows if row['train_num']=='slow')['arr'] += 1
        with patch.object(audit,'_build_rail_index',side_effect=AssertionError('changed source was consumed')):
            with self.assertRaisesRegex(RouteContractError,'changed since binding'):
                self.verify()

    def test_duplicate_legacy_record_is_not_hidden_by_an_equal_minimum(self):
        self.fixture(rail._run('run', (('A',600), ('B',605))))
        rows = self.manager.train_patterns_weekday[rail._station('A')]
        rows.append(dict(rows[0]))
        self.binding = TokyoRailDatasetBinding(self.snapshot,self.manager)
        with self.assertRaisesRegex(RouteContractError,'coverage differs.*reference_records=2'):
            self.verify()

    def test_reference_invalid_count_key_or_value_mismatch_stops_without_private_ids(self):
        self.fixture(rail._run('PRIVATE_RUN', (('PRIVATE_A',600), ('PRIVATE_B',605))))
        minima,_,_,intervals = audit._collect_static_rail_minima(self.snapshot,lambda:None)
        pair = next(iter(minima))
        cases = ((dict(minima),1), ({},0), ({pair:6.0},0), ({**minima,('PRIVATE_X','PRIVATE_Y'):1.0},0))
        for values,invalid in cases:
            reference = SimpleNamespace(minima=values,invalid=invalid,records=intervals)
            with self.subTest(invalid=invalid,keys=len(values)),patch.object(audit,'_build_rail_index',return_value=reference) as builder:
                with self.assertRaises(RouteContractError) as raised:
                    self.verify()
                builder.assert_called_once()
                self.assertNotIn('PRIVATE_',str(raised.exception))

    def test_audit_does_not_search_project_inspect_bus_or_publish_a_cache(self):
        self.fixture(rail._run('run', (('A',600), ('B',605))))
        sentinel = object()
        self.manager._tokyo_time_rail_interval_index = sentinel
        generation = self.manager._tokyo_time_bounds_generation
        with (patch('toei_engine._tokyo_label_search',side_effect=AssertionError('OD search')),
              patch('tokyo_time_bounds._build_bus_index',side_effect=AssertionError('bus audit')),
              patch('tokyo_time_bounds._publish',side_effect=AssertionError('index publish')),
              patch('tokyo_time_bounds.make_time_bounds',side_effect=AssertionError('destination projection')),
              patch.object(shared.TimetableChoices,'board_options',side_effect=AssertionError('board query')),
              patch.object(shared.TimetableChoices,'ride_options',side_effect=AssertionError('ride query'))):
            self.assertTrue(self.verify()['common_rail_interval_minima_verified'])
        self.assertIs(self.manager._tokyo_time_rail_interval_index,sentinel)
        self.assertEqual(self.manager._tokyo_time_bounds_generation,generation)

    def test_deadline_reference_error_and_inflight_source_change_are_never_retried(self):
        self.fixture(rail._run('run', (('A',600), ('B',605))))
        error = RuntimeError('original audit deadline')
        with patch.object(audit,'_build_rail_index') as builder:
            with self.assertRaises(RuntimeError) as raised:
                self.verify(check_deadline=lambda:(_ for _ in ()).throw(error))
            self.assertIs(raised.exception,error)
            builder.assert_not_called()
        with patch.object(audit,'_build_rail_index',side_effect=error) as builder:
            with self.assertRaises(RuntimeError) as raised:
                self.verify()
            self.assertIs(raised.exception,error)
            builder.assert_called_once()
        calls = 0
        def edit_after_initial_digest():
            nonlocal calls
            calls += 1
            if calls == 3:
                self.manager.train_patterns_weekday[rail._station('A')][0]['arr'] += 1
        with self.assertRaisesRegex(RouteContractError,'changed during interval audit'):
            self.verify(check_deadline=edit_after_initial_digest)

    def test_readonly_cli_has_a_distinct_marker_no_gtfs_dates_or_rank_claim(self):
        self.fixture(rail._run('run', (('A',600), ('B',605))))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            before = {p.name:p.read_bytes() for p in root.iterdir()}
            with (patch.object(sys,'argv',self.arguments(paths)),
                  patch.object(probe,'check_repository') as check,
                  patch('gtfs_loader.GtfsRepository.load_data',side_effect=AssertionError('GTFS read')),
                  patch('check_tokyo_rail_routes_local.select_cases',side_effect=AssertionError('rail OD selection')),
                  patch('check_tokyo_rail_routes_local.compare_choices',side_effect=AssertionError('rail graph rerun')),
                  patch('toei_engine._tokyo_label_search',side_effect=AssertionError('OD query')),
                  contextlib.redirect_stdout(io.StringIO()) as output):
                probe.main()
            self.assertEqual(check.call_count,2)
            lines = output.getvalue().splitlines()
            self.assertEqual(lines[-1],'READ_ONLY_TOKYO_COMMON_RAIL_INTERVAL_MINIMA_OK')
            report = json.loads(lines[-2])
            self.assertEqual(report['audit_mode'],'tokyo_common_rail_static_interval_minima')
            self.assertEqual(report['calendar_scope'],'all_source_calendars_no_date_filter')
            self.assertEqual(report['common_rail_time_bounds_provider'],'not_selected_audit_only')
            self.assertEqual(len(report['input_hashes']),4)
            self.assertTrue(report['common_rail_interval_minima_verified'])
            self.assertFalse(report['common_rail_sample_rank_verified'])
            self.assertFalse(report['common_rail_graph_projection_verified'])
            self.assertFalse(report['common_rail_destination_bounds_verified'])
            self.assertFalse(report['common_rail_priority_rounding_verified'])
            self.assertFalse(report['common_dataset_route_ranking_verified'])
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})

    def test_cli_input_change_and_original_exception_prevent_success_marker(self):
        self.fixture(rail._run('run', (('A',600), ('B',605))))
        with tempfile.TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            def edit(*args):
                paths[0].write_text('[]',encoding='utf-8')
                return {}
            error = RuntimeError('original source failure')
            for failure in (edit,error):
                with (patch.object(sys,'argv',self.arguments(paths)),patch.object(probe,'check_repository'),
                      patch.object(probe,'inspect',side_effect=failure) as inspect,
                      contextlib.redirect_stdout(io.StringIO()) as output):
                    with self.assertRaises(RuntimeError if failure is error else AssertionError) as raised:
                        probe.main()
                    inspect.assert_called_once()
                    if failure is error:
                        self.assertIs(raised.exception,error)
                    self.assertNotIn('READ_ONLY_TOKYO_COMMON_RAIL_INTERVAL_MINIMA_OK',output.getvalue())

    def test_cli_rejects_realtime_and_query_filters_before_reading_inputs(self):
        self.fixture(rail._run('run', (('A',600), ('B',605))))
        with tempfile.TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            for extra in (['--use-realtime'],['--query-date','2026-09-04'],['--gtfs-dir',directory]):
                with (patch.object(sys,'argv',self.arguments(paths)+extra),
                      patch.object(probe,'check_repository') as check,
                      contextlib.redirect_stderr(io.StringIO())):
                    with self.assertRaises(SystemExit) as raised:
                        probe.main()
                    self.assertEqual(raised.exception.code,2)
                    check.assert_not_called()


if __name__ == '__main__':
    unittest.main()

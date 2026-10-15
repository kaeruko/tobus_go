"""Pinned common bus choices preserve Tokyo graph/run/ranking contracts."""
from dataclasses import replace
from datetime import date
import unittest
from unittest.mock import patch

from route_engine import RouteContractError
from tokyo_dataset_bus_choices import TokyoBusDatasetBinding
from tokyo_timetable_choices import TimetableChoices
from transit_network import NetworkCosts, build_transit_network
from tests import test_tokyo_bus_choices_contract as bus
from tests import test_tokyo_compiled_routes_local_check as routes


class TokyoDatasetBusChoicesTest(unittest.TestCase):
    def setUp(self):
        fixture = routes.TokyoCompiledRoutesLocalCheckTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.prebuilt = fixture.full_fixture()
        self.root,self.graph,self.manager = fixture.root,fixture.graph,fixture.manager
        _,self.dataset,self.snapshot,_,_ = routes.probe.load_inputs(self.root,'fixture',('2026-09-04',))
        self.repository = routes.probe.GtfsRepository('tokyo_bus_probe').load_data(str(self.root))
        self.binding = TokyoBusDatasetBinding(self.snapshot,self.repository)
        self.day = bus.engine.ServiceDayType('weekday',date(2026,9,4),self.repository.get_active_service_ids(date(2026,9,4)),True)

    def reload_source(self):
        _,self.dataset,self.snapshot,_,_ = routes.probe.load_inputs(self.root,'fixture',('2026-09-04',))
        self.repository = routes.probe.GtfsRepository('tokyo_bus_probe').load_data(str(self.root))
        self.binding = TokyoBusDatasetBinding(self.snapshot,self.repository)

    def choices(self, **overrides):
        kwargs = dict(day_type=self.day,use_realtime=False,deadline=838,bus_repository=self.repository)
        kwargs.update(overrides)
        return self.binding.choices(self.graph,self.manager,**kwargs)

    def test_static_bus_minima_are_equal_without_changing_search_provider(self):
        result = self.binding.verify_static_bus_interval_minima(lambda: None)
        self.assertTrue(result['common_bus_interval_minima_verified'])
        self.assertGreater(result['bus_interval_pairs'], 0)
        self.assertEqual(result['bus_source_trips'], len(self.repository.trips))
        self.assertEqual(self.choices().time_bounds_choices.__class__, TimetableChoices)

    def test_static_bus_minima_mismatch_stops_without_provider_fallback(self):
        # Mutation happens AFTER the binding validates the pinned source.
        stop, arrival, departure = self.repository.stop_times['t'][2]
        self.repository.stop_times['t'][2] = (stop, arrival + 1, departure + 1)
        with self.assertRaisesRegex(RouteContractError, 'interval minimum differs'):
            self.binding.verify_static_bus_interval_minima(lambda: None)

    def test_static_bus_minima_bounds_only_cli_does_not_rerun_od_routes(self):
        import contextlib
        import io
        import json
        import sys
        args = [str(routes.SCRIPT), '--gtfs-dir', str(self.root),
                '--expected-feed-version', 'fixture', '--query-date', '2026-09-04',
                '--trusted-prebuilt', str(self.prebuilt), '--expected-sha', 'a'*40,
                '--shared-bus-bounds-only']
        with (patch.object(sys, 'argv', args),
              patch.object(routes.probe, 'check_repository'),
              patch.object(routes.probe, 'route_sample', side_effect=AssertionError('unexpected OD query')),
              contextlib.redirect_stdout(io.StringIO()) as output):
            routes.probe.main()
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[-1], 'READ_ONLY_TOKYO_COMMON_BUS_INTERVAL_MINIMA_OK')
        report = json.loads(lines[-2])
        self.assertTrue(report['common_bus_interval_minima_verified'])
        self.assertFalse(report['common_bus_sample_rank_verified'])
        self.assertEqual(report['common_bus_time_bounds_provider'], 'not_selected_audit_only')

    def test_board_ride_and_metadata_use_common_provider_without_legacy_bus_queries(self):
        legacy = TimetableChoices(self.graph,self.manager,day_type=self.day,use_realtime=False,
                                  deadline=838,bus_repository=self.repository)
        expected = legacy.board_options(bus._phys('A'),bus._line('A'),598)
        choices = self.choices()
        choices.prepare(lambda:None)
        with (patch.object(TimetableChoices,'_bus_options',side_effect=AssertionError('legacy bus query')),
              patch.object(TimetableChoices,'_bus_run',side_effect=AssertionError('legacy source run'))):
            actual = choices.board_options(bus._phys('A'),bus._line('A'),598)
            self.assertEqual(actual,expected)
            dep,state = actual[0]
            arrival,at_b = choices.ride_options(bus._line('A'),bus._line('B'),dep,state)[0]
            arrival,at_c = choices.ride_options(bus._line('B'),bus._line('C'),arrival,at_b)[0]
            self.assertEqual(arrival,620)
            self.assertEqual(choices.metadata(at_c)['stops'],('A','B','C'))
            self.assertEqual([s.trip_id for _,s in choices.board_options(bus._phys('B'),bus._line('B'),608)],['later'])

    def test_same_graph_all_three_modes_match_including_candidate_order(self):
        report = routes.probe.inspect(self.root,'fixture',('2026-09-04',),self.prebuilt,3,shared_bus=True)
        self.assertEqual(len(report['date_cases']),9)
        self.assertTrue(report['common_bus_sample_rank_verified'])
        self.assertFalse(report['common_dataset_route_ranking_verified'])
        self.assertEqual(report['rail_provider'],'existing_tokyo')

    def test_equal_departures_keep_tokyo_sequence_before_trip_id_order(self):
        path = self.root/'stop_times.txt'
        path.write_text(path.read_text().replace('later,10:15:00,10:15:00,B,1,0,0',
            'later,10:00:00,10:00:00,A,2,0,0').replace('later,10:25:00,10:25:00,C,2,0,0',
            'later,10:30:00,10:30:00,C,3,0,0'),encoding='utf-8')
        self.graph.add_edge(bus._line('A'),bus._line('C'),etype='ride',mode='bus',w=1)
        self.reload_source()
        choices = self.choices()
        choices.prepare(lambda:None)
        options = choices.board_options(bus._phys('A'),bus._line('A'),600)
        self.assertEqual([(dep,state.sequence,state.trip_id) for dep,state in options],[(600,1,'t'),(600,2,'later')])

    def test_loop_repeated_stop_and_sequence_gaps_keep_the_same_run(self):
        path = self.root/'stop_times.txt'
        path.write_text('trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\n'
            't,10:00:00,10:00:00,A,1,0,0\nt,10:10:00,10:10:00,B,4,1,0\n'
            't,10:20:00,10:20:00,A,8,0,0\nt,10:30:00,10:30:00,C,9,0,0\n'
            'later,10:15:00,10:15:00,B,1,0,0\nlater,10:25:00,10:25:00,C,2,0,0\n'
            'direct,10:30:00,10:30:00,A,1,0,0\ndirect,10:40:00,10:40:00,C,2,0,0\n',encoding='utf-8')
        self.graph.add_edge(bus._line('B'),bus._line('A'),etype='ride',mode='bus',w=1)
        self.graph.add_edge(bus._line('A'),bus._line('C'),etype='ride',mode='bus',w=1)
        self.reload_source()
        choices = self.choices()
        choices.prepare(lambda:None)
        options = choices.board_options(bus._phys('A'),bus._line('A'),598)
        self.assertEqual([(dep,state.sequence) for dep,state in options],[(600,1),(620,8)])
        clock,state = options[0]
        for left,right,sequence in (('A','B',4),('B','A',8),('A','C',9)):
            clock,state = choices.ride_options(bus._line(left),bus._line(right),clock,state)[0]
            self.assertEqual(state.sequence,sequence)
        self.assertEqual(choices.metadata(state)['stops'],('A','B','A','C'))

    def test_static_bus_minima_include_pickup1_continuation_and_revisits(self):
        path = self.root/'stop_times.txt'
        path.write_text('trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\n'
            't,10:00:00,10:00:00,A,1,0,0\n'
            't,10:10:00,10:10:00,B,4,1,0\n'
            't,10:20:00,10:20:00,A,8,0,0\n'
            't,10:30:00,10:30:00,C,9,0,0\n'
            'later,10:15:00,10:15:00,B,1,0,0\n'
            'later,10:16:00,10:16:00,C,2,0,0\n'
            'direct,10:30:00,10:30:00,A,1,0,0\n'
            'direct,10:40:00,10:40:00,C,2,0,0\n', encoding='utf-8')
        self.reload_source()
        result = self.binding.verify_static_bus_interval_minima(lambda: None)
        self.assertTrue(result['common_bus_interval_minima_verified'])
        self.assertEqual(result['bus_source_stop_times'], 8)
        # All three distinct same-run transitions survive the pickup=1 position.
        self.assertGreaterEqual(result['bus_interval_pairs'], 3)
        self.assertEqual(self.repository.get_stop_time_boarding('t', 4), (1, 0))

    def test_static_bus_minima_deadline_error_is_not_retried(self):
        original = RuntimeError('deadline check failure')
        def fail():
            raise original
        with self.assertRaises(RuntimeError) as raised:
            self.binding.verify_static_bus_interval_minima(fail)
        self.assertIs(raised.exception, original)

    def test_deadline_and_wrong_next_stop_do_not_extend_selected_bus(self):
        self.graph.add_edge(bus._line('A'),bus._line('C'),etype='ride',mode='bus',w=1)
        choices = self.choices(deadline=615)
        choices.prepare(lambda:None)
        dep,state = choices.board_options(bus._phys('A'),bus._line('A'),598)[0]
        self.assertEqual(choices.ride_options(bus._line('A'),bus._line('C'),dep,state),())
        arrival,state = choices.ride_options(bus._line('A'),bus._line('B'),dep,state)[0]
        self.assertEqual(choices.ride_options(bus._line('B'),bus._line('C'),arrival,state),())

    def test_time_bound_source_is_explicit_reference_not_disabled_custom_bound(self):
        import tokyo_search_labels
        with patch.object(tokyo_search_labels,'make_time_bounds',wraps=tokyo_search_labels.make_time_bounds) as bounds:
            routes.probe.route_sample(self.graph,self.manager,self.repository,date(2026,9,4),
                ('through',bus._phys('A'),bus._phys('C'),598),'time',3,choices_factory=self.binding.choices)
        self.assertIs(type(bounds.call_args.args[1]),TimetableChoices)

    def test_cli_requires_explicit_common_bus_flag_and_has_distinct_marker(self):
        import contextlib
        import io
        import json
        import sys
        args = [str(routes.SCRIPT),'--gtfs-dir',str(self.root),'--expected-feed-version','fixture',
                '--query-date','2026-09-04','--trusted-prebuilt',str(self.prebuilt),
                '--expected-sha','a'*40,'--shared-bus']
        with patch.object(sys,'argv',args),patch.object(routes.probe,'check_repository'),contextlib.redirect_stdout(io.StringIO()) as output:
            routes.probe.main()
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[-1],'READ_ONLY_TOKYO_COMMON_BUS_ROUTE_SAMPLE_OK')
        self.assertTrue(json.loads(lines[-2])['common_bus_sample_rank_verified'])

    def test_clock_precision_metadata_and_scope_are_not_repaired(self):
        raw = self.repository
        raw.stop_time_boarding['t'].pop(2)
        with self.assertRaisesRegex(ValueError,'metadata missing'):
            TokyoBusDatasetBinding(self.snapshot,raw)
        raw.stop_time_boarding['t'][2] = (0,0)
        with self.assertRaisesRegex(RouteContractError,'source flags differ'):
            TokyoBusDatasetBinding(self.snapshot,raw)
        raw.stop_time_boarding['t'][2] = (1,0)
        subset = build_transit_network((self.dataset,),allowed_trip_ids=(self.dataset.metadata.feed_id+':t',),walking_links=(),costs=NetworkCosts())
        with self.assertRaisesRegex(RouteContractError,'complete source trip scope'):
            TokyoBusDatasetBinding(subset,raw)
        changed = tuple(replace(row,arrival_service_seconds=36001,departure_service_seconds=36001)
                        if row.trip_id.endswith(':t') and row.sequence == 1 else row for row in self.dataset.stop_times)
        dataset = replace(self.dataset,stop_times=changed)
        snapshot = build_transit_network((dataset,),allowed_trip_ids=dataset.trips,walking_links=(),costs=NetworkCosts())
        with self.assertRaisesRegex(RouteContractError,'no rounding'):
            TokyoBusDatasetBinding(snapshot,raw)

    def test_preparation_realtime_calendar_and_opaque_provider_fail_fast(self):
        choices = self.choices()
        with self.assertRaisesRegex(RouteContractError,'explicit deadline-scoped preparation'):
            choices.board_options(bus._phys('A'),bus._line('A'),598)
        with self.assertRaisesRegex(RouteContractError,'realtime unsupported'):
            self.choices(use_realtime=True)
        with self.assertRaisesRegex(RouteContractError,'explicit date'):
            self.choices(day_type='weekday')
        with self.assertRaisesRegex(RouteContractError,'real calendar'):
            self.choices(day_type=bus.engine.ServiceDayType('weekday',date(2026,9,4),frozenset(),False))
        with self.assertRaisesRegex(RouteContractError,'active trip scope differs'):
            self.choices(day_type=bus.engine.ServiceDayType('weekday',date(2026,9,4),frozenset(),True)).prepare(lambda:None)
        with self.assertRaisesRegex(RouteContractError,'opaque'):
            choices._fallback_options()

    def test_common_provider_exception_is_not_retried_through_legacy(self):
        choices = self.choices()
        choices.prepare(lambda:None)
        error = RuntimeError('original common provider error')
        with (patch.object(choices.scheduled,'board_options',side_effect=error) as common,
              patch.object(TimetableChoices,'_bus_options') as legacy):
            with self.assertRaises(RuntimeError) as raised:
                choices.board_options(bus._phys('A'),bus._line('A'),598)
            self.assertIs(raised.exception,error)
            self.assertEqual(common.call_count,1)
            legacy.assert_not_called()


if __name__ == '__main__':
    unittest.main()

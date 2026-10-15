"""Static common rail keeps Tokyo runs, occurrences, clocks and ranked graph paths."""
import contextlib
from dataclasses import replace
from datetime import date, datetime, timezone
from fractions import Fraction
import importlib.util
import io
import json
import math
from pathlib import Path
import pickle
import sys
import tempfile
import unittest
from unittest.mock import patch

import networkx as nx
from route_engine import RouteContractError
from tokyo_dataset_rail_choices import TokyoRailDatasetBinding
from tokyo_timetable_choices import TimetableChoices
from transit_adapters.odpt import OdptCalendarRule, OdptTransitAdapter
from transit_dataset import FeedMetadata
from transit_network import NetworkCosts, build_transit_network
from transit_timetable_choices import DatasetTimetableChoices
from tests import test_tokyo_waiting_contract as rail
from tests import test_tokyo_bus_choices_contract as bus

SCRIPT = Path(__file__).resolve().parents[2]/'scripts/check_tokyo_rail_routes_local.py'
spec = importlib.util.spec_from_file_location('rail_routes_probe',SCRIPT)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def source_fixture(runs):
    names = sorted({obj['odpt:departureStation'] for run in runs for obj in run['odpt:trainTimetableObject']})
    stations = [{'owl:sameAs':name,'dc:title':name,'geo:lat':35.,'geo:long':139.}
                for name in names]
    railways = [{'owl:sameAs':rail.RAILWAY,'dc:title':'Asakusa'}]
    day = date(2000,1,1)
    rules = {run['odpt:calendar']:OdptCalendarRule((False,)*7,day,day) for run in runs}
    dataset = OdptTransitAdapter.build(metadata=FeedMetadata('rail','fixture','fixture:rail',
        '1',datetime(2026,1,1,tzinfo=timezone.utc)),stations=stations,railways=railways,
        train_timetables=runs,calendar_rules=rules,train_clock_convention='ordered_run')
    return build_transit_network((dataset,),allowed_trip_ids=dataset.trips,
        walking_links=(),costs=NetworkCosts()),stations,railways


class TokyoDatasetRailChoicesTest(unittest.TestCase):
    def fixture(self, *runs):
        self.runs = runs
        self.snapshot,self.stations,self.railways = source_fixture(runs)
        self.manager = rail._manager(*runs)
        self.graph = rail._graph(*[(a['odpt:departureStation'].rsplit('.',1)[1],
            b['odpt:departureStation'].rsplit('.',1)[1]) for run in runs
            for a,b in zip(run['odpt:trainTimetableObject'],run['odpt:trainTimetableObject'][1:])])
        self.repository = bus._repository()
        self.day = bus.engine.ServiceDayType('weekday',date(2026,9,4),frozenset(('active',)),True)
        self.binding = TokyoRailDatasetBinding(self.snapshot,self.manager)

    def choices(self, **kw):
        args = dict(day_type=self.day,use_realtime=False,deadline=3000,bus_repository=self.repository)
        args.update(kw)
        selected = self.binding.choices(self.graph,self.manager,**args)
        selected.prepare(lambda:None)
        return selected

    def test_common_provider_is_used_without_old_rail_evaluation_and_metadata_matches(self):
        self.fixture(rail._run('loop',(('A',600),('B',605),('A',610),('C',615))))
        expected = TimetableChoices(self.graph,self.manager,self.day,use_realtime=False,deadline=3000,bus_repository=self.repository)
        baseline = expected.board_options(rail._physical('A'),rail._line('A'),0)
        chosen = self.choices()
        original = DatasetTimetableChoices.board_options
        calls = []
        def common(*args):
            calls.append(True)
            return original(*args)
        with (patch.object(TimetableChoices,'_rail_options',side_effect=AssertionError('old rail board')),
              patch.object(TimetableChoices,'_build_rail',side_effect=AssertionError('old rail build')),
              patch.object(TimetableChoices,'ride_options',side_effect=AssertionError('old rail ride')),
              patch.object(DatasetTimetableChoices,'board_options',autospec=True,side_effect=common)):
            actual = chosen.board_options(rail._physical('A'),rail._line('A'),0)
            self.assertEqual(actual,baseline)
            for _,state in actual:
                self.assertEqual(chosen.metadata(state),expected.metadata(state))
                run = chosen._runs['rail',state.run_id]
                following = ('line',run.stops[state.sequence+1].stop_id,state.line_id)
                result = chosen.ride_options(rail._line('A'),following,state.departure_minute,state)
                self.assertTrue(result)
                self.assertEqual(chosen.metadata(result[0][1]),expected.metadata(result[0][1]))
        self.assertTrue(calls)
        report = probe.compare_choices(self.graph,self.manager,self.repository,self.day,self.binding,3000)
        self.assertEqual(report['differences'],0)
        self.assertGreater(report['continuations'],3)

    def test_same_number_distinct_runs_tie_order_and_boundary_readiness(self):
        self.fixture(rail._run('z',(('A',600),('B',605)),number='N'),
                     rail._run('a',(('A',600),('B',605)),number='N'),
                     rail._run('other',(('B',607),('C',608)),number='N'))
        expected = TimetableChoices(self.graph,self.manager,self.day,use_realtime=False,deadline=3000,bus_repository=self.repository)
        chosen = self.choices()
        for ready in (math.nextafter(600,-math.inf),600,math.nextafter(600,math.inf)):
            self.assertEqual(chosen.board_options(rail._physical('A'),rail._line('A'),ready),
                             expected.board_options(rail._physical('A'),rail._line('A'),ready))
        options = chosen.board_options(rail._physical('A'),rail._line('A'),600)
        self.assertEqual(len({state.run_id for _,state in options}),2)
        arr,state = chosen.ride_options(rail._line('A'),rail._line('B'),600,options[0][1])[0]
        self.assertEqual(chosen.ride_options(rail._line('B'),rail._line('C'),arr,state),())

    def test_midnight_multiple_days_dwell_and_terminal_match(self):
        run = rail._run('night',(('A',1439),('B',1),('A',3),('C',2)))
        run['odpt:trainTimetableObject'][1]['odpt:departureTime']='00:02'
        self.fixture(run)
        result = probe.compare_choices(self.graph,self.manager,self.repository,self.day,self.binding,5000)
        self.assertEqual(result['differences'],0)
        new = self.choices(deadline=5000)
        dep,state = new.board_options(rail._physical('A'),rail._line('A'),1439)[0]
        arr,next_state = new.ride_options(rail._line('A'),rail._line('B'),dep,state)[0]
        self.assertEqual(arr,1441)
        self.assertEqual(new._runs['rail',state.run_id].stops[-1].arrival,2882)
        self.assertEqual(new.metadata(next_state)['scheduled_arrival_minute'],1441)
        self.assertEqual(new.ride_options(rail._line('A'),rail._line('B'),1440,state),())
        short = self.choices(deadline=1440)
        _, short_state = short.board_options(rail._physical('A'),rail._line('A'),1439)[0]
        self.assertEqual(short.ride_options(rail._line('A'),rail._line('B'),1439,short_state),())

    def test_all_four_calendars_and_explicit_dates_keep_active_scope(self):
        self.fixture(*(rail._run(cal,(('A',600),('B',605)),calendar=cal)
                       for cal in ('Weekday','Saturday','Holiday','SaturdayHoliday')))
        for value in ('2026-09-04','2026-09-05','2026-09-06','2026-09-21'):
            day = bus.engine.determine_day_type(date.fromisoformat(value))
            result = probe.compare_choices(self.graph,self.manager,self.repository,day,self.binding,3000)
            self.assertGreater(result['boarding_options'],0)
        self.assertEqual(str(bus.engine.determine_day_type(date(2026,9,21))),'holiday')

    def test_split_legacy_run_and_changed_source_fail_before_use(self):
        self.fixture(rail._run('run',(('A',600),('B',605),('C',610))))
        self.manager.train_patterns_weekday[rail._station('B')][0]['stop_sequence']=2
        with self.assertRaisesRegex(RouteContractError,'clock/sequence|split|part'):
            TokyoRailDatasetBinding(self.snapshot,self.manager)
        with self.assertRaisesRegex(RouteContractError,'changed since'):
            self.choices()

    def test_invalid_scope_flags_number_clock_and_sequence_are_rejected(self):
        self.fixture(rail._run('run',(('A',600),('B',605))))
        key = next(iter(self.snapshot.trips))
        row = self.snapshot.rows_by_trip[key][0]
        for changed in (replace(row,departure_minute=Fraction(36001,60)),
                        replace(row,source=replace(row.source,pickup_type=1)),
                        replace(row,source=replace(row.source,sequence=2))):
            snapshot = replace(self.snapshot, rows_by_trip={key:(changed,self.snapshot.rows_by_trip[key][1])})
            with self.assertRaises(RouteContractError):
                TokyoRailDatasetBinding(snapshot,self.manager)
        trip = self.snapshot.trips[key]
        with self.assertRaisesRegex(RouteContractError,'clock/sequence/stop/number|source route/calendar/number'):
            TokyoRailDatasetBinding(replace(self.snapshot,trips={key:replace(trip,train_number='other')}),self.manager)
        with self.assertRaisesRegex(RouteContractError,'complete source scope'):
            TokyoRailDatasetBinding(replace(self.snapshot,allowed_trip_ids=frozenset()),self.manager)

    def test_realtime_opaque_date_deadline_and_original_prepare_errors_stop(self):
        self.fixture(rail._run('run',(('A',600),('B',605))))
        for kwargs in ({'use_realtime':True},{'day_type':'weekday'},{'deadline':math.inf},{'day_type':bus.engine.ServiceDayType('holiday',date(2026,9,4),frozenset(),True)}):
            with self.assertRaises(RouteContractError):
                self.choices(**kwargs)
        chosen = self.choices()
        with self.assertRaisesRegex(RouteContractError,'opaque'):
            chosen._fallback_options(None)
        failure = RuntimeError('original prepare failure')
        with patch.object(DatasetTimetableChoices,'prepare',side_effect=failure):
            with self.assertRaises(RuntimeError) as raised:
                self.choices()
            self.assertIs(raised.exception,failure)
        self.assertIs(type(chosen.time_bounds_choices),TimetableChoices)

    def multimodal(self):
        self.fixture(rail._run('first',(('A',600),('B',605))),
                     rail._run('last',(('D',609),('E',612))))
        self.graph = nx.compose(self.graph,bus._graph(('Q','Z')))
        self.repository = bus._repository(('bus','active',(('Q',608,608),('Z',615,615))))
        self.repository.service_calendar['active']={'start_date':'20260101','end_date':'20261231','weekdays':(True,)*7}
        rail._walk(self.graph,rail._physical('B'),bus._phys('Q'),80)
        rail._walk(self.graph,rail._physical('B'),rail._physical('D'),80)

    def test_three_modes_rail_bus_walk_keep_ranked_paths_metadata_and_reference_bounds(self):
        self.multimodal()
        plan = probe.select_cases(self.graph,self.manager,self.repository,self.day,3000)
        self.assertEqual(set(plan.cases),{(kind,mode) for kind in probe.KINDS for mode in probe.MODES})
        for (kind,mode),case in plan.cases.items():
            with self.subTest(case=kind,mode=mode):
                old = probe.route_sample(self.graph,self.manager,self.repository,self.day,case,mode,3)
                new = probe.route_sample(self.graph,self.manager,self.repository,self.day,case,mode,3,self.binding.choices)
                self.assertEqual(old,new)

    def preselection_fixture(self):
        self.fixture(rail._run('first',(('A',600),('B',605))),
                     rail._run('last',(('D',609),('E',612))),
                     rail._run('shortcut',(('A',600),('Z',604))))
        self.graph = nx.compose(self.graph,bus._graph(('Q',rail._station('Z'))))
        self.graph = nx.compose(self.graph,bus._graph(('U','V'),line='other'))
        self.repository = bus._repository(
            ('bad_bus','active',(('Q',608,608),(rail._station('Z'),615,615))),
            ('good_bus','active',(('U',608,608),('V',615,615))))
        self.repository.service_calendar['active']={'start_date':'20260101','end_date':'20261231','weekdays':(True,)*7}
        for stop in ('Q','U'):
            rail._walk(self.graph,rail._physical('B'),bus._phys(stop),80)
        rail._walk(self.graph,rail._physical('B'),rail._physical('D'),80)

    def test_structural_rail_bus_absent_from_top_three_is_rejected_before_freezing(self):
        self.preselection_fixture()
        candidates = list(probe.structural_cases(self.graph,self.manager,self.repository,self.day,3000))
        bad = next(case for case in candidates if case[0]=='rail_bus' and case[2]==rail._physical('Z'))
        rows = probe.search_sample(self.graph,self.manager,self.repository,self.day,bad,'time',3)
        self.assertTrue(rows)
        self.assertFalse(any(row['relevant'] for row in rows))
        with self.assertRaisesRegex(RouteContractError,'lacks required category'):
            probe.route_sample(self.graph,self.manager,self.repository,self.day,bad,'time',3)
        with (patch.object(self.binding,'choices',side_effect=AssertionError('common during preselection')),
              patch.object(probe,'search_sample',wraps=probe.search_sample) as search):
            plan = probe.select_cases(self.graph,self.manager,self.repository,self.day,3000,3)
            self.assertGreaterEqual(plan.nonmatching_queries,1)
            self.assertNotEqual(bad,plan.cases['rail_bus','time'])
            self.assertTrue(all(call.args[6]==3 and len(call.args)==7 for call in search.call_args_list))
        with self.assertRaises(TypeError):
            plan.cases['rail_bus','time'] = bad
        chosen = plan.cases['rail_bus','time']
        self.assertEqual(chosen[2],bus._phys('V'))
        for key in plan.cases:
            self.assertTrue(any(row['relevant'] for row in plan.baseline[key]))
        report = probe.compare_plan(self.graph,self.manager,self.repository,self.day,self.binding,plan,3)
        self.assertEqual(len(report),9)
        self.assertTrue(all(row['matching_candidates']>0 and row['differences']==0 for row in report))

    def test_preselection_freezes_each_mode_qualified_od_without_extra_cross_mode_requirement(self):
        self.multimodal()
        cases = [('rail_bus','origin','bad',598),('rail_bus','origin','good',598),
                 ('rail_only','origin','rail',598),('walking_transfer','origin','walk',598)]
        def selected(graph,manager,repository,profile,case,mode,limit):
            return [{'relevant':not(case[2]=='bad' and mode=='fewTransfers')}]
        with patch.object(probe,'structural_cases',return_value=iter(cases)),patch.object(probe,'search_sample',side_effect=selected):
            plan = probe.select_cases(self.graph,self.manager,self.repository,self.day,3000,3)
        self.assertEqual(plan.cases['rail_bus','time'],cases[0])
        self.assertEqual(plan.cases['rail_bus','fewTransfers'],cases[1])
        self.assertEqual(plan.cases['rail_bus','cost'],cases[0])
        self.assertEqual(plan.nonmatching_queries,1)
        self.assertEqual(plan.selection_queries,10)

    def test_preselection_budget_and_missing_category_never_succeed(self):
        self.multimodal()
        cases = [('rail_bus','origin',str(index),598) for index in range(11)]
        with (patch.object(probe,'structural_cases',return_value=iter(cases)),
              patch.object(probe,'search_sample',return_value=[{'relevant':False}]) as search,
              patch.object(self.binding,'choices',side_effect=AssertionError('common before qualification'))):
            with self.assertRaisesRegex(RouteContractError,'budget exhausted'):
                probe.select_cases(self.graph,self.manager,self.repository,self.day,3000,3,max_selection_queries=9)
            self.assertEqual(search.call_count,9)
        for budget in (8,True,9.0):
            with self.assertRaises(ValueError):
                probe.select_cases(self.graph,self.manager,self.repository,self.day,3000,3,max_selection_queries=budget)

    def test_reference_search_error_is_preserved_without_trying_next_case(self):
        self.multimodal()
        error = RuntimeError('original reference search error')
        cases = [('rail_bus','origin',str(index),598) for index in range(3)]
        with (patch.object(probe,'structural_cases',return_value=iter(cases)),
              patch.object(probe,'search_sample',side_effect=error) as search):
            with self.assertRaises(RuntimeError) as raised:
                probe.select_cases(self.graph,self.manager,self.repository,self.day,3000,3)
            self.assertIs(raised.exception,error)
            search.assert_called_once()

    def test_frozen_comparison_mismatch_or_exception_never_reselects_or_changes_limit(self):
        self.multimodal()
        plan = probe.select_cases(self.graph,self.manager,self.repository,self.day,3000,3)
        with (patch.object(probe,'select_cases',side_effect=AssertionError('reselection')),
              patch.object(probe,'route_sample',return_value=[]) as search):
            with self.assertRaisesRegex(RouteContractError,'frozen sample is not replaced'):
                probe.compare_plan(self.graph,self.manager,self.repository,self.day,self.binding,plan,3)
            search.assert_called_once()
        error = RuntimeError('original common comparison error')
        with patch.object(probe,'route_sample',side_effect=error) as search:
            with self.assertRaises(RuntimeError) as raised:
                probe.compare_plan(self.graph,self.manager,self.repository,self.day,self.binding,plan,3)
            self.assertIs(raised.exception,error)
            search.assert_called_once()
        with patch.object(probe,'route_sample',side_effect=AssertionError('changed limit')):
            with self.assertRaisesRegex(RouteContractError,'candidate limit changed'):
                probe.compare_plan(self.graph,self.manager,self.repository,self.day,self.binding,plan,4)

    def test_multiple_candidates_and_input_reordering_keep_tied_order(self):
        runs = (rail._run('z',(('A',600),('B',605),('C',610))),
                rail._run('a',(('A',600),('D',605),('C',610))))
        for ordered in (runs, tuple(reversed(runs))):
            self.fixture(*ordered)
            for mode in ('time','fewTransfers','cost'):
                case = ('rail_only',rail._physical('A'),rail._physical('C'),598)
                old = probe.route_sample(self.graph,self.manager,self.repository,self.day,case,mode,3)
                new = probe.route_sample(self.graph,self.manager,self.repository,self.day,case,mode,3,self.binding.choices)
                self.assertEqual(old,new)
                if mode != 'time':
                    self.assertGreaterEqual(len(old),2)

    def test_prepare_and_alight_boundary_is_added_once(self):
        for departure in (607,608,609):
            self.fixture(rail._run('first',(('A',600),('B',605))),
                         rail._run('next',(('B',departure),('C',departure+1))))
            chosen = self.choices()
            _,state = chosen.board_options(rail._physical('A'),rail._line('A'),600)[0]
            arrival,_ = chosen.ride_options(rail._line('A'),rail._line('B'),600,state)[0]
            ready = arrival+1+2
            options = chosen.board_options(rail._physical('B'),rail._line('B'),ready)
            self.assertEqual(bool(options),departure >= 608)

    def test_no_reference_sample_stops_before_common_comparison(self):
        self.fixture(rail._run('run',(('A',600),('B',605))))
        with patch.object(self.binding,'choices',side_effect=AssertionError('unexpected common comparison')):
            with self.assertRaisesRegex(RouteContractError,'no reference-qualified'):
                probe.select_cases(self.graph,self.manager,self.repository,self.day,3000)

    def test_partial_search_error_preserves_exception_and_closes_generator_without_retry(self):
        self.fixture(rail._run('run',(('A',600),('B',605))))
        from transit_search_labels import SelectedPath
        error = RuntimeError('original later search error')
        closed = []
        def failing():
            try:
                yield {'cost':1,'walk_m':0,'path':SelectedPath([rail._physical('A')],[],{},None,598)}
                raise error
            finally:
                closed.append(True)
        original = bus.engine.gtfs_repo
        with patch.object(bus.engine,'_tokyo_label_search',return_value=failing()) as search:
            with self.assertRaises(RuntimeError) as raised:
                probe.route_sample(self.graph,self.manager,self.repository,self.day,
                                   ('rail_only',rail._physical('A'),rail._physical('B'),598),'time',3)
            self.assertIs(raised.exception,error)
            search.assert_called_once()
        self.assertEqual(closed,[True])
        self.assertIs(bus.engine.gtfs_repo,original)

    def test_projection_runs_inside_original_query_deadline_and_never_retries(self):
        self.fixture(rail._run('run',(('A',600),('B',605))))
        import tokyo_dataset_rail_choices as module
        with patch.object(module,'project_legacy_rail_snapshot',wraps=module.project_legacy_rail_snapshot) as project:
            chosen = self.binding.choices(self.graph,self.manager,day_type=self.day,
                use_realtime=False,deadline=838,bus_repository=self.repository)
            project.assert_not_called()
            with self.assertRaisesRegex(RouteContractError,'deadline-scoped preparation'):
                chosen.board_options(rail._physical('A'),rail._line('A'),600)
            error = RuntimeError('original query deadline before projection')
            def stop():
                raise error
            with self.assertRaises(RuntimeError) as raised:
                chosen.prepare(stop)
            self.assertIs(raised.exception,error)
            project.assert_not_called()
            with self.assertRaisesRegex(RouteContractError,'single-use'):
                chosen.prepare(lambda:None)

    def test_bad_reference_identity_and_original_binding_deadline_stop(self):
        self.fixture(rail._run('run',(('A',600),('B',605))))
        row = self.manager.train_patterns_weekday[rail._station('A')][0]
        for field,value in (('run_key',''),('stop_sequence',True),('dep',600.0)):
            previous = row[field]
            row[field] = value
            with self.assertRaises(RouteContractError):
                TokyoRailDatasetBinding(self.snapshot,self.manager)
            row[field] = previous
        error = RuntimeError('original binding deadline')
        def stop():
            raise error
        with self.assertRaises(RuntimeError) as raised:
            TokyoRailDatasetBinding(self.snapshot,self.manager,check_deadline=stop)
        self.assertIs(raised.exception,error)

    def test_all_dates_are_selected_before_any_common_provider_comparison(self):
        self.multimodal()
        plan = probe.select_cases(self.graph,self.manager,self.repository,self.day,3000,3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train,stations,railways,prebuilt = [root/name for name in ('train.json','stations.json','railways.json','trusted.pkl')]
            train.write_text(json.dumps(self.runs),encoding='utf-8')
            stations.write_text(json.dumps(self.stations),encoding='utf-8')
            railways.write_text(json.dumps(self.railways),encoding='utf-8')
            prebuilt.write_bytes(pickle.dumps({'G':self.graph,'TM':self.manager}))
            (root/'feed_info.txt').write_text('feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n',encoding='utf-8')
            error = RuntimeError('reference selection failed on second date')
            with (patch.object(probe.GtfsRepository,'load_data',return_value=self.repository),
                  patch.object(probe,'select_cases',side_effect=(plan,error)) as select,
                  patch.object(probe,'compare_choices',side_effect=AssertionError('common before all dates frozen')) as choices,
                  patch.object(probe,'compare_plan',side_effect=AssertionError('rank before all dates frozen')) as compare):
                with self.assertRaises(RuntimeError) as raised:
                    probe.inspect(train,stations,railways,prebuilt,root,'fixture',
                                  ('2026-09-04','2026-09-07'),3)
                self.assertIs(raised.exception,error)
                self.assertEqual(select.call_count,2)
                choices.assert_not_called()
                compare.assert_not_called()

    def test_readonly_cli_full_gate_and_marker_do_not_run_bus_matrix(self):
        self.multimodal()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train,stations,railways,prebuilt = [root/name for name in ('train.json','stations.json','railways.json','trusted.pkl')]
            train.write_text(json.dumps(self.runs),encoding='utf-8')
            stations.write_text(json.dumps(self.stations),encoding='utf-8')
            railways.write_text(json.dumps(self.railways),encoding='utf-8')
            prebuilt.write_bytes(pickle.dumps({'G':self.graph,'TM':self.manager}))
            (root/'feed_info.txt').write_text('feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n',encoding='utf-8')
            args = [str(SCRIPT),'--train-timetables',str(train),'--stations',str(stations),'--railways',str(railways),
                    '--trusted-prebuilt',str(prebuilt),'--gtfs-dir',str(root),'--expected-feed-version','fixture',
                    '--query-date','2026-09-04','--expected-sha','a'*40]
            before = {p.name:p.read_bytes() for p in root.iterdir()}
            with (patch.object(sys,'argv',args),patch.object(probe,'check_repository'),
                  patch.object(probe.GtfsRepository,'load_data',return_value=self.repository),
                  contextlib.redirect_stdout(io.StringIO()) as output):
                probe.main()
            lines = output.getvalue().splitlines()
            self.assertEqual(lines[-1],'READ_ONLY_TOKYO_COMMON_RAIL_ROUTE_SAMPLE_OK')
            report = json.loads(lines[-2])
            self.assertTrue(report['rail_binding_verified'])
            self.assertFalse(report['common_dataset_route_ranking_verified'])
            self.assertEqual(report['sample_selection'],'reference_ranked_preselection_then_frozen_comparison')
            self.assertTrue(all(row['matching_candidates']>0 for row in report['date_cases']))
            self.assertTrue(all(row['all_modes_reference_qualified'] for row in report['selection_reports']))
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            self.assertEqual(len(report['date_cases']),9)
            self.assertEqual(len(report['date_choices']),1)
            def changed(*args, **kwargs):
                train.write_text('[]',encoding='utf-8')
                return {}
            with (patch.object(sys,'argv',args),patch.object(probe,'check_repository'),
                  patch.object(probe,'inspect',side_effect=changed),
                  contextlib.redirect_stdout(io.StringIO()) as failed_output):
                with self.assertRaisesRegex(AssertionError,'input files changed'):
                    probe.main()
            self.assertNotIn('READ_ONLY_TOKYO_COMMON_RAIL_ROUTE_SAMPLE_OK',failed_output.getvalue())

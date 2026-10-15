"""No private data: strict sampled route ranking across serialization."""
import contextlib
from datetime import date
import importlib.util
import io
import json
from pathlib import Path
import pickle
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import test_tokyo_bus_choices_contract as bus

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/check_tokyo_compiled_routes_local.py'
spec = importlib.util.spec_from_file_location('tokyo_compiled_routes_probe',SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TokyoCompiledRoutesLocalCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.graph = bus._graph(('A','B'),('B','C'))
        self.repository = bus._repository(
            ('t','active',(('A',600,600),('B',610,610),('C',620,620))),
            ('later','active',(('B',615,615),('C',625,625))))
        self.repository.stop_time_boarding['t'][2] = (1,0)
        self.repository.service_calendar['active'] = {
            'start_date':'20260101','end_date':'20261231',
            'weekdays':(True,True,True,True,True,True,True)}
        self.repository.is_loaded = True
        self.manager = bus.engine.TimetableManager()

    def test_ranked_paths_clocks_costs_and_selected_occurrences_match_all_modes(self):
        # ServiceDayType uses actual repository calendar; no forged day profile.
        day = date(2026,9,4)
        compiled, size = probe.compiled_copy(self.repository)
        self.assertGreater(size,0)
        cases = probe.select_cases(self.graph,self.manager,self.repository,day)
        self.assertEqual([case[0] for case in cases],['through','alight','blocked_origin'])
        original_global = probe.engine.gtfs_repo
        for case in cases:
            for mode in ('time','fewTransfers','cost'):
                raw = probe.route_sample(self.graph,self.manager,self.repository,day,case,mode,3)
                restored = probe.route_sample(self.graph,self.manager,compiled,day,case,mode,3)
                self.assertEqual(raw,restored)
                if case[0] == 'blocked_origin':
                    self.assertTrue(all(state is None or state['board_sequence'] != 2 or state['trip_id'] != 't'
                                        for row in raw for state in row['selected_rides'].values()))
        self.assertIs(probe.engine.gtfs_repo,original_global)

    def test_missing_binding_or_unsupported_sample_stops_before_search(self):
        day = date(2026,9,4)
        self.graph.remove_edge(bus._line('B'),bus._line('C'))
        with self.assertRaisesRegex(ValueError,'no active pickup=1'):
            probe.select_cases(self.graph,self.manager,self.repository,day)

    def test_error_propagates_and_global_repository_is_restored_without_retry(self):
        original_global = probe.engine.gtfs_repo
        error = RuntimeError('original search failure')
        with patch.object(probe.engine,'_tokyo_label_search',side_effect=error) as search:
            with self.assertRaises(RuntimeError) as raised:
                probe.route_sample(self.graph,self.manager,self.repository,date(2026,9,4),
                    ('through',bus._phys('A'),bus._phys('C'),598),'time',3)
            self.assertIs(raised.exception,error)
            search.assert_called_once()
        self.assertIs(probe.engine.gtfs_repo,original_global)

    def test_subminute_query_is_not_rounded(self):
        with self.assertRaisesRegex(ValueError,'no rounding'):
            probe.route_sample(self.graph,self.manager,self.repository,date(2026,9,4),
                ('through',bus._phys('A'),bus._phys('C'),598.5),'time',3)

    def test_partial_sample_does_not_hide_a_later_search_failure(self):
        from transit_search_labels import SelectedPath
        error = RuntimeError('search limit after first result')
        closed = []
        def failing():
            try:
                yield {'cost':1,'path':SelectedPath([bus._phys('A')],[],{},None,598)}
                raise error
            finally:
                closed.append(True)
        original_global = probe.engine.gtfs_repo
        with patch.object(probe.engine,'_tokyo_label_search',return_value=failing()):
            with self.assertRaises(RuntimeError) as raised:
                probe.route_sample(self.graph,self.manager,self.repository,date(2026,9,4),
                    ('through',bus._phys('A'),bus._phys('C'),598),'cost',3)
        self.assertIs(raised.exception,error)
        self.assertEqual(closed,[True])
        self.assertIs(probe.engine.gtfs_repo,original_global)

    def full_fixture(self):
        # Fully synthetic source, with a repeated legal later trip at B.
        files = {
            'stops.txt':'stop_id,stop_name,stop_lat,stop_lon\nA,A,35,139\nB,B,35.01,139\nC,C,35.02,139\n',
            'routes.txt':'route_id,route_short_name,route_type\nR,R,3\nS,S,3\n',
            'trips.txt':'route_id,service_id,trip_id\nR,active,t\nR,active,later\nS,active,direct\n',
            'stop_times.txt':'trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\n'
                't,10:00:00,10:00:00,A,1,0,0\nt,10:10:00,10:10:00,B,2,1,0\nt,10:20:00,10:20:00,C,3,0,0\n'
                'later,10:15:00,10:15:00,B,1,0,0\nlater,10:25:00,10:25:00,C,2,0,0\n'
                'direct,10:30:00,10:30:00,A,1,0,0\ndirect,10:40:00,10:40:00,C,2,0,0\n',
            'calendar.txt':'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nactive,1,1,1,1,1,1,1,20260101,20261231\n',
            'calendar_dates.txt':'service_id,date,exception_type\n',
            'feed_info.txt':'feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n'}
        for name, content in files.items():
            (self.root/name).write_text(content,encoding='utf-8')
        direct = bus._graph(('A','C'),line='direct')
        for _,attrs in direct.nodes(data=True):
            if attrs.get('mode') == 'bus':
                attrs['route_id'] = 'S'
        self.graph = probe.nx.compose(self.graph,direct)
        prebuilt = self.root/'trusted.pkl'
        prebuilt.write_bytes(pickle.dumps({'G':self.graph,'TM':self.manager}))
        return prebuilt

    def test_full_readonly_matrix_and_distinct_success_marker(self):
        prebuilt = self.full_fixture()
        before = probe.fingerprints(self.root)
        result = probe.inspect(self.root,'fixture',('2026-09-04',),prebuilt,3)
        self.assertEqual(len(result['date_cases']),9)
        self.assertTrue(result['raw_compiled_sample_rank_verified'])
        self.assertFalse(result['common_dataset_route_ranking_verified'])
        self.assertTrue(any(row['bus_candidates'] for row in result['date_cases']))
        self.assertTrue(any(row['candidates'] > 1 for row in result['date_cases']))
        self.assertEqual(before,probe.fingerprints(self.root))
        args = [str(SCRIPT),'--gtfs-dir',str(self.root),'--expected-feed-version','fixture',
                '--query-date','2026-09-04','--trusted-prebuilt',str(prebuilt),'--expected-sha','a'*40]
        with patch.object(sys,'argv',args),patch.object(probe,'check_repository'),contextlib.redirect_stdout(io.StringIO()) as output:
            probe.main()
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[-1],'READ_ONLY_TOKYO_COMPILED_ROUTE_SAMPLE_OK')
        report = json.loads(lines[-2])
        self.assertNotIn('path',json.dumps(report))
        self.assertEqual(report['compiled_state_schema_version'],2)

    def test_changed_input_and_rank_difference_never_emit_success(self):
        prebuilt = self.full_fixture()
        args = [str(SCRIPT),'--gtfs-dir',str(self.root),'--expected-feed-version','fixture',
                '--query-date','2026-09-04','--trusted-prebuilt',str(prebuilt),'--expected-sha','a'*40]
        with patch.object(sys,'argv',args),patch.object(probe,'check_repository'),patch.object(probe,'fingerprints',side_effect=[{}, {'changed':'1'}]),patch.object(probe,'inspect',return_value={}):
            with contextlib.redirect_stdout(io.StringIO()) as output,self.assertRaisesRegex(AssertionError,'inputs changed'):
                probe.main()
            self.assertNotIn('READ_ONLY_TOKYO_COMPILED_ROUTE_SAMPLE_OK',output.getvalue())
        with patch.object(probe,'route_sample',side_effect=[[{'rank':1}],[{'rank':2}]]) as search:
            with self.assertRaisesRegex(AssertionError,'ranked sample differs'):
                probe.inspect(self.root,'fixture',('2026-09-04',),prebuilt,3)
            self.assertEqual(search.call_count,2)


if __name__ == '__main__':
    unittest.main()

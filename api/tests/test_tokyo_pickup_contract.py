"""Approved pickup=1 exception: occurrence-specific, raw and compiled."""
import copy
from pathlib import Path
import tempfile
import unittest
import zipfile

from gtfs_loader import GtfsRepository
from gtfs_state import CompiledGtfsStateError, hydrate_repository_state, repository_state_payload
from tests import test_gtfs_state as state_fixture
from tests import test_tokyo_bus_choices_contract as bus


class TokyoPickupContractTest(unittest.TestCase):
    def source(self, flags='0,0'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        archive = state_fixture._gtfs_zip(str(root / 'source.zip'))
        with zipfile.ZipFile(archive) as stream:
            stream.extractall(root)
        path = root / 'stop_times.txt'
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + ',pickup_type,drop_off_type\n' +
                        '\n'.join(row + ',' + flags for row in lines[1:]) + '\n')
        return root

    def test_loader_preserves_flags_and_three_element_clock_contract(self):
        root = self.source('1,0')
        raw = GtfsRepository('test').load_data(str(root))
        self.assertEqual(raw.get_stop_time_boarding('T1', 1), (1, 0))
        self.assertEqual(raw.stop_times['T1'][1], ('A', 600, 600))
        state = repository_state_payload(raw, 'a' * 64)
        self.assertEqual(state['schema_version'], 2)
        target = GtfsRepository('test')
        hydrate_repository_state(target, state, expected_source_sha256='a' * 64)
        self.assertEqual(target.stop_time_boarding, raw.stop_time_boarding)
        self.assertEqual(target.stop_times, raw.stop_times)

    def test_blank_optional_flags_default_to_gtfs_zero(self):
        raw = GtfsRepository('test').load_data(str(self.source(',')))
        self.assertEqual(raw.get_stop_time_boarding('T1', 1), (0, 0))

    def test_malformed_flags_or_duplicate_occurrence_fail_atomically(self):
        for flags in ('4,0', 'x,0', '1.0,0', '0,-1'):
            with self.subTest(flags=flags):
                raw = GtfsRepository('test')
                with self.assertRaises(ValueError):
                    raw.load_data(str(self.source(flags)))
                self.assertFalse(raw.is_loaded)
                self.assertEqual(dict(raw.stop_time_boarding), {})
        root = self.source()
        path = root / 'stop_times.txt'
        with path.open('a') as stream:
            stream.write(path.read_text().splitlines()[1] + '\n')
        with self.assertRaisesRegex(ValueError, 'duplicate GTFS stop occurrence'):
            GtfsRepository('test').load_data(str(root))

    def test_missing_metadata_is_fatal_and_does_not_insert_a_default(self):
        raw = GtfsRepository('test')
        with self.assertRaisesRegex(ValueError, 'metadata missing'):
            raw.get_stop_time_boarding('unknown', 1)
        self.assertEqual(dict(raw.stop_time_boarding), {})
        raw = bus._repository(('t', 'active', (('A',600,600), ('B',610,610))))
        raw.stop_time_boarding['t'].pop(1)
        with self.assertRaisesRegex(ValueError, 'metadata missing'):
            bus._choices(bus._graph(('A','B')), raw)

    def test_conditional_pickup_fails_without_an_alternate_provider(self):
        for pickup in (2,3):
            raw = bus._repository(('t','active',(('A',600,600),('B',610,610))))
            raw.stop_time_boarding['t'][1] = (pickup,0)
            with self.assertRaisesRegex(ValueError, 'conditional pickup is unsupported'):
                bus._choices(bus._graph(('A','B')), raw)

    def test_invalid_compiled_flags_and_old_schema_fail_before_mutation(self):
        raw = GtfsRepository('test').load_data(str(self.source('1,0')))
        original = repository_state_payload(raw, 'a' * 64)
        mutations = [lambda s: s.update(schema_version=1),
                     lambda s: s.update(schema_version=2.0),
                     lambda s: s['payload'].pop('stop_time_boarding'),
                     lambda s: s['payload']['stop_time_boarding'].pop('T1'),
                     lambda s: s['payload']['stop_time_boarding']['T1'].pop(1),
                     lambda s: s['payload']['stop_time_boarding']['T1'].update({1:(True,0)}),
                     lambda s: s['payload']['stop_time_boarding']['T1'].update({1:(4,0)})]
        for mutate in mutations:
            state = copy.deepcopy(original)
            mutate(state)
            target = GtfsRepository('test')
            with self.assertRaises(CompiledGtfsStateError):
                hydrate_repository_state(target, state, expected_source_sha256='a' * 64)
            self.assertFalse(target.is_loaded)
            self.assertEqual(target.trips, {})

    def test_new_boarding_blocked_but_same_trip_continuation_and_alighting_survive(self):
        raw = bus._repository(
            ('through','active',(('A',600,600),('B',610,610),('C',620,620))),
            ('later','active',(('B',615,615),('C',625,625))))
        raw.stop_time_boarding['through'][2] = (1,0)
        graph = bus._graph(('A','B'), ('B','C'))
        raw.is_loaded = True
        compiled = GtfsRepository('tokyo-test')
        hydrate_repository_state(compiled, repository_state_payload(raw,'a'*64), expected_source_sha256='a'*64)
        for source in (raw,compiled):
            choices, options = bus._choices(graph, source)
            self.assertEqual([s.trip_id for _,s in choices.board_options(bus._phys('B'),bus._line('B'),605)], ['later'])
            dep, state = options[0]
            arrival, at_b = choices.ride_options(bus._line('A'),bus._line('B'),dep,state)[0]
            self.assertEqual(arrival,610)
            self.assertEqual(choices.ride_options(bus._line('B'),bus._line('C'),arrival,at_b)[0][0],620)
            with bus.patch.object(bus.engine,'gtfs_repo',source):
                arrival, path = bus.engine.find_fastest_path(graph, bus.engine.TimetableManager(),
                    bus._phys('A'),bus._phys('B'),start_time_str='09:58',day_type=bus._day('active'),use_realtime=False)
            self.assertEqual(arrival,610)
            self.assertEqual(path[-1],bus._phys('B'))

    def test_repeated_stop_uses_sequence_and_keeps_later_legal_occurrence(self):
        raw = bus._repository(('loop','active',(('A',600,600),('B',610,610),
                              ('A',620,620),('C',630,630))))
        raw.stop_time_boarding['loop'][1] = (1,0)
        _, options = bus._choices(bus._graph(('A','B'),('B','A'),('A','C')),raw)
        self.assertEqual([(dep,s.sequence) for dep,s in options],[(620,3)])


if __name__ == '__main__':
    unittest.main()

"""Synthetic GTFS streaming contracts: no private feed or allocator threshold."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from transit_adapters.gtfs import GtfsTransitAdapter, _stop_time_rows
from tests import test_transit_dataset as fixtures


class GtfsStreamingTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        fixture = fixtures.TransitDatasetTest()
        fixture._write_gtfs(root.name)
        self.metadata = fixture._metadata('stream_fixture', 'gtfs')

    def test_strict_reader_does_not_materialize_tail_after_invalid_first_record(self):
        path = self.root / 'stop_times.txt'
        path.write_text('trip_id,arrival_time,departure_time,stop_id,stop_sequence\n'
                        't1,10:00:00,10:00:00,a,invalid\n'
                        't1,10:10:00,10:10:00,b,2\n', encoding='utf-8')
        opened = []
        actual_open = Path.open
        class LimitedReader:
            def __init__(self, handle):
                self.handle, self.lines = handle, 0
            def __iter__(self):
                return self
            def __next__(self):
                self.lines += 1
                if self.lines > 2:
                    raise AssertionError('eagerly consumed CSV tail before validating first record')
                return next(self.handle)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.handle.close()
        def guarded_open(p, *args, **kwargs):
            handle = actual_open(p, *args, **kwargs)
            if p != path:
                return handle
            wrapped = LimitedReader(handle)
            opened.append(wrapped)
            return wrapped
        with patch.object(Path, 'open', guarded_open):
            with self.assertRaisesRegex(ValueError, 'invalid stop_sequence.*stream_fixture:t1') as raised:
                GtfsTransitAdapter.load(self.root, metadata=self.metadata)
        self.assertIsInstance(raised.exception.__cause__, ValueError)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0].lines, 2)
        self.assertTrue(opened[0].handle.closed)

    def test_bom_crlf_seconds_and_unordered_sequences_preserve_record_order(self):
        text = ('trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\r\n'
                't1,24:00:59,24:01:01,b,9,1,2\r\n'
                't1,23:59:29,23:59:30,a,3,0,0\r\n')
        (self.root / 'stop_times.txt').write_text('\ufeff' + text, encoding='utf-8', newline='')
        source = GtfsTransitAdapter.load(self.root, metadata=self.metadata)
        self.assertEqual([(r.sequence, r.stop_id, r.arrival_minute, r.departure_minute,
                           r.arrival_service_seconds, r.departure_service_seconds,
                           r.pickup_type, r.drop_off_type) for r in source.stop_times],
                         [(9, 'stream_fixture:b', 1441, 1441, 86459, 86461, 1, 2),
                          (3, 'stream_fixture:a', 1439, 1440, 86369, 86370, 0, 0)])

    def test_duplicate_sequence_and_unknown_reference_still_fail(self):
        path = self.root / 'stop_times.txt'
        original = path.read_text(encoding='utf-8')
        path.write_text(original + original.splitlines()[1] + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate stop sequence'):
            GtfsTransitAdapter.load(self.root, metadata=self.metadata)
        path.write_text(original.replace(',a,1', ',unknown,1'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unknown stop'):
            GtfsTransitAdapter.load(self.root, metadata=self.metadata)

    def test_reader_contracts_are_explicit_and_file_closes_after_body_error(self):
        path = self.root / 'stop_times.txt'
        with _stop_time_rows(path, materialize=False) as rows:
            self.assertNotIsInstance(rows, list)
            first = next(rows)
            self.assertEqual(first['trip_id'], 't1')
        with _stop_time_rows(path, materialize=True) as rows:
            self.assertIsInstance(rows, list)
            self.assertEqual(rows[0], first)
            self.assertEqual(len(rows), 6)
        # Test actual context cleanup independently of iteration exhaustion.
        handles = []
        actual_open = Path.open
        def tracked_open(p, *args, **kwargs):
            handle = actual_open(p, *args, **kwargs)
            handles.append(handle)
            return handle
        original_error = RuntimeError('synthetic row consumer failure')
        with patch.object(Path, 'open', tracked_open):
            with self.assertRaises(RuntimeError) as raised:
                with _stop_time_rows(path, materialize=False):
                    raise original_error
        self.assertIs(raised.exception, original_error)
        self.assertTrue(handles[0].closed)

    def test_empty_header_and_invalid_utf8_remain_errors(self):
        path = self.root / 'stop_times.txt'
        path.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'CSV has no header'):
            GtfsTransitAdapter.load(self.root, metadata=self.metadata)
        path.write_bytes(b'\xff')
        with self.assertRaises(UnicodeDecodeError):
            GtfsTransitAdapter.load(self.root, metadata=self.metadata)


if __name__ == '__main__':
    unittest.main()

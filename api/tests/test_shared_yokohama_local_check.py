"""Offline probe tests use wholly synthetic feeds and no user input files."""
import contextlib
from dataclasses import replace
from datetime import date
import importlib.util
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from transit_dataset import ServiceException
from tests.test_transit_network import dataset
from tests.test_yokohama_municipal_transfer import _feed
from tests.test_yokohama_subway import _refresh_manifest
from tests.test_yokohama_transit import _write_manifest
from yokohama_transit import YOKOHAMA_BUS_STATIC_URL
from transit_timetable_choices import NetworkSearchParameters


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_shared_yokohama_local.py"
spec = importlib.util.spec_from_file_location("shared_yokohama_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class _Memory:
    def sample(self):
        return {"rss_bytes": 10, "process_peak_rss_bytes": 20}


class SharedYokohamaProbeTests(unittest.TestCase):
    def setUp(self):
        roots = [tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()]
        for root in roots:
            self.addCleanup(root.cleanup)
        bus, rail = (_feed(Path(root.name), rail=bool(i)) for i, root in enumerate(roots))
        source = dataset('yokohama_bus', {
            'direct': [('o', 540, 540), ('d', 590, 590)],
            'first': [('o', 540, 540), ('m', 550, 550)],
            'second': [('m', 550, 550), ('d', 570, 570)],
        })
        self.bus = replace(bus, dataset=source, route_service_kinds={'yokohama_bus:r': 'local'})
        self.coverages = self.bus, rail
        self.config = {'dates': ['2026-10-14', '2026-10-15'], 'hours': [9],
                       'repeats': 2, 'max_candidates': 3}

    def run_probe(self, engine, coverages=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = probe.run_cases(self.coverages if coverages is None else coverages,
                                     self.config, engine, _Memory())
        return {'input_hashes': {'fixture': 'synthetic'}, 'versions': {'fixture': 'v1'}, **result}

    def test_separate_engines_compare_heads_and_check_multiple_candidate_order(self):
        old, new = self.run_probe('v1'), self.run_probe('shared')
        head = self.run_probe('shared_head')
        self.assertEqual(probe.compare_workers(old, head)['comparisons'], 16)
        self.assertTrue(all(r['candidate_count'] == 1 for r in head['results']))
        summary = probe.compare_workers(old, new)
        self.assertEqual(summary['comparisons'], 16)
        self.assertEqual(summary['selection_differences'], 0)
        self.assertGreater(summary['shared_queries_with_multiple_candidates'], 0)
        self.assertFalse(summary['top_k_completeness_verified'])
        self.assertEqual(summary['walking_links'], 0)
        self.assertTrue(all(len(r['seconds']) == 2 for r in new['results']))
        bus_few = next(r for r in new['results'] if r['case'][1] == 'yokohama_bus'
                       and r['case'][-1] == 'fewTransfers')
        self.assertEqual([(c['rides'], c['arrival']) for c in bus_few['candidates']],
                         [(1, '590'), (2, '570')])

    def test_active_calendar_exception_and_missing_hour_stop_without_alternate_case(self):
        removed = replace(self.bus.dataset, service_exceptions=(ServiceException(
            'yokohama_bus:s', date(2026, 10, 15), 2),))
        with self.assertRaisesRegex(ValueError, 'no approved case.*2026-10-15'):
            probe.select_cases((replace(self.bus, dataset=removed),),
                               (date(2026, 10, 15),), (9,))
        with self.assertRaisesRegex(ValueError, 'no approved case.*hour=8'):
            probe.select_cases((self.bus,), (date(2026, 10, 14),), (8,))

    def test_seconds_are_not_rounded_for_v1_comparison(self):
        source = self.bus.dataset
        bad = replace(source.stop_times[0], arrival_service_seconds=32401,
                      departure_service_seconds=32401)
        coverage = replace(self.bus, dataset=replace(source, stop_times=(bad, *source.stop_times[1:])))
        with self.assertRaisesRegex(ValueError, 'minute-aligned source'):
            probe.select_cases((coverage,), (date(2026, 10, 14),), (9,))

    def test_comparison_mismatch_and_source_hash_mismatch_are_errors(self):
        old, new = self.run_probe('v1'), self.run_probe('shared')
        with self.assertRaisesRegex(AssertionError, 'identical source'):
            probe.compare_workers(old, {**new, 'input_hashes': {'changed': 'bytes'}})
        new['results'][0]['candidates'][0]['arrival'] = '999'
        with self.assertRaisesRegex(AssertionError, 'head selection differs'):
            probe.compare_workers(old, new)

    def test_repeated_query_rank_change_is_an_error(self):
        actual = probe.search_shared_municipal_network
        calls = [0]
        def unstable(*args, **kwargs):
            journeys = actual(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                # Inject a different but source-valid journey to distinguish
                # determinism verification from the interval validation.
                return actual(*args, **{**kwargs, 'mode': 'fewTransfers',
                    'parameters': NetworkSearchParameters(max_candidates=1,
                                                         few_transfers_tiebreak='arrival')})
            return journeys
        with patch.object(probe, 'search_shared_municipal_network', unstable):
            with self.assertRaisesRegex(AssertionError, 'repeated query changed'):
                self.run_probe('shared')

    def test_readonly_fingerprints_detect_changed_source(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for name in ('bus', 'rail'):
                (root / name).mkdir()
                (root / name / 'stops.txt').write_text('fixture', encoding='utf-8')
            (root / 'bus/yokohama_bus_gtfs_manifest.json').write_text('{}', encoding='utf-8')
            (root / 'rail/yokohama_subway_gtfs_manifest.json').write_text('{}', encoding='utf-8')
            (root / 'coverage.json').write_text('{}', encoding='utf-8')
            config = {'bus_dir': str(root / 'bus'), 'subway_dir': str(root / 'rail'),
                      'bus_coverage': str(root / 'coverage.json')}
            before = probe.fingerprints(config)
            self.assertEqual(before, probe.fingerprints(config))
            (root / 'bus/stops.txt').write_text('changed fixture', encoding='utf-8')
            self.assertNotEqual(before, probe.fingerprints(config))

    def test_memory_provider_is_explicit_and_current_peak_are_distinguished(self):
        with self.assertRaisesRegex(ValueError, 'unknown memory source'):
            probe.ProcessMemory('automatic')
        if sys.platform == 'linux':
            sample = probe.ProcessMemory('linux-proc').sample()
            self.assertGreater(sample['rss_bytes'], 0)
            self.assertGreaterEqual(sample['process_peak_rss_bytes'], sample['rss_bytes'])
            with self.assertRaisesRegex(ValueError, 'requires Windows'):
                probe.ProcessMemory('windows-psapi')
        elif sys.platform == 'win32':
            sample = probe.ProcessMemory('windows-psapi').sample()
            self.assertGreater(sample['rss_bytes'], 0)
            self.assertGreaterEqual(sample['process_peak_rss_bytes'], sample['rss_bytes'])
            with self.assertRaisesRegex(ValueError, 'requires Linux'):
                probe.ProcessMemory('linux-proc')

    @unittest.skipUnless(sys.platform in ('linux', 'win32'), 'explicit RSS providers support Windows/Linux')
    def test_real_worker_pipe_loads_synthetic_pinned_feeds_without_writing_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bus, rail = root / 'bus', root / 'rail'
            bus.mkdir()
            rail.mkdir()
            _feed(bus, rail=False)
            _feed(rail, rail=True)
            (bus / 'feed_info.txt').write_text(
                'feed_version,feed_start_date,feed_end_date\nv3.0_20260727,20260727,20270726\n',
                encoding='utf-8')
            _write_manifest(bus, service_date='2026-10-14')
            path = bus / 'yokohama_bus_gtfs_manifest.json'
            raw = json.loads(path.read_text(encoding='utf-8'))
            raw.update(calendar_coverage_from='2026-01-01', calendar_coverage_until='2026-12-31')
            path.write_text(json.dumps(raw), encoding='utf-8')
            path = bus / 'coverage.json'
            raw = json.loads(path.read_text(encoding='utf-8'))
            raw.update(feed_version='v3.0_20260727', feed_source_uri=YOKOHAMA_BUS_STATIC_URL)
            path.write_text(json.dumps(raw), encoding='utf-8')
            (rail / 'feed_info.txt').write_text(
                'feed_version,feed_start_date,feed_end_date\n20251226,20251226,20261231\n', encoding='utf-8')
            (rail / 'agency.txt').write_text(
                'agency_id,agency_name,agency_url,agency_timezone\n'
                '3000020141003,横浜市,https://www.city.yokohama.lg.jp/kotsu/,Asia/Tokyo\n', encoding='utf-8')
            route_path = rail / 'routes.txt'
            lines = route_path.read_text(encoding='utf-8').splitlines()
            route_path.write_text(lines[0] + ',agency_id\n' + '\n'.join(
                row + ',3000020141003' for row in lines[1:]) + '\n', encoding='utf-8')
            _refresh_manifest(rail)
            # Explicit platform provider, never recovery from an API error.
            source = {'linux': 'linux-proc', 'win32': 'windows-psapi'}[sys.platform]
            config = {'bus_dir': str(bus), 'subway_dir': str(rail),
                      'bus_coverage': str(bus / 'coverage.json'), 'manifest_date': '2026-10-14',
                      'dates': ['2026-10-14', '2026-10-15'], 'hours': [9],
                      'repeats': 2, 'max_candidates': 3, 'memory_source': source}
            before = probe.fingerprints(config)
            old = probe.run_worker(config, 'v1')
            head = probe.run_worker(config, 'shared_head')
            new = probe.run_worker(config, 'shared')
            self.assertEqual(probe.compare_workers(old, new)['comparisons'], 16)
            self.assertEqual(probe.compare_workers(old, head)['comparisons'], 16)
            self.assertEqual(before, probe.fingerprints(config))
            self.assertEqual(old['input_hashes'], before)
            self.assertEqual(new['input_hashes'], before)
            self.assertGreater(new['final_memory']['rss_bytes'], 0)

    def test_worker_failure_retains_original_stderr_and_return_code(self):
        completed = subprocess.CompletedProcess(['synthetic-worker'], 42, stdout='',
                                                stderr='original synthetic failure\n')
        stderr = io.StringIO()
        with patch.object(probe.subprocess, 'run', return_value=completed), contextlib.redirect_stderr(stderr):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                probe.run_worker({}, 'v1')
        self.assertEqual(raised.exception.returncode, 42)
        self.assertEqual(raised.exception.stderr, 'original synthetic failure\n')
        self.assertEqual(stderr.getvalue(), 'original synthetic failure\n')

    def test_cli_rejects_wrong_sha_before_reading_inputs_or_starting_workers(self):
        argv = [str(SCRIPT), '--bus-gtfs-dir', 'missing_bus', '--bus-coverage', 'missing_coverage',
                '--subway-gtfs-dir', 'missing_rail', '--manifest-date', '2026-10-14',
                '--query-date', '2026-10-14', '--hour', '9', '--memory-source', 'linux-proc',
                '--expected-sha', 'a' * 40]
        def git_result(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=('b' * 40 if command[-1] == 'HEAD' else 'main'), stderr='')
        with patch.object(sys, 'argv', argv), patch.object(probe.subprocess, 'run', side_effect=git_result), \
                patch.object(probe, 'run_worker') as worker:
            with self.assertRaisesRegex(ValueError, 'clean main at expected SHA'):
                probe.main()
            worker.assert_not_called()

    def test_completed_reports_remain_visible_when_later_worker_fails(self):
        old = {'engine': 'v1', **self.run_probe('v1')}
        head = {'engine': 'shared_head', **self.run_probe('shared_head')}
        failure = subprocess.CalledProcessError(1, ['synthetic-worker'], stderr='original failure')
        argv = [str(SCRIPT), '--bus-gtfs-dir', 'missing_bus', '--bus-coverage', 'missing_coverage',
                '--subway-gtfs-dir', 'missing_rail', '--manifest-date', '2026-10-14',
                '--query-date', '2026-10-14', '--hour', '9', '--memory-source', 'linux-proc',
                '--expected-sha', 'a' * 40]
        def git_result(command, **kwargs):
            last = command[-1]
            stdout = 'a' * 40 if last == 'HEAD' else ('' if last == '--porcelain' else 'main')
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr='')
        output = io.StringIO()
        with patch.object(sys, 'argv', argv), patch.object(probe.subprocess, 'run', side_effect=git_result), \
                patch.object(probe, 'run_worker', side_effect=[old, head, failure]), \
                contextlib.redirect_stdout(output):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                probe.main()
        self.assertIs(raised.exception, failure)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual({row['engine'] for row in rows if 'engine' in row}, {'v1', 'shared_head'})
        self.assertFalse(any('candidates' in row for row in rows))
        self.assertNotIn('READ_ONLY_SHARED_MATRIX_OK', output.getvalue())


if __name__ == '__main__':
    unittest.main()

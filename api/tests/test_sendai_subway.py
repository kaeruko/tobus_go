"""Independent Sendai inputs/gates; real fixtures do not certify current service."""
import base64
import csv
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import unittest

from sendai_subway_source_audit import current_departures
from transit_network import NetworkCosts, build_transit_network
from transit_adapters.sendai_subway import (
    Evidence, FILES, STATIONS, SendaiSubwayAdapter, StationReview, TableReview, inspect_csv,
)

DAY = date(2026, 10, 15)
HOLIDAY = date(2026, 10, 18)
E = Evidence("https://www.city.sendai.jp/synthetic-test-evidence", "a" * 64)
FIXTURES = Path(__file__).parent / "fixtures" / "sendai_subway"


def synthetic_input():
    files, reviews = {}, {}
    for name in FILES:
        line, kind, direction, _ = name.split("_")
        stations = STATIONS[line]
        if direction in ("north", "west"):
            stations = tuple(reversed(stations))
        clocks = tuple(23 * 3600 + 47 * 60 + i * 120 for i in range(len(stations)))
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["行先", "始発", *stations])
        writer.writerow([stations[-1], stations[0], *(f"{s // 3600 % 24}:{s // 60 % 60:02d}" for s in clocks)])
        raw = output.getvalue().encode("cp932")
        files[name] = raw
        arrivals = tuple(s if i in (0, len(clocks) - 1) else s - 20 for i, s in enumerate(clocks))
        reviews[name] = TableReview(hashlib.sha256(raw).hexdigest(), {2: arrivals},
            {station: (clocks[i],) for i, station in enumerate(stations[:-1])}, E, E, E, E,
            frozenset({DAY if kind == "w" else HOLIDAY}), "CC-BY-4.0")
    stations = {f"{line}/{station}": StationReview(38.26, 140.88, E)
                for line, names in STATIONS.items() for station in names}
    return files, reviews, stations


def normalize(files, reviews, stations):
    return SendaiSubwayAdapter().load(files, reviews=reviews, stations=stations,
        fetched_at=datetime(2026, 10, 15, tzinfo=timezone.utc))


class SendaiSubwayTest(unittest.TestCase):
    def test_published_all_eight_exact_bytes_and_independent_row_oracle(self):
        fixture = json.loads((FIXTURES / "published_20230701.json").read_text())
        self.assertEqual(set(fixture), set(FILES))
        total = wraps = 0
        for name, data in fixture.items():
            raw = base64.b64decode(data["cp932_base64"], validate=True)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), data["sha256"])
            parsed = inspect_csv(name, raw)
            source = list(csv.reader(io.StringIO(raw.decode("cp932"))))
            self.assertEqual(len(parsed.runs), len(source) - 1)
            for run, row in zip(parsed.runs, source[1:]):
                values = [int(h) * 60 + int(m) for h, m in (c.split(":") for c in row[2:])]
                exact = tuple((minute + (1440 if minute < 60 else 0)) * 60 for minute in values)
                self.assertEqual(run.service_seconds, exact)
                self.assertEqual(run.clocks, tuple(row[2:]))
                total += 1
                wraps += any(t >= 86400 for t in exact)
        self.assertEqual((total, wraps), (1046, 10))

    def test_exact_clocks_calendars_and_separate_line_station_identity(self):
        dataset = normalize(*synthetic_input())
        self.assertEqual(len(dataset.stops), 30)
        self.assertIn("sendai_subway:namboku/仙台", dataset.stops)
        self.assertIn("sendai_subway:tozai/仙台", dataset.stops)
        self.assertEqual(len(dataset.trips), 8)
        self.assertEqual(len(dataset.active_service_ids(DAY)), 4)
        self.assertFalse(dataset.active_service_ids(date(2026, 10, 16)))
        middle = next(r for r in dataset.stop_times if r.sequence == 1)
        self.assertEqual(middle.departure_service_seconds - middle.arrival_service_seconds, 20)
        self.assertTrue(any(r.arrival_service_seconds >= 86400 for r in dataset.stop_times))
        snapshot = build_transit_network((dataset,), allowed_trip_ids=frozenset(dataset.trips),
            walking_links=(), costs=NetworkCosts())
        self.assertEqual(len(snapshot.trips), 8)

    def test_missing_or_stale_evidence_rejected(self):
        files, reviews, stations = synthetic_input(); name = FILES[0]
        mutations = [replace(reviews[name], csv_sha256="b" * 64),
                     replace(reviews[name], arrivals_by_row={}),
                     replace(reviews[name], departures_by_station={}),
                     replace(reviews[name], operating_days=frozenset()),
                     replace(reviews[name], license_id="unreviewed"),
                     replace(reviews[name], arrival_clock_evidence=None)]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                normalize(files, {**reviews, name: mutation}, stations)
        with self.assertRaises(ValueError): normalize(files, {}, stations)
        with self.assertRaises(ValueError): normalize(files, reviews, {})

    def test_nonmonotone_arrivals_and_conflicting_days_rejected(self):
        files, reviews, stations = synthetic_input(); name = FILES[0]
        arrivals = list(reviews[name].arrivals_by_row[2]); arrivals[1] = 0
        with self.assertRaisesRegex(ValueError, "nonmonotone"):
            normalize(files, {**reviews, name: replace(reviews[name], arrivals_by_row={2: tuple(arrivals)})}, stations)
        bad = {name: replace(review, operating_days=frozenset({DAY})) for name, review in reviews.items()}
        with self.assertRaisesRegex(ValueError, "overlapping"): normalize(files, bad, stations)

    def test_arrival_changes_invalidate_feed_version(self):
        files, reviews, stations = synthetic_input(); name = FILES[0]
        first = normalize(files, reviews, stations)
        values = list(reviews[name].arrivals_by_row[2]); values[1] -= 1
        changed = normalize(files, {**reviews, name: replace(reviews[name], arrivals_by_row={2: tuple(values)})}, stations)
        self.assertNotEqual(first.metadata.version, changed.metadata.version)

    def test_bad_order_clock_width_encoding_rejected(self):
        files, _, _ = synthetic_input(); name = FILES[0]; text = files[name].decode("cp932")
        for bad in [text.replace("泉中央,八乙女", "八乙女,泉中央", 1),
                    text.replace("23:49", "23:46", 1), text.replace("23:49", "", 1)]:
            with self.subTest(bad=bad), self.assertRaises(ValueError): inspect_csv(name, bad.encode("cp932"))
        with self.assertRaises(UnicodeDecodeError): inspect_csv(name, b"\x81")

    def test_current_page_parser_direction_day_midnight_and_annotations(self):
        source = ('<meta charset="shift_jis"><h3>仙台</h3>'
            '<section id="0" class="time_main_table ns">'
            '<section class="weekday"><table><td class="hour">24</td><td>'
            '<span>04　</span></td></table>')
        self.assertEqual(current_departures(source.encode("shift_jis"), station="仙台", direction="south", day_kind="w"), (86640,))
        for altered in (source.replace("04　", "04臨時"), source.replace("仙台", "富沢")):
            with self.assertRaises(ValueError):
                current_departures(altered.encode("shift_jis"), station="仙台", direction="south", day_kind="w")


if __name__ == "__main__": unittest.main()

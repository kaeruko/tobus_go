"""Read-only source inspection, explicitly not an operational readiness gate."""
from collections import Counter
import hashlib
import html
import re

from transit_adapters.sendai_subway import FILES, STATIONS, inspect_csv

STATION_CODES = {
    "namboku": ("6646", "6647", "6648", "6649", "6650", "1222", "6651", "6652", "6653",
                "9285", "6654", "6655", "6656", "6657", "975", "6658", "6659"),
    "tozai": ("9727", "9728", "9729", "9730", "9731", "9732", "9285", "9733", "9734",
              "9735", "9736", "9737", "9738"),
}


def current_departures(raw_html, *, station, direction, day_kind):
    # The acquired official pages explicitly declare Shift_JIS. No lossy decode.
    source = raw_html.decode("shift_jis", errors="strict")
    if not re.search(r'<meta charset="shift_jis"\s*/?>', source, re.I):
        raise ValueError("current timetable HTML charset/schema mismatch")
    if re.findall(r"<h3>([^<]+)</h3>", source) != [{"旭ヶ丘": "旭ケ丘"}.get(station, station)]:
        raise ValueError("current timetable station identity mismatch")
    sections = re.split(r'<section id="([^"]+)" class="time_main_table ([^"]+)">', source)
    section_id, line = {"north": ("1", "ns"), "south": ("0", "ns"),
                        "east": ("2", "ew"), "west": ("3", "ew")}[direction]
    blocks = [block for ident, cls, block in zip(sections[1::3], sections[2::3], sections[3::3])
              if (ident, cls) == (section_id, line)]
    if len(blocks) != 1:
        raise ValueError("current timetable direction missing/ambiguous")
    day = {"w": "weekday", "h": "holiday"}[day_kind]
    split = blocks[0].split(f'<section class="{day}"')
    if len(split) != 2 or "</table>" not in split[1]:
        raise ValueError("current timetable day/table missing/ambiguous")
    table = split[1].split("</table>")[0]
    result = []
    rows = re.findall(r'<td class="hour">([0-9]+)</td><td>(.*?)</td>', table, re.S)
    if (not rows or len(re.findall(r'class="hour"', table)) != len(rows)
            or len({hour for hour, _ in rows}) != len(rows)):
        raise ValueError("current timetable has no hour rows")
    for hour, cell in rows:
        spans = re.findall(r"<span[^>]*>(.*?)</span>", cell, re.S)
        remainder = re.sub(r"<span[^>]*>.*?</span>", "", cell, flags=re.S)
        if html.unescape(re.sub(r"<[^>]+>", "", remainder)).strip():
            raise ValueError("unrecognized current timetable minute cell")
        for span in spans:
            text = html.unescape(span).strip()
            if re.fullmatch(r"[0-5][0-9]", text) is None or not 0 <= int(hour) <= 24:
                raise ValueError("unreviewed timetable annotation/clock")
            clock = int(hour) * 3600 + int(text) * 60
            result.append(clock + 86400 if clock < 3600 else clock)
    return tuple(result)


def audit_sources(raw_files, current_pages):
    if set(raw_files) != set(FILES):
        raise ValueError("all eight exact CSV filenames are required")
    expected_codes = set().union(*map(set, STATION_CODES.values()))
    if set(current_pages) != expected_codes:
        raise ValueError("all current official station pages are required")
    comparisons = []
    runs = 0
    wraps = 0
    for filename in FILES:
        table = inspect_csv(filename, raw_files[filename])
        line, kind, direction, _ = filename.split("_")
        mapping = dict(zip(STATIONS[line], STATION_CODES[line]))
        runs += len(table.runs)
        wraps += sum(any(clock >= 86400 for clock in run.service_seconds) for run in table.runs)
        # The terminal does not publish departures in this direction. Its CSV
        # clock is NOT compared against the opposite-direction departure table.
        for index, station in enumerate(table.stations[:-1]):
            raw = current_pages[mapping[station]]
            clocks = current_departures(raw, station=station, direction=direction, day_kind=kind)
            if Counter(clocks) != Counter(run.service_seconds[index] for run in table.runs):
                raise ValueError(f"{filename}: current departure mismatch at column {index + 2}")
            comparisons.append({"file": filename, "column": index + 2, "station_code": mapping[station],
                "departures": len(clocks), "html_sha256": hashlib.sha256(raw).hexdigest()})
    return {"csv_sha256": {name: hashlib.sha256(raw_files[name]).hexdigest() for name in FILES},
        "source_runs": runs, "midnight_runs": wraps, "departure_comparisons": comparisons,
        "operational_ready": False, "real_bus_subway_routes_verified": False,
        "blockers": ["terminal arrivals and intermediate arrival/dwell clocks unverified",
                     "explicit operational dates including holidays/special schedules unverified",
                     "municipal bus GTFS, full free segment scope and platform walking links require separate gates"]}

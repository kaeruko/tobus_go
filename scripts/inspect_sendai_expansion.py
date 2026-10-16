"""Derive explicit candidate patterns from the already approved original feed.

This is a data inventory, not a fare/transfer approval or a routing audit.
No alternate URL, feed version, route or encoding is tried on failure.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from sendai_transit import load_sendai_dataset, SENDAI_MANIFEST_FILENAME


FILES = ("agency.txt", "feed_info.txt", "routes.txt", "trips.txt",
         "stop_times.txt", "stops.txt", "calendar.txt", "calendar_dates.txt")


def inspect(root: Path, names: tuple[str, ...], expected_sha256: str):
    if not names or len(set(names)) != len(names) or any(not n for n in names):
        raise ValueError("explicit unique exact route short names required")
    manifest = json.loads((root / SENDAI_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    if manifest["sha256"] != expected_sha256:
        raise ValueError("approved source ZIP SHA mismatch")
    # Reuse the existing original ZIP/member/coverage/version validation.
    dataset = load_sendai_dataset(root, expected_service_date="2026-10-16")
    if manifest["published_version"] != "20261007_20261130":
        raise ValueError("this inventory requires the explicitly approved published version")
    raw, fields = {}, {}
    for name in FILES:
        text = (root / name).read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"missing/duplicate CSV header: {name}")
        fields[name] = reader.fieldnames
        raw[name] = list(reader)
        if any(None in row for row in raw[name]):
            raise ValueError(f"unexpected extra CSV columns: {name}")
    routes = [r for r in raw["routes.txt"] if r["route_short_name"] in names]
    present = {r["route_short_name"] for r in routes}
    if "21" not in present:
        raise ValueError("explicit candidate 21 does not exist; do not choose another route")
    routeids = {r["route_id"] for r in routes}
    trips = [r for r in raw["trips.txt"] if r["route_id"] in routeids]
    tripids = {r["trip_id"] for r in trips}
    times = [r for r in raw["stop_times.txt"] if r["trip_id"] in tripids]
    stops = {r["stop_id"] for r in times}
    services = {r["service_id"] for r in trips}
    selected = {
        "agency.txt": raw["agency.txt"], "feed_info.txt": raw["feed_info.txt"],
        "routes.txt": routes, "trips.txt": trips, "stop_times.txt": times,
        "stops.txt": [r for r in raw["stops.txt"] if r["stop_id"] in stops],
        "calendar.txt": [r for r in raw["calendar.txt"] if r["service_id"] in services],
        "calendar_dates.txt": [r for r in raw["calendar_dates.txt"] if r["service_id"] in services],
    }
    stop_by_id = {r["stop_id"]: r for r in selected["stops.txt"]}
    route_by_id = {r["route_id"]: r for r in routes}
    rows_by_trip = {tid: [] for tid in tripids}
    for row in times:
        rows_by_trip[row["trip_id"]].append(row)
    patterns = {}
    for trip in trips:
        rows = sorted(rows_by_trip[trip["trip_id"]], key=lambda r: int(r["stop_sequence"]))
        if len(rows) < 2 or len({r["stop_sequence"] for r in rows}) != len(rows):
            raise ValueError(f"invalid complete stop sequence for {trip['trip_id']}")
        key = (trip["route_id"], tuple(r["stop_id"] for r in rows))
        pattern = patterns.setdefault(key, {
            "route": route_by_id[trip["route_id"]], "stop_ids": list(key[1]),
            "stop_names": [stop_by_id[s]["stop_name"] for s in key[1]],
            "stop_coordinates": [[stop_by_id[s]["stop_lat"], stop_by_id[s]["stop_lon"]] for s in key[1]],
            "trip_ids": [], "services": [], "first_departures": [],
        })
        pattern["trip_ids"].append(trip["trip_id"])
        pattern["services"].append(trip["service_id"])
        pattern["first_departures"].append([trip["trip_id"], rows[0]["departure_time"], rows[-1]["arrival_time"]])
    files = {}
    for name in FILES:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields[name], lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(selected[name])
        files[name] = output.getvalue()
    subset = {
        "source_url": manifest["source_url"], "source_zip_sha256": manifest["sha256"],
        "source_member_sha256": {n: manifest["file_sha256"][n] for n in FILES},
        "extraction": {"route_short_names": list(names), "selection": "all exact trips of selected routes, complete ordered stop times; no free approval"},
        "files": files,
    }
    return {"published_version": manifest["published_version"], "feed_version": dataset.metadata.version,
            "calendar": selected["calendar.txt"], "calendar_dates": selected["calendar_dates.txt"],
            "patterns": list(patterns.values()), "subset": subset}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-gtfs-dir", type=Path, required=True)
    parser.add_argument("--route-short-names", nargs="+", required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    result = inspect(args.bus_gtfs_dir, tuple(args.route_short_names), args.expected_sha256)
    subset = result.pop("subset")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    packed = zlib.compress(json.dumps(subset, ensure_ascii=False, sort_keys=True).encode("utf-8"), level=9)
    print("SENDAI_EXPANSION_SUBSET_ZLIB_BASE64=" + base64.b64encode(packed).decode("ascii"))


if __name__ == "__main__":
    main()

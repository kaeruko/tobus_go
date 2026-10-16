"""Exact route-ID row selection from a verified retained-source inventory.

This creates test evidence, never an operational feed or a free-scope approval.
The original ZIP/member hashes remain attached to every derived subset.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
from pathlib import Path


def derive(source, route_ids):
    if type(route_ids) is not tuple or not route_ids or len(set(route_ids)) != len(route_ids):
        raise ValueError("explicit unique exact route IDs required")
    if source["source_zip_sha256"] != "53a08400776b3229743b24eb53566eb523b354a5b783dcfffd3e40f39258e6a2":
        raise ValueError("approved original source SHA required")
    fields, rows = {}, {}
    for name, text in source["files"].items():
        reader = csv.DictReader(io.StringIO(text))
        fields[name] = reader.fieldnames
        rows[name] = list(reader)
    chosen = set(route_ids)
    routes = [r for r in rows["routes.txt"] if r["route_id"] in chosen]
    if {r["route_id"] for r in routes} != chosen or len(routes) != len(chosen):
        raise ValueError("exact selected route set is missing/duplicated")
    trips = [r for r in rows["trips.txt"] if r["route_id"] in chosen]
    trip_ids = {r["trip_id"] for r in trips}
    times = [r for r in rows["stop_times.txt"] if r["trip_id"] in trip_ids]
    services = {r["service_id"] for r in trips}
    stops = {r["stop_id"] for r in times}
    selected = {
        "agency.txt": rows["agency.txt"], "feed_info.txt": rows["feed_info.txt"],
        "routes.txt": routes, "trips.txt": trips, "stop_times.txt": times,
        "stops.txt": [r for r in rows["stops.txt"] if r["stop_id"] in stops],
        "calendar.txt": [r for r in rows["calendar.txt"] if r["service_id"] in services],
        "calendar_dates.txt": [r for r in rows["calendar_dates.txt"] if r["service_id"] in services],
    }
    files = {}
    for name, records in selected.items():
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields[name], lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(records)
        files[name] = output.getvalue()
    return {"source_url": source["source_url"], "source_zip_sha256": source["source_zip_sha256"],
            "source_member_sha256": source["source_member_sha256"],
            "extraction": {"route_ids": list(route_ids), "selection": "all concrete trips; every complete ordered stop time; no operational/free approval"},
            "files": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--route-ids", nargs="+", required=True)
    args = parser.parse_args()
    source = json.loads(args.inventory.read_text(encoding="utf-8"))
    print(json.dumps(derive(source, tuple(args.route_ids)), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

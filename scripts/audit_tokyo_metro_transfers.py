#!/usr/bin/env python3
"""List Metro/Toei subway connections and their review state.

The input ODPT station master is an authenticated deployment input and is not
copied into the repository.  This script writes only a local derived audit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


TOEI_SUBWAY_PREFIXES = (
    "odpt.Station:Toei.Asakusa.",
    "odpt.Station:Toei.Mita.",
    "odpt.Station:Toei.Shinjuku.",
    "odpt.Station:Toei.Oedo.",
)
METRO_PREFIX = "odpt.Station:TokyoMetro."


def _station_id(station: dict) -> str:
    return str(station.get("owl:sameAs") or station.get("@id") or "")


def _connections(station: dict) -> tuple[str, ...]:
    value = station.get("odpt:connectingStation") or ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def build_audit(stations_path: Path, manifest_path: Path) -> dict:
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviewed = {
        frozenset((item["from_station_id"], item["to_station_id"])): item
        for item in manifest["transfers"]
    }
    names = {
        _station_id(station): (station.get("odpt:stationTitle") or {}).get("ja")
        for station in stations
    }
    pairs = {}
    for station in stations:
        source = _station_id(station)
        for target in _connections(station):
            if not target.startswith((METRO_PREFIX, *TOEI_SUBWAY_PREFIXES)):
                continue
            pair = frozenset((source, target))
            if len(pair) != 2:
                continue
            first, second = sorted(pair)
            pairs[pair] = {
                "from_station_id": first,
                "from_station_name_ja": names.get(first),
                "to_station_id": second,
                "to_station_name_ja": names.get(second),
                "kind": "metro_to_toei" if any(
                    value.startswith(TOEI_SUBWAY_PREFIXES) for value in pair
                ) else "metro_to_metro",
            }
    rows = []
    for pair, row in sorted(pairs.items(), key=lambda item: tuple(sorted(item[0]))):
        evidence = reviewed.get(pair)
        row["status"] = "reviewed" if evidence else "unresolved"
        if evidence:
            row["minimum_minutes"] = evidence["minimum_minutes"]
            row["walking_distance_meters"] = evidence["walking_distance_meters"]
            row["reviewed_at"] = evidence["reviewed_at"]
        else:
            row["reason"] = "official path distance/time evidence not yet complete"
        rows.append(row)
    return {
        "schema": "tokyo_metro_transfer_audit/v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "counts": {
            "total": len(rows),
            "reviewed": sum(row["status"] == "reviewed" for row in rows),
            "unresolved": sum(row["status"] == "unresolved" for row in rows),
            "metro_to_metro": sum(row["kind"] == "metro_to_metro" for row in rows),
            "metro_to_toei": sum(row["kind"] == "metro_to_toei" for row in rows),
        },
        "connections": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", required=True, type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "api" / "config" / "tokyo_metro_reviewed_transfers.json",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    audit = build_audit(args.stations, args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit["counts"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

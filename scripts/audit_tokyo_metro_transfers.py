#!/usr/bin/env python3
"""List Metro/Toei subway connections and their review state.

The input ODPT station master is an authenticated deployment input and is not
copied into the repository.  This script writes only a local derived audit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "api"))

from tokyo_metro_transfer_model import (  # noqa: E402
    automatic_path_class,
    load_transfer_policy,
)


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


def _line_id(station_id: str) -> str:
    parts = station_id.split(".")
    if len(parts) < 3:
        raise ValueError(f"unexpected ODPT station ID: {station_id!r}")
    return ".".join(parts[:-1])


def _distance_m(first: dict, second: dict) -> float | None:
    values = tuple(first.get(key) for key in ("geo:lat", "geo:long")) + tuple(
        second.get(key) for key in ("geo:lat", "geo:long")
    )
    if not all(type(value) in (int, float) and math.isfinite(value) for value in values):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, values)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _complexes(rows: list[dict], names: dict[str, str | None]) -> list[dict]:
    """Group pairwise ODPT relations into physical interchange complexes.

    This is deliberately topology-only.  A component reduces repeated review
    work (one validated corridor can be cited by several line pairs), but it
    never turns an unreviewed relation into a routable transfer.
    """

    adjacency: dict[str, set[str]] = defaultdict(set)
    row_by_pair = {}
    for row in rows:
        first, second = row["from_station_id"], row["to_station_id"]
        adjacency[first].add(second)
        adjacency[second].add(first)
        row_by_pair[frozenset((first, second))] = row

    components = []
    pending = set(adjacency)
    while pending:
        root = min(pending)
        stack = [root]
        members = set()
        while stack:
            station_id = stack.pop()
            if station_id in members:
                continue
            members.add(station_id)
            stack.extend(adjacency[station_id] - members)
        pending -= members
        component_rows = [
            row for pair, row in row_by_pair.items()
            if pair.issubset(members)
        ]
        station_slugs = sorted({
            station_id.rsplit(".", 1)[-1] for station_id in members
        })
        components.append({
            "complex_id": min(members),
            "station_slugs": station_slugs,
            "station_ids": sorted(members),
            "station_names_ja": sorted({
                names.get(station_id) or station_id.rsplit(".", 1)[-1]
                for station_id in members
            }),
            "line_ids": sorted({_line_id(station_id) for station_id in members}),
            "line_count": len({_line_id(station_id) for station_id in members}),
            "pair_count": len(component_rows),
            "reviewed_pairs": sum(row["status"] == "reviewed" for row in component_rows),
            "automatic_pairs": sum(
                row["status"] == "automatic_same_station" for row in component_rows
            ),
            "unresolved_pairs": sum(row["status"] == "unresolved" for row in component_rows),
            "pair_station_ids": sorted(
                [row["from_station_id"], row["to_station_id"]]
                for row in component_rows
            ),
        })

    # This order measures review leverage, not passenger demand: complexes
    # covering the most still-disabled line pairs come first.
    components.sort(key=lambda item: (
        -item["unresolved_pairs"], -item["line_count"], item["complex_id"]
    ))
    for priority, component in enumerate(components, 1):
        component["review_priority"] = priority
        component["priority_basis"] = "unresolved_pair_count_then_line_count"
    return components


def build_audit(
    stations_path: Path,
    manifest_path: Path,
    counterpart_stations_path: Path | None = None,
) -> dict:
    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    counterpart_stations = (
        [] if counterpart_stations_path is None
        else json.loads(counterpart_stations_path.read_text(encoding="utf-8"))
    )
    if not isinstance(stations, list) or not isinstance(counterpart_stations, list):
        raise ValueError("ODPT station audit inputs must be lists")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    policy = load_transfer_policy(manifest)
    automatic_enabled = policy.automatic_enabled
    reviewed = policy.overrides
    names = {
        _station_id(station): (station.get("odpt:stationTitle") or {}).get("ja")
        for station in (*stations, *counterpart_stations)
    }
    by_id = {
        _station_id(station): station for station in (*stations, *counterpart_stations)
    }
    directed_relations = {
        (_station_id(station), target)
        for station in (*stations, *counterpart_stations)
        for target in _connections(station)
        if target.startswith((METRO_PREFIX, *TOEI_SUBWAY_PREFIXES))
        and target != _station_id(station)
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
        first, second = sorted(pair)
        evidence = reviewed.get(pair)
        exception = policy.exceptions.get(pair)
        path_class = automatic_path_class(first, second) if automatic_enabled else None
        reciprocal = (
            (first, second) in directed_relations
            and (second, first) in directed_relations
        )
        reference_separation = (
            None if first not in by_id or second not in by_id
            else _distance_m(by_id[first], by_id[second])
        )
        automatic = (
            path_class is not None
            and reciprocal
        )
        row["status"] = (
            "reviewed" if evidence else
            "automatic_same_station" if automatic else
            "unresolved"
        )
        row["official_relation_reciprocal"] = reciprocal
        row["station_reference_point_separation_meters"] = reference_separation
        row["evidence"] = {
            "official_connection_verified": True,
            "path_verified": evidence is not None,
            "physical_distance_verified": evidence is not None,
            "minimum_time_verified": evidence is not None,
            "direction_restrictions_verified": exception is not None,
            "availability_hours_verified": exception is not None,
        }
        if evidence:
            row["minimum_minutes"] = evidence["minutes"]
            row["walking_distance_meters"] = evidence["meters"]
            row["reviewed_at"] = evidence["reviewed_at"]
        elif automatic:
            row["minimum_minutes"] = policy.automatic_minutes
            row["walking_distance_meters"] = None
            row["walk_resource_meters"] = policy.automatic_resource_meters
            row["time_basis"] = "app_conservative_allowance"
        else:
            row["reason"] = (
                "official relation is not reciprocal"
                if path_class and not reciprocal else
                "official path distance/time evidence not yet complete"
            )
        rows.append(row)
    complexes = _complexes(rows, names)
    return {
        "schema": "tokyo_metro_transfer_audit/v3",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "counts": {
            "total": len(rows),
            "reviewed": sum(row["status"] == "reviewed" for row in rows),
            "automatic_same_station": sum(
                row["status"] == "automatic_same_station" for row in rows
            ),
            "nonreciprocal_same_station": sum(
                row["status"] == "unresolved"
                and row.get("reason") == "official relation is not reciprocal"
                for row in rows
            ),
            "unresolved": sum(row["status"] == "unresolved" for row in rows),
            "metro_to_metro": sum(row["kind"] == "metro_to_metro" for row in rows),
            "metro_to_toei": sum(row["kind"] == "metro_to_toei" for row in rows),
        },
        "complex_counts": {
            "total": len(complexes),
            "fully_reviewed": sum(item["unresolved_pairs"] == 0 for item in complexes),
            "partially_reviewed": sum(
                item["reviewed_pairs"] + item["automatic_pairs"] > 0
                and item["unresolved_pairs"] > 0
                for item in complexes
            ),
            "unreviewed": sum(
                item["reviewed_pairs"] + item["automatic_pairs"] == 0
                for item in complexes
            ),
        },
        "complexes": complexes,
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
    parser.add_argument("--counterpart-stations", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    audit = build_audit(args.stations, args.manifest, args.counterpart_stations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit["counts"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

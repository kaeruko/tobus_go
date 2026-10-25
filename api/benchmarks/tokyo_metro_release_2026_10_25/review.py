from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path


def load_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return json.load(source)
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def minute(value: str | None) -> int | None:
    if not value:
        return None
    hour, minute_value = map(int, value.split(":")[:2])
    return hour * 60 + minute_value


def gtfs_minute(value: str) -> int:
    hour, minute_value, second = map(int, value.split(":"))
    if second != 0:
        raise ValueError(f"unexpected non-minute GTFS time: {value}")
    return hour * 60 + minute_value


def raw_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.removeprefix("tokyo_metro:")


def service_active(
    service_id: str,
    service_date: str,
    calendars: dict[str, dict[str, str]],
    exceptions: dict[tuple[str, str], int],
) -> bool:
    exception = exceptions.get((service_date.replace("-", ""), service_id))
    if exception is not None:
        return exception == 1
    row = calendars[service_id]
    compact = service_date.replace("-", "")
    import datetime as dt

    weekday = dt.date.fromisoformat(service_date).strftime("%A").lower()
    return row["start_date"] <= compact <= row["end_date"] and row[weekday] == "1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independently review fixed-corpus candidate snapshots against GTFS"
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--metro-gtfs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = load_json(args.result)
    corpus = load_json(args.corpus)
    rows = result["rows"]
    cases = {
        case["name"]: case
        for case in (*corpus["matrix_cases"], *corpus["supplemental_cases"])
    }
    trips = {row["trip_id"]: row for row in read_csv(args.metro_gtfs / "trips.txt")}
    stop_times: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(args.metro_gtfs / "stop_times.txt"):
        stop_times[row["trip_id"]].append(row)
    for values in stop_times.values():
        values.sort(key=lambda row: int(row["stop_sequence"]))
    calendars = {
        row["service_id"]: row for row in read_csv(args.metro_gtfs / "calendar.txt")
    }
    exceptions = {
        (row["date"], row["service_id"]): int(row["exception_type"])
        for row in read_csv(args.metro_gtfs / "calendar_dates.txt")
    }

    violations: list[str] = []
    trip_steps_checked = 0
    transfer_steps_checked = 0
    candidate_prefix_groups = 0

    grouped: dict[tuple[str, str, bool], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["case"], row["mode"], row["estimated_transfers"])].append(row)
    for key, group in grouped.items():
        by_limit = {row["candidate_limit"]: row for row in group}
        if len(by_limit) <= 1:
            continue
        candidate_prefix_groups += 1
        largest = by_limit[max(by_limit)]["candidates"]
        for limit, row in by_limit.items():
            if row["candidates"] != largest[: len(row["candidates"])]:
                violations.append(f"{key}: limit {limit} is not an ordered prefix")

    zero_rows = []
    for row in rows:
        case = cases[row["case"]]
        if row["candidate_count"] == 0:
            zero_rows.append(row)
        for rank, candidate in enumerate(row["candidates"], 1):
            previous_arrival = minute(row["time"])
            for step_index, step in enumerate(candidate["steps"]):
                departure = minute(step.get("departure_time"))
                arrival = minute(step.get("arrival_time"))
                if departure is not None and previous_arrival is not None and departure < previous_arrival:
                    violations.append(
                        f"{row['case']}/{row['mode']}/rank{rank}/step{step_index}: time goes backwards"
                    )
                if departure is not None and arrival is not None and arrival < departure:
                    violations.append(
                        f"{row['case']}/{row['mode']}/rank{rank}/step{step_index}: negative duration"
                    )
                if arrival is not None:
                    previous_arrival = arrival

                selected = step.get("selected_run")
                if not isinstance(selected, dict) or not str(selected.get("trip_id", "")).startswith("tokyo_metro:"):
                    continue
                trip_steps_checked += 1
                trip_id = raw_id(selected["trip_id"])
                trip = trips.get(trip_id)
                if trip is None:
                    violations.append(f"unknown GTFS trip {selected['trip_id']}")
                    continue
                if raw_id(selected.get("route_id")) != trip["route_id"]:
                    violations.append(f"{trip_id}: route_id disagrees with trips.txt")
                if selected.get("service_id") != trip["service_id"]:
                    violations.append(f"{trip_id}: service_id disagrees with trips.txt")
                if selected.get("service_key") != row["date"]:
                    violations.append(f"{trip_id}: selected run belongs to another service date")
                if not service_active(trip["service_id"], row["date"], calendars, exceptions):
                    violations.append(f"{trip_id}: service is inactive on {row['date']}")

                origin = raw_id(selected.get("origin_gtfs_stop_id"))
                destination = raw_id(selected.get("destination_gtfs_stop_id"))
                timed = stop_times[trip_id]
                origins = [i for i, item in enumerate(timed) if item["stop_id"] == origin]
                destinations = [i for i, item in enumerate(timed) if item["stop_id"] == destination]
                endpoint_pairs = [(i, j) for i in origins for j in destinations if i < j]
                if len(endpoint_pairs) != 1:
                    violations.append(f"{trip_id}: GTFS endpoints are not uniquely ordered")
                    continue
                origin_index, destination_index = endpoint_pairs[0]
                scheduled_departure = gtfs_minute(timed[origin_index]["departure_time"])
                scheduled_arrival = gtfs_minute(timed[destination_index]["arrival_time"])
                if selected.get("scheduled_departure_minute") != scheduled_departure:
                    violations.append(f"{trip_id}: departure differs from stop_times.txt")
                if selected.get("scheduled_arrival_minute") != scheduled_arrival:
                    violations.append(f"{trip_id}: arrival differs from stop_times.txt")
                if departure != scheduled_departure or arrival != scheduled_arrival:
                    violations.append(f"{trip_id}: displayed clocks differ from GTFS")

                if step_index:
                    prior = candidate["steps"][step_index - 1]
                    if prior.get("kind") == "walk":
                        transfer_steps_checked += 1
                        prior_arrival = minute(prior.get("arrival_time"))
                        if prior_arrival is None or departure is None or departure < prior_arrival:
                            violations.append(f"{trip_id}: train departs before transfer walk ends")

            if candidate["arrival_time"] is not None and previous_arrival is not None:
                if minute(candidate["arrival_time"]) < previous_arrival:
                    violations.append(f"{row['case']}/{row['mode']}/rank{rank}: candidate arrival conflicts with steps")

    expected_zero_keys = {
        ("estimated_transfer_stress", mode, limit, False)
        for mode in corpus["fixed_contract"]["modes"]
        for limit in corpus["fixed_contract"]["candidate_limits"]
    }
    observed_zero_keys = {
        (row["case"], row["mode"], row["candidate_limit"], row["estimated_transfers"])
        for row in zero_rows
    }
    if observed_zero_keys != expected_zero_keys:
        violations.append(
            f"zero-candidate set changed: expected={sorted(expected_zero_keys)!r}, observed={sorted(observed_zero_keys)!r}"
        )
    topology = result.get("fixed_station_topology", {}).get("estimated_transfer_stress", {})
    if topology != {"ordinary": False, "estimated": True}:
        violations.append(f"zero-case topology proof changed: {topology!r}")
    stress_estimated = [
        row
        for row in rows
        if row["case"] == "estimated_transfer_stress"
        and row["estimated_transfers"]
        and row["candidate_limit"] == 5
    ]
    if not stress_estimated or any(
        not candidate["contains_estimated_transfer"]
        for row in stress_estimated
        for candidate in row["candidates"]
    ):
        violations.append("estimated stress candidates are not marked as estimated")

    representative = {}
    for case_name in (
        "tokyo_metro_only",
        "metro_public_holiday",
        "metro_last_train",
        "metro_date_crossing",
        "reviewed_transfer_forward",
        "reviewed_transfer_reverse",
        "estimated_transfer_stress",
    ):
        selected = [
            row
            for row in rows
            if row["case"] == case_name
            and row["mode"] == "fewTransfers"
            and row["candidate_limit"] == 5
            and row["estimated_transfers"] == (case_name == "estimated_transfer_stress")
        ]
        if len(selected) != 1:
            violations.append(f"missing representative row: {case_name}")
            continue
        row = selected[0]
        representative[case_name] = {
            "candidate_count": row["candidate_count"],
            "ordered_candidate_sha256": row["candidate_sha256"],
            "first_candidate_trip_ids": [
                step["trip_id"]
                for step in (row["candidates"][0]["steps"] if row["candidates"] else [])
                if step.get("trip_id")
            ],
            "first_candidate_arrival": row["candidates"][0]["arrival_time"] if row["candidates"] else None,
        }

    output = {
        "schema": "tokyo_metro_release_snapshot_review/v1",
        "result_rows": len(rows),
        "candidate_prefix_groups_checked": candidate_prefix_groups,
        "metro_trip_steps_checked_against_gtfs": trip_steps_checked,
        "transfer_boardings_checked": transfer_steps_checked,
        "zero_candidate_rows": len(zero_rows),
        "zero_candidate_classification": {
            "case": "estimated_transfer_stress",
            "reason": "ordinary scoped graph has no directed path; opt-in graph has a path and exact candidates traverse estimated edges",
            "ordinary_topology_path": topology.get("ordinary"),
            "estimated_topology_path": topology.get("estimated"),
        },
        "representative_cases": representative,
        "violations": violations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if violations:
        for violation in violations:
            print(f"VIOLATION: {violation}")
        return 1
    print(
        f"reviewed {len(rows)} rows, {trip_steps_checked} Metro trip steps, "
        f"{transfer_steps_checked} transfer boardings; no violations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

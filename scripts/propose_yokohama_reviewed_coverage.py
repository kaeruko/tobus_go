"""Propose development-only Yokohama municipal free-pass routes from one review registry.

This script NEVER auto-discovers free routes from names, clocks or operator
identity. Only exact route IDs marked "development_eligible" in the checked-in
scripts/yokohama_municipal_route_reviews.json can be promoted, after strict
GTFS feed/route-name, previous-coverage, reference URL and review-date checks.
Routes marked "pending" are refused. ALL source files remain unmodified.

By default stdout is a DRY RUN; --output creates a NEW JSON file (exclusive
create) and never overwrites an existing file.

Example, starting from the original three-route partial coverage:
 python scripts/propose_yokohama_reviewed_coverage.py \
   --gtfs-dir api/data/yokohama/2026-09-04 \
   --coverage api/data/yokohama/2026-09-04/coverage.json \
   --service-date 2026-09-04 --reviewed-on 2026-10-14 \
   --route-id 008 --route-id 288
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from yokohama_fare_coverage import YokohamaFareCoverage
from yokohama_transit import load_yokohama_bus_dataset

_REGISTRY = Path(__file__).with_name("yokohama_municipal_route_reviews.json")
_BASE_LOCAL = frozenset({
    "yokohama_bus:089", "yokohama_bus:200", "yokohama_bus:280",
})
_EXCLUDED = "yokohama_bus:271"
_VALID_STATUS = frozenset({"development_eligible", "pending"})


def _date(text: str, *, field: str) -> date:
    if not isinstance(text, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{field} must be zero-padded YYYY-MM-DD")
    return parsed


def _trusted_https(url: str) -> bool:
    if not isinstance(url, str) or not url or url != url.strip():
        return False
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.port is not None:
            return False
    except ValueError:
        return False
    if (
        parsed.scheme != "https" or not host or parsed.username or parsed.password
        or parsed.fragment or any(c.isspace() for c in url)
    ):
        return False
    return (
        host == "city.yokohama.lg.jp"
        or host.endswith(".city.yokohama.lg.jp")
        or host == "www.seirei.or.jp"
    )


def _load_reviews(dataset, *, reviewed_on: str) -> dict:
    raw = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version", "feed_id", "feed_version", "purpose", "routes"
    }:
        raise ValueError("municipal route review registry schema mismatch")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("unsupported municipal review registry schema")
    if raw["feed_id"] != dataset.metadata.feed_id or raw["feed_version"] != dataset.metadata.version:
        raise ValueError("municipal review registry feed identity mismatch")
    if not isinstance(raw["purpose"], str) or not raw["purpose"]:
        raise ValueError("review registry purpose is required")
    records = raw["routes"]
    if not isinstance(records, dict) or not records:
        raise ValueError("municipal review registry must contain reviewed routes")
    stamp = _date(reviewed_on, field="reviewed-on")
    for number, info in records.items():
        if (
            not isinstance(number, str) or len(number) != 3
            or not number.isascii() or not number.isdigit()
        ):
            raise ValueError(f"invalid three-digit reviewed route ID: {number!r}")
        if not isinstance(info, dict) or set(info) != {
            "status", "short_name", "long_name", "reviewed_on",
            "evidence_urls", "remaining_checks"
        }:
            raise ValueError(f"review registry fields mismatch: route {number}")
        if info["status"] not in _VALID_STATUS:
            raise ValueError(f"invalid review decision: route {number}")
        route_id = f"yokohama_bus:{number}"
        route = dataset.routes.get(route_id)
        if route is None:
            raise ValueError(f"reviewed route missing from pinned GTFS: {route_id}")
        if (
            route.short_name != info["short_name"]
            or route.long_name != info["long_name"]
        ):
            raise ValueError(f"reviewed route name/identity changed: {route_id}")
        if _date(info["reviewed_on"], field=f"{number}.reviewed_on") > stamp:
            raise ValueError(f"review date is after proposed review date: {number}")
        urls = info["evidence_urls"]
        if (
            not isinstance(urls, list) or not urls
            or any(not _trusted_https(item) for item in urls)
            or len(set(urls)) != len(urls)
        ):
            raise ValueError(f"invalid/duplicate official evidence URL: route {number}")
        notes = info["remaining_checks"]
        if (
            not isinstance(notes, list) or not notes
            or any(not isinstance(note, str) or not note.strip() for note in notes)
        ):
            raise ValueError(f"reviewed route must record remaining checks: {number}")
    return records


def propose_reviewed(
    *, gtfs_dir: Path, coverage_path: Path,
    service_date: str, reviewed_on: str, route_ids: tuple[str, ...],
) -> tuple[dict, dict]:
    _date(service_date, field="service-date")
    _date(reviewed_on, field="reviewed-on")
    if not route_ids:
        raise ValueError("select at least one explicit --route-id")
    if len(set(route_ids)) != len(route_ids):
        raise ValueError("duplicate --route-id")
    dataset = load_yokohama_bus_dataset(
        gtfs_dir, expected_service_date=service_date,
    )
    coverage = YokohamaFareCoverage.load(coverage_path, dataset=dataset)
    raw = json.loads(coverage_path.read_text(encoding="utf-8"))
    if raw["schema_version"] != 1 or coverage.reviewed_free_trip_uris is not None:
        raise ValueError("route-based development proposal requires coverage schema v1")
    if coverage.operator_id != "yokohama_municipal_bus":
        raise ValueError("reviewed-route proposal requires municipal bus")
    if coverage.route_service_kinds.get(_EXCLUDED) != "sightseeing":
        raise ValueError("Akai Kutsu exclusion is missing")
    if "あかいくつ" not in (
        dataset.routes[_EXCLUDED].short_name + dataset.routes[_EXCLUDED].long_name
    ):
        raise ValueError("Akai Kutsu route name no longer matches")
    records = _load_reviews(dataset, reviewed_on=reviewed_on)
    source_local = {
        key for key, kind in coverage.route_service_kinds.items()
        if kind == "local"
    }
    if not _BASE_LOCAL <= source_local:
        raise ValueError("original three-route development baseline missing")
    eligible = {
        f"yokohama_bus:{number}" for number, record in records.items()
        if record["status"] == "development_eligible"
    }
    if not source_local <= (_BASE_LOCAL | eligible):
        raise ValueError("unexpected enabled route: source coverage cannot be trusted")
    if any(
        kind != "unreviewed" for key, kind in coverage.route_service_kinds.items()
        if key not in source_local | {_EXCLUDED}
    ):
        raise ValueError("unexpected classification outside original enabled routes")

    additions = []
    for number in route_ids:
        if (
            not isinstance(number, str) or len(number) != 3
            or not number.isascii() or not number.isdigit()
        ):
            raise ValueError(f"route IDs must be exactly 3 digits: {number!r}")
        record = records.get(number)
        if record is None:
            raise ValueError(f"route {number} has no explicit review record")
        if record["status"] != "development_eligible":
            raise ValueError(f"route {number} is pending official fare review; cannot enable")
        route_id = f"yokohama_bus:{number}"
        if route_id in source_local:
            raise ValueError(f"route {number} is already enabled in the source coverage")
        if coverage.route_service_kinds.get(route_id) != "unreviewed":
            raise ValueError(f"route {number} is not unreviewed; refuse proposal")
        if not any(trip.route_id == route_id for trip in dataset.trips.values()):
            raise ValueError(f"route {number} has no trips in pinned feed")
        additions.append(route_id)

    proposal = {
        **raw,
        "reviewed_on": reviewed_on,
        "routes": {
            **raw["routes"],
            **{route_id: "local" for route_id in additions},
        },
    }
    totals = Counter(proposal["routes"].values())
    return proposal, {
        "operation": "DEVELOPMENT ONLY: not production fare certification",
        "feed_version": dataset.metadata.version,
        "source_coverage": str(coverage_path),
        "added_route_ids": [route_id.split(":")[-1] for route_id in additions],
        "enabled_route_ids": sorted(
            route_id.split(":")[-1] for route_id, kind
            in proposal["routes"].items() if kind == "local"
        ),
        "route_counts": {
            kind: totals[kind] for kind in ("local", "sightseeing", "unreviewed")
        },
        "review_evidence": {
            route_id.split(":")[-1]: records[route_id.split(":")[-1]]["evidence_urls"]
            for route_id in additions
        },
        "remaining_checks": {
            route_id.split(":")[-1]: records[route_id.split(":")[-1]]["remaining_checks"]
            for route_id in additions
        },
        "unchanged_excluded_route_id": "271",
        "warning": (
            "This is a development coverage proposal only; a pass-eligible "
            "route name and sample same-GTFS smoke do not independently "
            "certify all trip fares or publication readiness."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--reviewed-on", required=True)
    parser.add_argument("--route-id", required=True, action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    proposal, report = propose_reviewed(
        gtfs_dir=args.gtfs_dir, coverage_path=args.coverage,
        service_date=args.service_date, reviewed_on=args.reviewed_on,
        route_ids=tuple(args.route_id),
    )
    if args.output is None:
        report["file_action"] = "DRY RUN: no files written"
    else:
        if args.output.resolve() == args.coverage.resolve():
            raise ValueError("refusing to overwrite source coverage")
        if not args.output.parent.is_dir():
            raise FileNotFoundError(f"output directory does not exist: {args.output.parent}")
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
        # Exclusive creation. Do not make directories, delete files or alter
        # the original GTFS or coverage.
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(proposal, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        report["file_action"] = f"CREATED: {args.output}"
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

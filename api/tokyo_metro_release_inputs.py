"""Fail-closed, read-only validation for a pinned Tokyo Metro static release.

This module does not download, publish, or replace data.  Operations run it on
staged inputs before invoking the existing prebuild process.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pickle
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import networkx as nx

from toei_engine import TimetableManager
from tokyo_metro_gtfs import REQUIRED_FILES, add_tokyo_metro_to_graph


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_sha(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return normalized


def _validate_archive(archive_path: Path, expected_sha256: str) -> zipfile.ZipFile:
    actual = sha256(archive_path)
    if actual != _required_sha(expected_sha256, "expected archive SHA-256"):
        raise ValueError(
            f"Tokyo Metro GTFS archive SHA-256 mismatch: expected={expected_sha256} actual={actual}"
        )
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as error:
        raise ValueError("Tokyo Metro GTFS archive is not a valid ZIP") from error
    names: set[str] = set()
    try:
        for member in archive.infolist():
            pure = PurePosixPath(member.filename)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or len(pure.parts) != 1
                or member.is_dir()
            ):
                raise ValueError(f"unsafe Tokyo Metro GTFS member: {member.filename!r}")
            if member.flag_bits & 0x1:
                raise ValueError("encrypted Tokyo Metro GTFS members are not accepted")
            if member.filename in names:
                raise ValueError(f"duplicate Tokyo Metro GTFS member: {member.filename}")
            names.add(member.filename)
        missing = sorted(set(REQUIRED_FILES) - names)
        if missing:
            raise ValueError(f"Tokyo Metro GTFS archive is missing: {', '.join(missing)}")
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"Tokyo Metro GTFS CRC failed: {bad_member}")
    except Exception:
        archive.close()
        raise
    return archive


def validate_release_inputs(
    *,
    archive_path: Path,
    stations_path: Path,
    railways_path: Path,
    transfer_manifest_path: Path,
    expected_archive_sha256: str,
    expected_station_sha256: str,
    expected_railway_sha256: str,
    expected_transfer_manifest_sha256: str,
    expected_version: str,
    expected_valid_from: dt.date,
    expected_valid_until: dt.date,
    service_date: dt.date,
    counterpart_stations_path: Path | None = None,
    expected_counterpart_stations_sha256: str | None = None,
    base_app_data_path: Path | None = None,
    expected_base_app_data_sha256: str | None = None,
) -> dict:
    station_hash = sha256(stations_path)
    railway_hash = sha256(railways_path)
    transfer_manifest_hash = sha256(transfer_manifest_path)
    if station_hash != _required_sha(expected_station_sha256, "expected station SHA-256"):
        raise ValueError("Tokyo Metro station master SHA-256 mismatch")
    if railway_hash != _required_sha(expected_railway_sha256, "expected railway SHA-256"):
        raise ValueError("Tokyo Metro railway master SHA-256 mismatch")
    if transfer_manifest_hash != _required_sha(
        expected_transfer_manifest_sha256, "expected transfer-manifest SHA-256"
    ):
        raise ValueError("Tokyo Metro transfer-manifest SHA-256 mismatch")

    counterpart_hash = None
    if (counterpart_stations_path is None) != (
        expected_counterpart_stations_sha256 is None
    ):
        raise ValueError(
            "counterpart-stations path and expected SHA-256 must be supplied together"
        )
    if counterpart_stations_path is not None:
        counterpart_hash = sha256(counterpart_stations_path)
        if counterpart_hash != _required_sha(
            expected_counterpart_stations_sha256,
            "expected counterpart-stations SHA-256",
        ):
            raise ValueError("counterpart-stations SHA-256 mismatch")

    base_hash = None
    if base_app_data_path is not None:
        if expected_base_app_data_sha256 is None:
            raise ValueError("expected base app-data SHA-256 is required")
        base_hash = sha256(base_app_data_path)
        if base_hash != _required_sha(
            expected_base_app_data_sha256, "expected base app-data SHA-256"
        ):
            raise ValueError("base app-data SHA-256 mismatch")

    archive = _validate_archive(archive_path, expected_archive_sha256)
    try:
        with tempfile.TemporaryDirectory(prefix="tokyo-metro-release-") as directory:
            archive.extractall(directory)
            if base_app_data_path is None:
                graph = nx.DiGraph()
                manager = TimetableManager()
            else:
                with base_app_data_path.open("rb") as source:
                    base = pickle.load(source)
                graph = base.get("G")
                manager = base.get("TM")
                if graph is None or manager is None:
                    raise ValueError("base app data is missing G or TM")
            info = add_tokyo_metro_to_graph(
                graph,
                manager,
                gtfs_dir=directory,
                stations_path=str(stations_path),
                railways_path=str(railways_path),
                counterpart_stations_path=(
                    str(counterpart_stations_path) if counterpart_stations_path else None
                ),
                reviewed_transfers_path=str(transfer_manifest_path),
            )
    finally:
        archive.close()

    expected = (expected_version, expected_valid_from, expected_valid_until)
    observed = (info.version, info.start_date, info.end_date)
    if observed != expected:
        raise ValueError(
            "Tokyo Metro GTFS edition mismatch: "
            f"expected={expected_version}/{expected_valid_from}/{expected_valid_until} "
            f"observed={info.version}/{info.start_date}/{info.end_date}"
        )
    if not info.start_date <= service_date <= info.end_date:
        raise ValueError(
            f"Tokyo Metro service date is outside the feed period: {service_date}"
        )
    return {
        "schema": "tokyo_metro_release_input_verification/v1",
        "archive_sha256": sha256(archive_path),
        "station_master_sha256": station_hash,
        "railway_master_sha256": railway_hash,
        "counterpart_station_master_sha256": counterpart_hash,
        "transfer_manifest_sha256": transfer_manifest_hash,
        "base_app_data_sha256": base_hash,
        "feed_version": info.version,
        "valid_from": info.start_date.isoformat(),
        "valid_until": info.end_date.isoformat(),
        "service_date": service_date.isoformat(),
        "routes": info.route_count,
        "stops": info.stop_count,
        "trips": info.trip_count,
        "status": "accepted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify pinned Tokyo Metro release inputs")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--stations", type=Path, required=True)
    parser.add_argument("--railways", type=Path, required=True)
    parser.add_argument("--counterpart-stations", type=Path)
    parser.add_argument("--transfer-manifest", type=Path, required=True)
    parser.add_argument("--base-app-data", type=Path)
    parser.add_argument("--expected-base-app-data-sha256")
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--expected-station-sha256", required=True)
    parser.add_argument("--expected-railway-sha256", required=True)
    parser.add_argument("--expected-counterpart-stations-sha256")
    parser.add_argument("--expected-transfer-manifest-sha256", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-valid-from", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--expected-valid-until", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--service-date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_release_inputs(
        archive_path=args.archive,
        stations_path=args.stations,
        railways_path=args.railways,
        counterpart_stations_path=args.counterpart_stations,
        transfer_manifest_path=args.transfer_manifest,
        expected_archive_sha256=args.expected_archive_sha256,
        expected_station_sha256=args.expected_station_sha256,
        expected_railway_sha256=args.expected_railway_sha256,
        expected_counterpart_stations_sha256=(
            args.expected_counterpart_stations_sha256
        ),
        expected_transfer_manifest_sha256=args.expected_transfer_manifest_sha256,
        expected_version=args.expected_version,
        expected_valid_from=args.expected_valid_from,
        expected_valid_until=args.expected_valid_until,
        service_date=args.service_date,
        base_app_data_path=args.base_app_data,
        expected_base_app_data_sha256=args.expected_base_app_data_sha256,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

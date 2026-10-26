"""Fail-closed checks for the Tokyo bus graph and concrete GTFS feed."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from tokyo_timetable_choices import TimetableChoices


RELEASE_MANIFEST_SCHEMA = "toei_bus_static_release/v1"


class TokyoStaticCompatibilityError(RuntimeError):
    """The installed Tokyo static inputs cannot safely be used together."""


@dataclass(frozen=True)
class BusTopologyCompatibilityReport:
    graph_adjacencies: int
    gtfs_adjacencies: int
    graph_only: tuple[tuple[str, str, str], ...]
    gtfs_only: tuple[tuple[str, str, str], ...]
    unresolved_graph_edges: tuple[tuple[str, str, str], ...]

    @property
    def compatible(self) -> bool:
        return not (self.graph_only or self.gtfs_only or self.unresolved_graph_edges)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_release_sources(data_dir: str, manifest_path: str) -> dict[str, Any]:
    """Verify that prebuild uses the reviewed ODPT snapshot byte-for-byte."""
    try:
        with open(manifest_path, encoding="utf-8") as source:
            manifest = json.load(source)
    except Exception as error:
        raise TokyoStaticCompatibilityError(
            f"Could not read Tokyo static release manifest: {manifest_path}"
        ) from error

    if not isinstance(manifest, Mapping) or manifest.get("schema") != RELEASE_MANIFEST_SCHEMA:
        raise TokyoStaticCompatibilityError(
            "Tokyo static release manifest schema mismatch: "
            f"expected={RELEASE_MANIFEST_SCHEMA!r}"
        )
    sources = manifest.get("odpt_sources")
    if not isinstance(sources, list) or not sources:
        raise TokyoStaticCompatibilityError(
            "Tokyo static release manifest has no odpt_sources"
        )

    checked = []
    for item in sources:
        if not isinstance(item, Mapping):
            raise TokyoStaticCompatibilityError(
                "Tokyo static release manifest source must be an object"
            )
        filename = item.get("filename")
        expected_sha256 = item.get("sha256")
        expected_records = item.get("records")
        if (
            not isinstance(filename, str)
            or not filename
            or os.path.basename(filename) != filename
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_sha256
            )
            or type(expected_records) is not int
            or expected_records <= 0
        ):
            raise TokyoStaticCompatibilityError(
                "Tokyo static release manifest source metadata is invalid"
            )
        path = os.path.join(data_dir, filename)
        if not os.path.isfile(path):
            raise TokyoStaticCompatibilityError(
                f"Reviewed Tokyo static input is missing: {filename}"
            )
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise TokyoStaticCompatibilityError(
                "Reviewed Tokyo static input checksum mismatch: "
                f"file={filename} expected={expected_sha256} actual={actual_sha256}"
            )
        try:
            with open(path, encoding="utf-8") as source:
                records = json.load(source)
        except Exception as error:
            raise TokyoStaticCompatibilityError(
                f"Reviewed Tokyo static input is not valid JSON: {filename}"
            ) from error
        if not isinstance(records, list) or len(records) != expected_records:
            actual_records = len(records) if isinstance(records, list) else None
            raise TokyoStaticCompatibilityError(
                "Reviewed Tokyo static input record count mismatch: "
                f"file={filename} expected={expected_records} actual={actual_records}"
            )
        checked.append(
            {
                "filename": filename,
                "sha256": actual_sha256,
                "records": len(records),
            }
        )
    return {
        "schema": manifest["schema"],
        "snapshot_id": manifest.get("snapshot_id"),
        "checked_sources": checked,
    }


def _graph_bus_adjacencies(graph, manager, repository):
    choices = TimetableChoices(
        graph,
        manager,
        day_type="weekday",
        use_realtime=False,
        bus_repository=repository,
    )
    adjacencies: set[tuple[str, str, str]] = set()
    unresolved: set[tuple[str, str, str]] = set()
    for origin, destination, edge in graph.edges(data=True):
        if edge.get("etype") != "ride" or edge.get("mode") != "bus":
            continue
        route_id = choices._bus_route(origin)
        origin_id = choices._stop_id(origin[1] if len(origin) > 1 else None)
        destination_id = choices._stop_id(
            destination[1] if len(destination) > 1 else None
        )
        if route_id is None or origin_id is None or destination_id is None:
            unresolved.add((str(route_id), str(origin_id), str(destination_id)))
        else:
            adjacencies.add((route_id, origin_id, destination_id))
    return adjacencies, unresolved


def _gtfs_bus_adjacencies(repository):
    adjacencies: set[tuple[str, str, str]] = set()
    for trip_id, rows in repository.stop_times.items():
        trip = repository.trips.get(trip_id)
        route_id = trip.get("route_id") if isinstance(trip, Mapping) else None
        if route_id is None:
            raise TokyoStaticCompatibilityError(
                f"GTFS stop sequence has no route identity: trip={trip_id!r}"
            )
        previous = None
        for _sequence, row in sorted(rows.items()):
            if not isinstance(row, (tuple, list)) or not row:
                raise TokyoStaticCompatibilityError(
                    f"GTFS stop occurrence is invalid: trip={trip_id!r}"
                )
            stop_id = row[0]
            if previous is not None:
                adjacencies.add((route_id, previous, stop_id))
            previous = stop_id
    return adjacencies


def inspect_toei_bus_graph_gtfs(graph, manager, repository):
    if not getattr(repository, "is_loaded", False):
        raise TokyoStaticCompatibilityError(
            "Toei Bus GTFS repository must be loaded before topology validation"
        )
    graph_adjacencies, unresolved = _graph_bus_adjacencies(
        graph, manager, repository
    )
    gtfs_adjacencies = _gtfs_bus_adjacencies(repository)
    return BusTopologyCompatibilityReport(
        graph_adjacencies=len(graph_adjacencies),
        gtfs_adjacencies=len(gtfs_adjacencies),
        graph_only=tuple(sorted(graph_adjacencies - gtfs_adjacencies)),
        gtfs_only=tuple(sorted(gtfs_adjacencies - graph_adjacencies)),
        unresolved_graph_edges=tuple(sorted(unresolved)),
    )


def validate_toei_bus_graph_gtfs(graph, manager, repository):
    """Require exact bidirectional adjacency agreement; never degrade silently."""
    report = inspect_toei_bus_graph_gtfs(graph, manager, repository)
    if report.compatible:
        return report

    def sample(rows):
        return list(rows[:5])

    raise TokyoStaticCompatibilityError(
        "Toei Bus ODPT topology and GTFS are incompatible: "
        f"graph_adjacencies={report.graph_adjacencies} "
        f"gtfs_adjacencies={report.gtfs_adjacencies} "
        f"graph_only={len(report.graph_only)} sample={sample(report.graph_only)!r} "
        f"gtfs_only={len(report.gtfs_only)} sample={sample(report.gtfs_only)!r} "
        f"unresolved_graph_edges={len(report.unresolved_graph_edges)} "
        f"sample={sample(report.unresolved_graph_edges)!r}"
    )

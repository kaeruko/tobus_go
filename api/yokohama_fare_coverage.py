from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from fare_policy import RideFareContext, YOKOHAMA_WELFARE_PASS_SOURCE
from transit_dataset import TransitDataset


# Internal operator IDs are explicit; they are not inferred from display names.
YOKOHAMA_FARE_FEED_OPERATORS = {
    "yokohama_bus": "yokohama_municipal_bus",
    "yokohama_subway": "yokohama_municipal_subway",
    "yokohama_rinko_bus": "kawasaki_tsurumi_rinko_bus",
    "yokohama_odakyu_bus": "odakyu_bus",
    "yokohama_tokyu_bus": "tokyu_bus",
    "yokohama_sotetsu_bus": "sotetsu_bus",
}


@dataclass(frozen=True, slots=True)
class YokohamaFareCoverage:
    dataset: TransitDataset
    operator_id: str
    route_service_kinds: Mapping[str, str]
    stop_municipalities: Mapping[str, str]
    reviewed_on: date
    # None is legacy route-only schema v1. In v2, ONLY listed trip IDs
    # may enter pass-only search; missing IDs are excluded, never inferred.
    reviewed_free_trip_uris: Mapping[str, str] | None = None

    @classmethod
    def load(cls, path: str | Path, *, dataset: TransitDataset) -> "YokohamaFareCoverage":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Yokohama fare coverage must be a JSON object")
        required = {
            "schema_version", "city", "feed_id", "feed_version", "feed_source_uri",
            "operator_id", "policy_source_uri", "reviewed_on", "routes",
            "stop_municipalities",
        }
        schema_version = raw.get("schema_version")
        if type(schema_version) is not int or schema_version not in (1, 2):
            raise ValueError("unsupported Yokohama fare coverage schema_version")
        if schema_version == 2:
            required = required | {"reviewed_free_trips"}
        if set(raw) != required:
            raise ValueError(
                "Yokohama fare coverage fields mismatch: "
                f"missing={sorted(required - set(raw))}, extra={sorted(set(raw) - required)}"
            )
        expected_operator = YOKOHAMA_FARE_FEED_OPERATORS.get(dataset.metadata.feed_id)
        if expected_operator is None:
            raise ValueError(f"unregistered Yokohama fare feed: {dataset.metadata.feed_id}")
        expected = {
            "city": "yokohama",
            "feed_id": dataset.metadata.feed_id,
            "feed_version": dataset.metadata.version,
            "feed_source_uri": dataset.metadata.source_uri,
            "operator_id": expected_operator,
            "policy_source_uri": YOKOHAMA_WELFARE_PASS_SOURCE,
        }
        for key, value in expected.items():
            if raw[key] != value:
                raise ValueError(
                    f"Yokohama fare coverage {key} mismatch: "
                    f"expected={value!r}, actual={raw[key]!r}"
                )
        if not isinstance(raw["reviewed_on"], str):
            raise ValueError("Yokohama fare reviewed_on must be YYYY-MM-DD")
        reviewed_on = date.fromisoformat(raw["reviewed_on"])
        if reviewed_on.isoformat() != raw["reviewed_on"]:
            raise ValueError("Yokohama fare reviewed_on must be zero-padded YYYY-MM-DD")
        routes = raw["routes"]
        municipalities = raw["stop_municipalities"]
        if not isinstance(routes, dict) or set(routes) != set(dataset.routes):
            raise ValueError("Yokohama fare coverage must review every route in the exact feed")
        expected_mode = "rail" if expected_operator == "yokohama_municipal_subway" else "bus"
        if any(route.mode.value != expected_mode for route in dataset.routes.values()):
            raise ValueError("Yokohama fare feed mode does not match its registered operator")
        if not isinstance(municipalities, dict) or set(municipalities) - set(dataset.stops):
            raise ValueError("Yokohama fare coverage contains invalid stop_municipalities")
        for stop_id, code in municipalities.items():
            if not isinstance(code, str) or len(code) != 5 or not code.isascii() or not code.isdigit():
                raise ValueError(f"invalid municipality code for {stop_id}: {code!r}")
        if expected_operator not in {"yokohama_municipal_bus", "yokohama_municipal_subway"}:
            if set(municipalities) != set(dataset.stops):
                raise ValueError("Yokohama private bus coverage must classify every stop municipality")
        reviewed_free_trip_uris = None
        if schema_version == 2:
            # Route-only approval cannot distinguish an ordinary trip from a
            # premium late-night trip on the same route. Only explicitly
            # reviewed trip IDs are eligible under v2. Sparse maps are valid.
            if expected_operator != "yokohama_municipal_bus":
                raise ValueError("Yokohama trip-level coverage v2 currently supports only municipal bus")
            trip_reviews = raw["reviewed_free_trips"]
            if not isinstance(trip_reviews, dict):
                raise ValueError("Yokohama reviewed_free_trips must be an ID-to-evidence-URL object")
            for trip_id, evidence_uri in trip_reviews.items():
                trip = dataset.trips.get(trip_id)
                if trip is None:
                    raise ValueError(f"Yokohama reviewed_free_trips has unknown trip: {trip_id!r}")
                if routes[trip.route_id] != "local":
                    raise ValueError(
                        f"Yokohama approved trip belongs to non-local route: "
                        f"trip={trip_id!r}, route={trip.route_id!r}"
                    )
                if not isinstance(evidence_uri, str) or evidence_uri != evidence_uri.strip():
                    raise ValueError(f"Yokohama reviewed trip needs an HTTPS evidence URI: {trip_id!r}")
                url = urlparse(evidence_uri)
                if url.scheme != "https" or not url.hostname or url.username or url.password:
                    raise ValueError(f"Yokohama reviewed trip needs an HTTPS evidence URI: {trip_id!r}")
            reviewed_free_trip_uris = dict(trip_reviews)
        # Validate each route against the same contract used for emitted ride contexts.
        stop_id = next(iter(dataset.stops))
        for route_id, kind in routes.items():
            RideFareContext(
                mode=dataset.routes[route_id].mode.value,
                feed_id=dataset.metadata.feed_id,
                operator_id=expected_operator,
                route_id=route_id,
                boarding_stop_id=stop_id,
                alighting_stop_id=stop_id,
                service_kind=kind,
            )
        return cls(
            dataset=dataset,
            operator_id=expected_operator,
            route_service_kinds=routes,
            stop_municipalities=municipalities,
            reviewed_on=reviewed_on,
            reviewed_free_trip_uris=reviewed_free_trip_uris,
        )

    def municipal_free_coverage(self) -> "YokohamaFareCoverage | None":
        """Select reviewed municipal routes before search, preserving source IDs."""
        if self.operator_id not in {"yokohama_municipal_bus", "yokohama_municipal_subway"}:
            raise ValueError(
                "Free-route filtering for private buses requires boarding/alighting-aware "
                "search and is not implemented by the municipal route filter"
            )
        local_route_ids = {
            key for key in self.dataset.routes
            if self.route_service_kinds[key] == "local"
        }
        trips = {
            key: trip for key, trip in self.dataset.trips.items()
            if trip.route_id in local_route_ids
            and (
                self.reviewed_free_trip_uris is None
                or key in self.reviewed_free_trip_uris
            )
        }
        if not trips:
            return None
        allowed_route_ids = {trip.route_id for trip in trips.values()}
        allowed_routes = {
            key: route for key, route in self.dataset.routes.items()
            if key in allowed_route_ids
        }
        if len(allowed_routes) == len(self.dataset.routes) and len(trips) == len(self.dataset.trips):
            return self
        selected = replace(
            self.dataset,
            routes=allowed_routes,
            trips=trips,
            stop_times=tuple(row for row in self.dataset.stop_times if row.trip_id in trips),
        )
        return replace(
            self,
            dataset=selected,
            route_service_kinds={key: self.route_service_kinds[key] for key in allowed_routes},
        )

    def context_for_step(self, step: dict) -> dict[str, str | None]:
        route_id = step.get("route_id")
        boarding = step.get("departureStopId")
        alighting = step.get("arrivalPoleId")
        if not isinstance(route_id, str) or route_id not in self.dataset.routes:
            raise ValueError("Yokohama fare step references an unreviewed route")
        if boarding not in self.dataset.stops or alighting not in self.dataset.stops:
            raise ValueError("Yokohama fare step references an unknown boarding/alighting stop")
        if step.get("kind") != self.dataset.routes[route_id].mode.value:
            raise ValueError("Yokohama fare step mode does not match reviewed route")
        if self.reviewed_free_trip_uris is not None:
            trip_id = step.get("trip_id")
            trip = self.dataset.trips.get(trip_id) if isinstance(trip_id, str) else None
            if (
                trip is None or trip.route_id != route_id
                or trip_id not in self.reviewed_free_trip_uris
            ):
                raise ValueError("Yokohama fare step references an unreviewed or mismatched trip")
        return {
            "feed_id": self.dataset.metadata.feed_id,
            "operator_id": self.operator_id,
            "route_id": route_id,
            "boarding_stop_id": boarding,
            "alighting_stop_id": alighting,
            "service_kind": self.route_service_kinds[route_id],
            "boarding_municipality_code": self.stop_municipalities.get(boarding),
            "alighting_municipality_code": self.stop_municipalities.get(alighting),
        }

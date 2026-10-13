from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Mapping

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
        if set(raw) != required:
            raise ValueError(
                "Yokohama fare coverage fields mismatch: "
                f"missing={sorted(required - set(raw))}, extra={sorted(set(raw) - required)}"
            )
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise ValueError("unsupported Yokohama fare coverage schema_version")
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
        )

    def municipal_free_coverage(self) -> "YokohamaFareCoverage | None":
        """Select reviewed municipal routes before search, preserving source IDs."""
        if self.operator_id not in {"yokohama_municipal_bus", "yokohama_municipal_subway"}:
            raise ValueError(
                "Free-route filtering for private buses requires boarding/alighting-aware "
                "search and is not implemented by the municipal route filter"
            )
        allowed_routes = {
            key: route for key, route in self.dataset.routes.items()
            if self.route_service_kinds[key] == "local"
        }
        if len(allowed_routes) == len(self.dataset.routes):
            return self
        trips = {
            key: trip for key, trip in self.dataset.trips.items()
            if trip.route_id in allowed_routes
        }
        if not trips:
            return None
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

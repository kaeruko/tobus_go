from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol, TypeAlias, runtime_checkable


class RouteEngineError(Exception):
    """Base class for failures exposed by the route-engine boundary."""


class RouteInputError(RouteEngineError, ValueError):
    """The route request is structurally invalid."""


class UnsupportedPreferenceError(RouteInputError):
    """The client requested an unknown route preference."""


class RouteSearchLimitError(RouteEngineError, RuntimeError):
    """A search stopped because a safety limit was reached."""


class RouteEngineUnavailableError(RouteEngineError, RuntimeError):
    """The selected city's route engine is not ready."""


class RouteContractError(RouteEngineError, RuntimeError):
    """An engine returned a result that violates the shared contract."""


class RoutePreference(str, Enum):
    FASTEST = "fastest"
    FEWEST_TRANSFERS = "fewest_transfers"
    # Tokyo historically exposes a separate comfort/cost objective. Keeping it
    # explicit avoids silently changing route ordering during this migration.
    COMFORT = "comfort"

    @property
    def api_value(self) -> str:
        if self is RoutePreference.FASTEST:
            return "time"
        if self is RoutePreference.FEWEST_TRANSFERS:
            return "fewTransfers"
        return "cost"


def normalize_route_preference(value: str | None) -> RoutePreference:
    if value in ("shortTime", "fast", "time"):
        return RoutePreference.FASTEST
    if value == "fewTransfers":
        return RoutePreference.FEWEST_TRANSFERS
    if value in (None, "", "cost"):
        return RoutePreference.COMFORT
    raise UnsupportedPreferenceError(f"unsupported route preference: {value!r}")


@dataclass(frozen=True, slots=True)
class GeoPoint:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.lat, bool)
            or isinstance(self.lon, bool)
            or not isinstance(self.lat, (int, float))
            or not isinstance(self.lon, (int, float))
        ):
            raise RouteInputError("latitude and longitude must be numbers")
        if not math.isfinite(self.lat) or not -90.0 <= self.lat <= 90.0:
            raise RouteInputError(f"latitude is out of range: {self.lat!r}")
        if not math.isfinite(self.lon) or not -180.0 <= self.lon <= 180.0:
            raise RouteInputError(f"longitude is out of range: {self.lon!r}")

    def to_list(self) -> list[float]:
        return [self.lat, self.lon]


@dataclass(frozen=True, slots=True)
class RouteSearchRequest:
    origin: GeoPoint
    destination: GeoPoint
    departure_at: datetime
    preference: RoutePreference
    limit: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.departure_at, datetime):
            raise RouteInputError("departure_at must be a datetime")
        if self.departure_at.tzinfo is None or self.departure_at.utcoffset() is None:
            raise RouteInputError("departure_at must be timezone-aware")
        if not isinstance(self.preference, RoutePreference):
            raise RouteInputError("preference must be a RoutePreference")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise RouteInputError("limit must be an integer")
        if not 1 <= self.limit <= 20:
            raise RouteInputError("limit must be between 1 and 20")


@dataclass(slots=True)
class WalkStep:
    title: str
    from_: str | None
    to: str | None
    minutes: int
    meters: int
    step_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    source_fields: frozenset[str] | None = field(default=None, repr=False)

    def to_mapping(self) -> dict[str, Any]:
        value = dict(self.extra)
        fields = self.source_fields
        core = {
            "kind": "walk",
            "title": self.title,
            "from_": self.from_,
            "to": self.to,
            "minutes": self.minutes,
            "meters": self.meters,
        }
        value.update(core if fields is None else {k: v for k, v in core.items() if k in fields})
        if self.step_id is not None:
            value["step_id"] = self.step_id
        return value


@dataclass(slots=True)
class WaitStep:
    title: str
    from_: str | None
    to: str | None
    minutes: int
    meters: int = 0
    step_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    source_fields: frozenset[str] | None = field(default=None, repr=False)

    def to_mapping(self) -> dict[str, Any]:
        value = dict(self.extra)
        fields = self.source_fields
        core = {
            "kind": "wait",
            "title": self.title,
            "from_": self.from_,
            "to": self.to,
            "minutes": self.minutes,
            "meters": self.meters,
        }
        value.update(core if fields is None else {k: v for k, v in core.items() if k in fields})
        if self.step_id is not None:
            value["step_id"] = self.step_id
        return value


@dataclass(slots=True)
class RideStep:
    mode: str
    title: str
    from_: str | None
    to: str | None
    minutes: int
    meters: int = 0
    step_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    source_fields: frozenset[str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in ("bus", "rail"):
            raise RouteContractError(f"unsupported ride mode: {self.mode!r}")

    def to_mapping(self) -> dict[str, Any]:
        value = dict(self.extra)
        fields = self.source_fields
        core = {
            "kind": self.mode,
            "title": self.title,
            "from_": self.from_,
            "to": self.to,
            "minutes": self.minutes,
            "meters": self.meters,
        }
        value.update(core if fields is None else {k: v for k, v in core.items() if k in fields})
        if self.step_id is not None:
            value["step_id"] = self.step_id
        return value


RouteStep: TypeAlias = WalkStep | WaitStep | RideStep


def _contract_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouteContractError(f"{field_name} must be an integer")
    if value < 0:
        raise RouteContractError(f"{field_name} must be >= 0")
    return value


def route_step_from_mapping(raw: Mapping[str, Any]) -> RouteStep:
    data = dict(raw)
    source_fields = frozenset(data)
    kind = data.pop("kind", None)
    title = data.pop("title", None)
    from_ = data.pop("from_", None)
    to = data.pop("to", None)
    minutes = _contract_int(data.pop("minutes", 0), "step.minutes")
    meters = _contract_int(data.pop("meters", 0), "step.meters")
    step_id = data.pop("step_id", None)
    if not isinstance(title, str):
        raise RouteContractError("step.title must be a string")
    if from_ is not None and not isinstance(from_, str):
        raise RouteContractError("step.from_ must be a string or null")
    if to is not None and not isinstance(to, str):
        raise RouteContractError("step.to must be a string or null")
    if step_id is not None and not isinstance(step_id, str):
        raise RouteContractError("step.step_id must be a string")
    if kind == "walk":
        return WalkStep(title, from_, to, minutes, meters, step_id, data, source_fields)
    if kind == "wait":
        return WaitStep(title, from_, to, minutes, meters, step_id, data, source_fields)
    if kind in ("bus", "rail"):
        return RideStep(
            kind,
            title,
            from_,
            to,
            minutes,
            meters,
            step_id,
            data,
            source_fields,
        )
    raise RouteContractError(f"unsupported route step kind: {kind!r}")


@dataclass(slots=True)
class RouteCandidate:
    id: str
    lines: list[str]
    boards: int
    transfers: int
    total_time: int
    walking_distance_meters: int
    walking_segment_count: int
    steps: list[RouteStep]
    points: list[GeoPoint]
    arrival_time: str
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RouteCandidate":
        data = dict(raw)
        if "walk_m" in data:
            raise RouteContractError(
                "legacy candidate.walk_m is not part of the route contract"
            )
        try:
            candidate_id = data.pop("id")
            lines = data.pop("lines")
            boards = data.pop("boards")
            transfers = data.pop("transfers")
            total_time = data.pop("total_time")
            walking_distance = data.pop("walking_distance_meters")
            walking_segments = data.pop("walking_segment_count")
            raw_steps = data.pop("steps")
            raw_points = data.pop("points")
            arrival_time = data.pop("arrival_time")
        except KeyError as error:
            raise RouteContractError(
                f"route candidate is missing required field: {error.args[0]}"
            ) from error

        if not isinstance(candidate_id, str) or not candidate_id:
            raise RouteContractError("candidate.id must be a non-empty string")
        if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
            raise RouteContractError("candidate.lines must be a list of strings")
        if not isinstance(raw_steps, list):
            raise RouteContractError("candidate.steps must be a list")
        if not isinstance(raw_points, list):
            raise RouteContractError("candidate.points must be a list")
        if not isinstance(arrival_time, str):
            raise RouteContractError("candidate.arrival_time must be a string")

        points: list[GeoPoint] = []
        for index, point in enumerate(raw_points):
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise RouteContractError(f"candidate.points[{index}] is invalid")
            try:
                points.append(GeoPoint(float(point[0]), float(point[1])))
            except (TypeError, ValueError, RouteInputError) as error:
                raise RouteContractError(
                    f"candidate.points[{index}] is invalid"
                ) from error

        try:
            steps = [route_step_from_mapping(step) for step in raw_steps]
        except (TypeError, ValueError) as error:
            if isinstance(error, RouteContractError):
                raise
            raise RouteContractError("candidate contains an invalid step") from error

        candidate = cls(
            id=candidate_id,
            lines=list(lines),
            boards=_contract_int(boards, "candidate.boards"),
            transfers=_contract_int(transfers, "candidate.transfers"),
            total_time=_contract_int(total_time, "candidate.total_time"),
            walking_distance_meters=_contract_int(
                walking_distance, "candidate.walking_distance_meters"
            ),
            walking_segment_count=_contract_int(
                walking_segments, "candidate.walking_segment_count"
            ),
            steps=steps,
            points=points,
            arrival_time=arrival_time,
            extra=data,
        )
        validate_route_candidate(candidate)
        return candidate

    def to_mapping(self) -> dict[str, Any]:
        value = dict(self.extra)
        value.update(
            {
                "id": self.id,
                "lines": list(self.lines),
                "boards": self.boards,
                "transfers": self.transfers,
                "total_time": self.total_time,
                "walking_distance_meters": self.walking_distance_meters,
                "walking_segment_count": self.walking_segment_count,
                "steps": [step.to_mapping() for step in self.steps],
                "points": [point.to_list() for point in self.points],
                "arrival_time": self.arrival_time,
            }
        )
        return value


@dataclass(slots=True)
class RouteSearchResult:
    candidates: list[RouteCandidate]
    meta: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


def validate_route_candidate(candidate: RouteCandidate) -> None:
    if not isinstance(candidate.id, str) or not candidate.id:
        raise RouteContractError("candidate.id must be a non-empty string")
    if not isinstance(candidate.lines, list) or not all(
        isinstance(line, str) for line in candidate.lines
    ):
        raise RouteContractError("candidate.lines must be a list of strings")
    _contract_int(candidate.boards, "candidate.boards")
    _contract_int(candidate.transfers, "candidate.transfers")
    _contract_int(candidate.total_time, "candidate.total_time")
    _contract_int(
        candidate.walking_distance_meters,
        "candidate.walking_distance_meters",
    )
    _contract_int(
        candidate.walking_segment_count,
        "candidate.walking_segment_count",
    )
    if not isinstance(candidate.arrival_time, str):
        raise RouteContractError("candidate.arrival_time must be a string")
    if "walk_m" in candidate.extra:
        raise RouteContractError(
            "legacy candidate.walk_m is not part of the route contract"
        )
    for step in candidate.steps:
        if not isinstance(step, (WalkStep, WaitStep, RideStep)):
            raise RouteContractError("candidate.steps contains an unknown step type")
        _contract_int(step.minutes, "step.minutes")
        _contract_int(step.meters, "step.meters")
    walk_steps = [step for step in candidate.steps if isinstance(step, WalkStep)]
    walk_distance = sum(step.meters for step in walk_steps)
    if candidate.walking_distance_meters != walk_distance:
        raise RouteContractError(
            "walking_distance_meters does not equal the sum of walk step meters: "
            f"candidate={candidate.walking_distance_meters}, steps={walk_distance}"
        )
    if candidate.walking_segment_count != len(walk_steps):
        raise RouteContractError(
            "walking_segment_count does not equal the number of walk steps: "
            f"candidate={candidate.walking_segment_count}, steps={len(walk_steps)}"
        )
    expected_transfers = max(0, candidate.boards - 1)
    if candidate.transfers != expected_transfers:
        raise RouteContractError(
            "transfers does not equal max(0, boards - 1): "
            f"candidate={candidate.transfers}, expected={expected_transfers}"
        )


def validate_route_result(result: RouteSearchResult) -> None:
    if not isinstance(result, RouteSearchResult):
        raise RouteContractError("route engine must return RouteSearchResult")
    if not isinstance(result.candidates, list):
        raise RouteContractError("route result candidates must be a list")
    for candidate in result.candidates:
        if not isinstance(candidate, RouteCandidate):
            raise RouteContractError(
                "route result candidates must contain RouteCandidate values"
            )
        validate_route_candidate(candidate)


def serialize_route_candidate(candidate: RouteCandidate) -> dict[str, Any]:
    validate_route_candidate(candidate)
    return candidate.to_mapping()


def serialize_route_result(result: RouteSearchResult) -> dict[str, Any]:
    validate_route_result(result)
    payload = dict(result.extra)
    payload["candidates"] = [
        serialize_route_candidate(candidate) for candidate in result.candidates
    ]
    payload["meta"] = dict(result.meta)
    return payload


@runtime_checkable
class RouteEngine(Protocol):
    def search(self, request: RouteSearchRequest) -> RouteSearchResult:
        ...

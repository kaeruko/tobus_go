"""Common Tokyo Metro/Toei transfer policy derived from official ODPT links.

ODPT ``connectingStation`` establishes topology.  It does not publish a
walked distance or a universal minimum transfer time.  This module therefore
keeps official possibility, app scheduling allowance, physical distance and
search-resource accounting as separate facts.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from urllib.parse import urlparse

from reviewed_walk_time import validate_reviewed_walk_timing


LEGACY_SCHEMA = "tokyo_metro_reviewed_transfer/v1"
POLICY_SCHEMA = "tokyo_metro_transfer_policy/v2"
MODEL_VERSION = "odpt_same_station_conservative/v1"
METRO_PREFIX = "odpt.Station:TokyoMetro."
TOEI_SUBWAY_PREFIXES = (
    "odpt.Station:Toei.Asakusa.",
    "odpt.Station:Toei.Mita.",
    "odpt.Station:Toei.Shinjuku.",
    "odpt.Station:Toei.Oedo.",
)
ALLOWED_PATH_CLASSES = frozenset((
    "same_platform", "same_station", "out_of_gate", "linked_station",
))
EVIDENCE_HOSTS = frozenset((
    "tokyometro.jp", "www.tokyometro.jp",
    "kotsu.metro.tokyo.jp", "www.kotsu.metro.tokyo.jp",
    "odpt.org", "www.odpt.org", "developer.odpt.org", "ckan.odpt.org",
))


@dataclass(frozen=True, slots=True)
class TransferPolicy:
    schema: str
    automatic_enabled: bool
    automatic_minutes: int
    automatic_resource_meters: float
    overrides: dict[frozenset[str], dict]
    exceptions: dict[frozenset[str], dict]


def station_slug(station_id: str) -> str:
    if not isinstance(station_id, str) or not station_id.startswith("odpt.Station:"):
        raise ValueError(f"invalid ODPT station ID: {station_id!r}")
    parts = station_id.rsplit(".", 1)
    if len(parts) != 2 or not parts[1]:
        raise ValueError(f"invalid ODPT station ID: {station_id!r}")
    return parts[1]


def relevant_connection(station_id: str) -> bool:
    return station_id.startswith((METRO_PREFIX, *TOEI_SUBWAY_PREFIXES))


def automatic_path_class(first: str, second: str) -> str | None:
    """Classify only identities the common model can justify.

    Equal official ODPT station slugs plus an explicit connectingStation
    relation identify a same-station interchange.  Different slugs can be a
    valid linked-station transfer, but need an override because the common
    input has no walked-path evidence to prove the existing 600 m constraint.
    """
    return "same_station" if station_slug(first) == station_slug(second) else None


def _pair(item: dict, description: str) -> frozenset[str]:
    first, second = item.get("from_station_id"), item.get("to_station_id")
    if not all(isinstance(value, str) and relevant_connection(value)
               for value in (first, second)) or first == second:
        raise ValueError(f"{description} has invalid station IDs")
    return frozenset((first, second))


def _urls(value, description: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{description} lacks official evidence")
    result = []
    for url in value:
        parsed = urlparse(url) if isinstance(url, str) else None
        if (parsed is None or parsed.scheme != "https"
                or parsed.hostname not in EVIDENCE_HOSTS):
            raise ValueError(f"{description} lacks official evidence")
        result.append(url)
    return tuple(result)


def _clock(value: str, description: str) -> int:
    if not isinstance(value, str) or value.count(":") != 1:
        raise ValueError(f"{description} has invalid clock")
    try:
        hour, minute = map(int, value.split(":"))
    except ValueError as error:
        raise ValueError(f"{description} has invalid clock") from error
    if not 0 <= hour <= 47 or not 0 <= minute <= 59:
        raise ValueError(f"{description} has invalid clock")
    return hour * 60 + minute


def _windows(value, description: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{description} requires at least one availability window")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            raise ValueError(f"{description} window #{index} has invalid fields")
        start = _clock(item["start"], description)
        end = _clock(item["end"], description)
        if end <= start:
            raise ValueError(f"{description} availability window must be increasing")
        result.append((start, end))
    return tuple(result)


def _overrides(items) -> dict[frozenset[str], dict]:
    if not isinstance(items, list):
        raise ValueError("Tokyo Metro transfer overrides must be a list")
    result = {}
    required = {
        "from_station_id", "to_station_id", "path_class", "minimum_minutes",
        "walking_distance_meters", "evidence_urls", "reviewed_at",
    }
    for index, item in enumerate(items):
        description = f"Tokyo Metro transfer override #{index}"
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"{description} has invalid fields")
        pair = _pair(item, description)
        if pair in result:
            raise ValueError(f"{description} duplicates a station pair")
        path_class = item["path_class"]
        if path_class not in ALLOWED_PATH_CLASSES:
            raise ValueError(f"{description} has invalid path class")
        minutes, meters = item["minimum_minutes"], item["walking_distance_meters"]
        if type(minutes) is not int or minutes < 1:
            raise ValueError(f"{description} has invalid minutes")
        if type(meters) is not int or not 0 < meters <= 600:
            raise ValueError(f"{description} has invalid walking distance")
        validate_reviewed_walk_timing(meters, minutes)
        try:
            reviewed_at = dt.date.fromisoformat(item["reviewed_at"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{description} has invalid review date") from error
        result[pair] = {
            "path_class": path_class,
            "minutes": minutes,
            "meters": float(meters),
            "evidence_urls": _urls(item["evidence_urls"], description),
            "reviewed_at": reviewed_at.isoformat(),
        }
    return result


def _legacy_overrides(items) -> dict[frozenset[str], dict]:
    upgraded = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Tokyo Metro legacy reviewed transfer must be an object")
        upgraded.append({**item, "path_class": "linked_station"})
    return _overrides(upgraded)


def _exceptions(items) -> dict[frozenset[str], dict]:
    if not isinstance(items, list):
        raise ValueError("Tokyo Metro transfer exceptions must be a list")
    result = {}
    required = {
        "from_station_id", "to_station_id", "available_windows",
        "evidence_urls", "reason",
    }
    for index, item in enumerate(items):
        description = f"Tokyo Metro transfer exception #{index}"
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"{description} has invalid fields")
        pair = _pair(item, description)
        if pair in result:
            raise ValueError(f"{description} duplicates a station pair")
        reason = item["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{description} requires a reason")
        result[pair] = {
            "available_windows": _windows(item["available_windows"], description),
            "evidence_urls": _urls(item["evidence_urls"], description),
            "reason": reason.strip(),
        }
    return result


def load_transfer_policy(payload: object) -> TransferPolicy:
    if not isinstance(payload, dict):
        raise ValueError("Tokyo Metro transfer policy has an invalid envelope")
    schema = payload.get("schema")
    if schema == LEGACY_SCHEMA:
        if set(payload) != {"schema", "transfers"}:
            raise ValueError("Tokyo Metro reviewed transfer manifest has an invalid envelope")
        return TransferPolicy(
            schema=schema, automatic_enabled=False, automatic_minutes=0,
            automatic_resource_meters=0.0,
            overrides=_legacy_overrides(payload["transfers"]), exceptions={},
        )
    if schema != POLICY_SCHEMA or set(payload) != {
        "schema", "automatic_model", "overrides", "exceptions"
    }:
        raise ValueError("Tokyo Metro transfer policy has an unsupported schema")
    model = payload["automatic_model"]
    required_model = {
        "version", "eligible_relation", "unmatched_relation_policy",
        "minimum_minutes", "walk_resource_meters", "distance_basis",
        "time_basis", "official_minimum",
    }
    if not isinstance(model, dict) or set(model) != required_model:
        raise ValueError("Tokyo Metro automatic transfer model has invalid fields")
    if (model["version"] != MODEL_VERSION
            or model["eligible_relation"] != "same_station_slug"
            or model["unmatched_relation_policy"] != "disabled_requires_override"
            or model["distance_basis"] != "unknown_consumes_full_segment_limit"
            or model["time_basis"] != "app_conservative_allowance"
            or model["official_minimum"] is not False):
        raise ValueError("Tokyo Metro automatic transfer model contract is unsupported")
    minutes, resource = model["minimum_minutes"], model["walk_resource_meters"]
    if type(minutes) is not int or minutes < 1:
        raise ValueError("Tokyo Metro automatic transfer minutes are invalid")
    if (type(resource) not in (int, float) or not math.isfinite(resource)
            or not 0 < resource <= 600):
        raise ValueError("Tokyo Metro automatic walking resource is invalid")
    if minutes < math.ceil(resource / 80):
        raise ValueError("Tokyo Metro automatic allowance is shorter than its resource floor")
    overrides = _overrides(payload["overrides"])
    exceptions = _exceptions(payload["exceptions"])
    # Exceptions may also target an automatic same-station pair; its official
    # relation is validated when the graph is built, not while parsing JSON.
    return TransferPolicy(
        schema=schema, automatic_enabled=True, automatic_minutes=minutes,
        automatic_resource_meters=float(resource), overrides=overrides,
        exceptions=exceptions,
    )

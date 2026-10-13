from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol


class SettlementType(str, Enum):
    NORMAL = "normal"
    DISCOUNT = "discount"
    FREE_PASS = "free_pass"
    REIMBURSEMENT = "reimbursement"


@dataclass(frozen=True, slots=True)
class RideFareContext:
    """Verified route identity and boarding/alighting context for one ride."""

    mode: str
    feed_id: str
    operator_id: str
    route_id: str
    boarding_stop_id: str
    alighting_stop_id: str
    service_kind: str
    boarding_municipality_code: str | None = None
    alighting_municipality_code: str | None = None
    normal_fare_yen: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"bus", "rail"}:
            raise ValueError(f"unsupported fare ride mode: {self.mode!r}")
        if not isinstance(self.feed_id, str) or not self.feed_id or ":" in self.feed_id:
            raise ValueError(f"invalid fare feed_id: {self.feed_id!r}")
        if self.feed_id.strip() != self.feed_id:
            raise ValueError(f"invalid fare feed_id: {self.feed_id!r}")
        if not isinstance(self.operator_id, str) or not self.operator_id:
            raise ValueError("fare operator_id is required")
        if self.operator_id.strip() != self.operator_id:
            raise ValueError("fare operator_id must not have surrounding whitespace")
        prefix = f"{self.feed_id}:"
        for name in ("route_id", "boarding_stop_id", "alighting_stop_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.startswith(prefix) or value == prefix:
                raise ValueError(f"fare {name} must belong to feed {self.feed_id!r}")
        if self.service_kind not in {
            "local", "airport", "highway", "midnight_express", "sightseeing"
        }:
            raise ValueError(f"unreviewed fare service_kind: {self.service_kind!r}")
        for name in ("boarding_municipality_code", "alighting_municipality_code"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or re.fullmatch(r"[0-9]{5}", value) is None
            ):
                raise ValueError(f"fare {name} must be a five-digit city code")
        if self.normal_fare_yen is not None and (
            isinstance(self.normal_fare_yen, bool)
            or not isinstance(self.normal_fare_yen, int)
            or self.normal_fare_yen < 0
        ):
            raise ValueError("ride normal_fare_yen must be an integer >= 0")

    @classmethod
    def from_step(cls, step: dict) -> "RideFareContext":
        value = step.get("fare_context")
        if not isinstance(value, dict):
            raise ValueError("Yokohama welfare pass requires verified fare_context for each ride")
        required = (
            "feed_id", "operator_id", "route_id", "boarding_stop_id",
            "alighting_stop_id", "service_kind",
        )
        for key in required:
            if key not in value:
                raise ValueError(f"Yokohama fare_context is missing {key}")
        if value["route_id"] != step.get("route_id"):
            raise ValueError("Yokohama fare_context route_id does not match ride")
        if value["boarding_stop_id"] != step.get("departureStopId"):
            raise ValueError("Yokohama fare_context boarding stop does not match ride")
        if value["alighting_stop_id"] != step.get("arrivalPoleId"):
            raise ValueError("Yokohama fare_context alighting stop does not match ride")
        return cls(
            mode=step["kind"],
            **{key: value[key] for key in required},
            boarding_municipality_code=value.get("boarding_municipality_code"),
            alighting_municipality_code=value.get("alighting_municipality_code"),
            normal_fare_yen=step.get("fare_yen"),
        )


@dataclass(frozen=True, slots=True)
class FarePolicyContext:
    city_key: str
    normal_fare_yen: int | None
    ride_modes: tuple[str, ...]
    rides: tuple[RideFareContext, ...] = ()

    def __post_init__(self) -> None:
        if self.city_key not in {"tokyo", "nagoya", "sendai", "yokohama"}:
            raise ValueError(f"unsupported city_key: {self.city_key!r}")
        if self.normal_fare_yen is not None and self.normal_fare_yen < 0:
            raise ValueError("normal_fare_yen must be >= 0")
        for mode in self.ride_modes:
            if mode not in {"bus", "rail"}:
                raise ValueError(f"unsupported ride mode: {mode!r}")
        if self.rides and tuple(ride.mode for ride in self.rides) != self.ride_modes:
            raise ValueError("fare ride contexts do not match ride_modes")


@dataclass(frozen=True, slots=True)
class FareQuote:
    normal_fare_yen: int | None
    pay_now_yen: int | None
    effective_fare_yen: int | None
    policy_id: str
    settlement_type: SettlementType
    status: str = "available"
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id is required")
        if self.status not in {"available", "unavailable"}:
            raise ValueError(f"invalid fare quote status: {self.status!r}")
        for name, value in (
            ("normal_fare_yen", self.normal_fare_yen),
            ("pay_now_yen", self.pay_now_yen),
            ("effective_fare_yen", self.effective_fare_yen),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.status == "available" and self.unavailable_reason is not None:
            raise ValueError("available fare quote cannot have unavailable_reason")
        if self.status == "unavailable" and not self.unavailable_reason:
            raise ValueError("unavailable fare quote requires unavailable_reason")

    def to_api_dict(self) -> dict[str, object | None]:
        return {
            "normalFareYen": self.normal_fare_yen,
            "payNowYen": self.pay_now_yen,
            "effectiveFareYen": self.effective_fare_yen,
            "policyId": self.policy_id,
            "settlementType": self.settlement_type.value,
            "status": self.status,
            "unavailableReason": self.unavailable_reason,
        }


class FarePolicy(Protocol):
    policy_id: str
    city_key: str
    display_name: str
    settlement_type: SettlementType
    source_uri: str | None

    def apply(self, context: FarePolicyContext) -> FareQuote: ...


@dataclass(frozen=True, slots=True)
class NormalFarePolicy:
    city_key: str
    policy_id: str = "normal"
    display_name: str = "通常運賃"
    settlement_type: SettlementType = SettlementType.NORMAL
    source_uri: str | None = None

    def apply(self, context: FarePolicyContext) -> FareQuote:
        _require_city(self.city_key, context)
        if context.normal_fare_yen is None:
            return FareQuote(
                normal_fare_yen=None,
                pay_now_yen=None,
                effective_fare_yen=None,
                policy_id=self.policy_id,
                settlement_type=self.settlement_type,
                status="unavailable",
                unavailable_reason="normal_fare_not_calculable_from_current_route_data",
            )
        return FareQuote(
            normal_fare_yen=context.normal_fare_yen,
            pay_now_yen=context.normal_fare_yen,
            effective_fare_yen=context.normal_fare_yen,
            policy_id=self.policy_id,
            settlement_type=self.settlement_type,
        )


@dataclass(frozen=True, slots=True)
class FreePassFarePolicy:
    city_key: str
    policy_id: str
    display_name: str
    covered_modes: frozenset[str]
    source_uri: str
    settlement_type: SettlementType = SettlementType.FREE_PASS

    def apply(self, context: FarePolicyContext) -> FareQuote:
        _require_city(self.city_key, context)
        unsupported = set(context.ride_modes) - self.covered_modes
        if unsupported:
            raise ValueError(
                f"fare policy {self.policy_id} does not cover modes: "
                f"{sorted(unsupported)}"
            )
        return FareQuote(
            normal_fare_yen=context.normal_fare_yen,
            pay_now_yen=0,
            effective_fare_yen=0,
            policy_id=self.policy_id,
            settlement_type=self.settlement_type,
        )


YOKOHAMA_WELFARE_PASS_SOURCE = (
    "https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/"
    "fukushi/annai/gaishutsu/kotsu/fukushi-jyosyaken/ticket.html"
)
YOKOHAMA_SENIOR_PASS_SOURCE = (
    "https://www.city.yokohama.lg.jp/kenko-iryo-fukushi/fukushi-kaigo/"
    "koreisha-kaigo/kaigoyobo-kenkoudukuri-ikigai/"
    "ikigai-shakaisanka/keirou.html"
)
YOKOHAMA_CITY_CODE = "14100"
YOKOHAMA_PRIVATE_BUS_OPERATORS = frozenset({
    "odakyu_bus", "kanachu", "enoden_bus", "fujiexpress",
    "kawasaki_tsurumi_rinko_bus", "keikyu_bus", "sotetsu_bus",
    "daishinto", "tokyu_bus", "yokohama_kotsu_kaihatsu",
})


def yokohama_welfare_pass_covers(ride: RideFareContext) -> bool:
    """Apply reviewed operator/route/boarding rules, never the mode alone."""
    if ride.operator_id == "yokohama_municipal_subway":
        if ride.mode != "rail":
            raise ValueError("Yokohama municipal subway fare context must be rail")
        return ride.service_kind == "local"
    if ride.operator_id == "yokohama_seaside_line":
        if ride.mode != "rail":
            raise ValueError("Yokohama Seaside Line fare context must be rail")
        return ride.service_kind == "local"
    if ride.operator_id == "yokohama_municipal_bus":
        if ride.mode != "bus":
            raise ValueError("Yokohama municipal bus fare context must be bus")
        return ride.service_kind == "local"
    if ride.operator_id not in YOKOHAMA_PRIVATE_BUS_OPERATORS:
        return False
    if ride.mode != "bus":
        raise ValueError("Yokohama private bus fare context must be bus")
    if ride.service_kind != "local":
        return False
    if ride.boarding_municipality_code is None or ride.alighting_municipality_code is None:
        raise ValueError("Yokohama private bus fare requires both stop municipality codes")
    return YOKOHAMA_CITY_CODE in {
        ride.boarding_municipality_code, ride.alighting_municipality_code,
    }


def yokohama_senior_pass_covers(ride: RideFareContext) -> bool:
    """Until route-level city-stop coverage is reviewed, only municipal rides are certified."""
    if ride.operator_id in {
        "yokohama_municipal_bus", "yokohama_municipal_subway",
        "yokohama_seaside_line",
    }:
        return yokohama_welfare_pass_covers(ride)
    # Senior private-bus rules require route-level data, not just endpoint codes.
    return False


@dataclass(frozen=True, slots=True)
class YokohamaWelfarePassFarePolicy:
    city_key: str = "yokohama"
    policy_id: str = "yokohama_welfare_special_pass"
    display_name: str = "横浜市 福祉特別乗車券（福祉パス）"
    source_uri: str = YOKOHAMA_WELFARE_PASS_SOURCE
    settlement_type: SettlementType = SettlementType.FREE_PASS

    def apply(self, context: FarePolicyContext) -> FareQuote:
        return _apply_yokohama_pass(self, context, yokohama_welfare_pass_covers)


@dataclass(frozen=True, slots=True)
class YokohamaSeniorPassFarePolicy:
    city_key: str = "yokohama"
    policy_id: str = "yokohama_senior_special_pass"
    display_name: str = "横浜市 敬老特別乗車証（敬老パス）"
    source_uri: str = YOKOHAMA_SENIOR_PASS_SOURCE
    settlement_type: SettlementType = SettlementType.FREE_PASS

    def apply(self, context: FarePolicyContext) -> FareQuote:
        return _apply_yokohama_pass(self, context, yokohama_senior_pass_covers)


def _apply_yokohama_pass(policy, context: FarePolicyContext, covers) -> FareQuote:
    _require_city(policy.city_key, context)
    if len(context.rides) != len(context.ride_modes):
        raise ValueError("Yokohama pass requires verified ride contexts")
    uncovered = [ride for ride in context.rides if not covers(ride)]
    if not uncovered:
        pay_now = 0
    elif len(uncovered) == len(context.rides) and context.normal_fare_yen is not None:
        pay_now = context.normal_fare_yen
    elif all(ride.normal_fare_yen is not None for ride in uncovered):
        pay_now = sum(ride.normal_fare_yen for ride in uncovered)
    else:
        return FareQuote(
            normal_fare_yen=context.normal_fare_yen,
            pay_now_yen=None,
            effective_fare_yen=None,
            policy_id=policy.policy_id,
            settlement_type=policy.settlement_type,
            status="unavailable",
            unavailable_reason="normal_fare_required_for_noncovered_segment",
        )
    return FareQuote(
        normal_fare_yen=context.normal_fare_yen,
        pay_now_yen=pay_now,
        effective_fare_yen=pay_now,
        policy_id=policy.policy_id,
        settlement_type=policy.settlement_type,
    )


@dataclass(frozen=True, slots=True)
class PercentageDiscountFarePolicy:
    city_key: str
    policy_id: str
    display_name: str
    numerator: int
    denominator: int
    source_uri: str | None = None
    settlement_type: SettlementType = SettlementType.DISCOUNT

    def __post_init__(self) -> None:
        if self.numerator < 0 or self.denominator <= 0:
            raise ValueError("discount ratio must be non-negative with denominator > 0")
        if self.numerator > self.denominator:
            raise ValueError("discount ratio cannot exceed normal fare")

    def apply(self, context: FarePolicyContext) -> FareQuote:
        _require_city(self.city_key, context)
        if context.normal_fare_yen is None:
            return FareQuote(
                normal_fare_yen=None,
                pay_now_yen=None,
                effective_fare_yen=None,
                policy_id=self.policy_id,
                settlement_type=self.settlement_type,
                status="unavailable",
                unavailable_reason="normal_fare_required_for_discount",
            )
        discounted = context.normal_fare_yen * self.numerator // self.denominator
        return FareQuote(
            normal_fare_yen=context.normal_fare_yen,
            pay_now_yen=discounted,
            effective_fare_yen=discounted,
            policy_id=self.policy_id,
            settlement_type=self.settlement_type,
        )


@dataclass(frozen=True, slots=True)
class ReimbursementFarePolicy:
    city_key: str
    policy_id: str
    display_name: str
    source_uri: str
    settlement_type: SettlementType = SettlementType.REIMBURSEMENT

    def apply(self, context: FarePolicyContext) -> FareQuote:
        _require_city(self.city_key, context)
        if context.normal_fare_yen is None:
            return FareQuote(
                normal_fare_yen=None,
                pay_now_yen=None,
                effective_fare_yen=0,
                policy_id=self.policy_id,
                settlement_type=self.settlement_type,
                status="unavailable",
                unavailable_reason="normal_fare_required_for_reimbursement_pay_now",
            )
        return FareQuote(
            normal_fare_yen=context.normal_fare_yen,
            pay_now_yen=context.normal_fare_yen,
            effective_fare_yen=0,
            policy_id=self.policy_id,
            settlement_type=self.settlement_type,
        )


def _require_city(expected: str, context: FarePolicyContext) -> None:
    if context.city_key != expected:
        raise ValueError(
            f"fare policy city mismatch: expected={expected}, actual={context.city_key}"
        )


TOKYO_TOEI_PASS_SOURCE = (
    "https://www.fukushi.metro.tokyo.lg.jp/shougai/nichijo/jousyasyo"
)
NAGOYA_WELFARE_PASS_SOURCE = (
    "https://www.city.nagoya.jp/kenkofukushi/shougaisha/1016573/1016578.html"
)


_POLICY_REGISTRY: dict[str, dict[str, FarePolicy]] = {
    "tokyo": {
        "normal": NormalFarePolicy(city_key="tokyo"),
        "tokyo_toei_transport_pass": FreePassFarePolicy(
            city_key="tokyo",
            policy_id="tokyo_toei_transport_pass",
            display_name="東京都 精神障害者都営交通乗車証",
            covered_modes=frozenset({"bus", "rail"}),
            source_uri=TOKYO_TOEI_PASS_SOURCE,
        ),
    },
    "nagoya": {
        "normal": NormalFarePolicy(city_key="nagoya"),
        "nagoya_welfare_special_pass": FreePassFarePolicy(
            city_key="nagoya",
            policy_id="nagoya_welfare_special_pass",
            display_name="名古屋市 福祉特別乗車券（無料乗車区間）",
            covered_modes=frozenset({"bus", "rail"}),
            source_uri=NAGOYA_WELFARE_PASS_SOURCE,
        ),
    },
    "sendai": {
        "normal": NormalFarePolicy(city_key="sendai"),
    },
    "yokohama": {
        "yokohama_welfare_special_pass": YokohamaWelfarePassFarePolicy(),
        "yokohama_senior_special_pass": YokohamaSeniorPassFarePolicy(),
    },
}


def list_fare_policies(city_key: str) -> tuple[FarePolicy, ...]:
    policies = _POLICY_REGISTRY.get(city_key)
    if policies is None:
        raise ValueError(f"fare policies are not configured for city: {city_key!r}")
    return tuple(policies.values())


def fare_policy_api_options(city_key: str) -> list[dict[str, str | None]]:
    return [
        {
            "policyId": policy.policy_id,
            "displayName": policy.display_name,
            "settlementType": policy.settlement_type.value,
            "sourceUri": policy.source_uri,
        }
        for policy in list_fare_policies(city_key)
    ]


def get_fare_policy(city_key: str, policy_id: str) -> FarePolicy:
    if not policy_id or policy_id.strip() != policy_id:
        raise ValueError(f"invalid fare policy id: {policy_id!r}")
    policies = _POLICY_REGISTRY.get(city_key)
    if policies is None:
        raise ValueError(f"fare policies are not configured for city: {city_key!r}")
    policy = policies.get(policy_id)
    if policy is None:
        raise ValueError(
            f"unsupported fare policy for {city_key}: {policy_id!r}; "
            f"expected one of {sorted(policies)}"
        )
    return policy


def evaluate_candidate_fare(
    *,
    city_key: str,
    candidate: dict,
    policy_id: str,
    normal_fare_yen: int | None,
) -> FareQuote:
    steps = candidate.get("steps")
    if not isinstance(steps, list):
        raise ValueError("candidate is missing steps list")
    ride_modes: list[str] = []
    rides: list[RideFareContext] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("candidate step must be an object")
        kind = step.get("kind")
        if kind in {"bus", "rail"}:
            ride_modes.append(kind)
            if city_key == "yokohama" and policy_id in {
                "yokohama_welfare_special_pass", "yokohama_senior_special_pass",
            }:
                rides.append(RideFareContext.from_step(step))
    context = FarePolicyContext(
        city_key=city_key,
        normal_fare_yen=normal_fare_yen,
        ride_modes=tuple(ride_modes),
        rides=tuple(rides),
    )
    return get_fare_policy(city_key, policy_id).apply(context)


def _normal_fare_for_candidate(city_key: str, candidate: dict) -> int | None:
    steps = candidate.get("steps")
    if not isinstance(steps, list):
        raise ValueError("candidate is missing steps list")

    if city_key == "nagoya":
        total = 0
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("candidate step must be an object")
            kind = step.get("kind")
            if kind in {"walk", "wait"}:
                continue
            if kind != "bus":
                raise ValueError(
                    f"Nagoya city-bus fare calculator received unsupported mode: {kind!r}"
                )
            step["fare_yen"] = 210
            total += 210
        return total

    if city_key in {"tokyo", "sendai", "yokohama"}:
        # Tokyo can mix flat-fare buses with distance-based subway rides, while
        # Sendai and Yokohama do not yet provide an exact base-fare adapter here.
        # Do not infer money from geometry, route count, or a generalized cost score.
        # If an adapter provides exact per-step fare_yen values, summing them is
        # safe without changing the policy layer.
        ride_steps = []
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("candidate step must be an object")
            if step.get("kind") in {"bus", "rail"}:
                ride_steps.append(step)
        if not ride_steps:
            return 0
        fares = [step.get("fare_yen") for step in ride_steps]
        if any(not isinstance(value, int) or value < 0 for value in fares):
            return None
        return sum(fares)

    raise ValueError(f"normal fare calculator is not configured for city: {city_key!r}")


def decorate_route_result_with_fare(
    *, city_key: str, result: dict, policy_id: str
) -> dict:
    if not isinstance(result, dict):
        raise ValueError("route result must be an object")
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("route result is missing candidates list")
    get_fare_policy(city_key, policy_id)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("route candidate must be an object")
        normal_fare_yen = _normal_fare_for_candidate(city_key, candidate)
        candidate["fare"] = evaluate_candidate_fare(
            city_key=city_key,
            candidate=candidate,
            policy_id=policy_id,
            normal_fare_yen=normal_fare_yen,
        ).to_api_dict()
    return result

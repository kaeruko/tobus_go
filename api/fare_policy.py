from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class SettlementType(str, Enum):
    NORMAL = "normal"
    DISCOUNT = "discount"
    FREE_PASS = "free_pass"
    REIMBURSEMENT = "reimbursement"


@dataclass(frozen=True, slots=True)
class FarePolicyContext:
    city_key: str
    normal_fare_yen: int | None
    ride_modes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.city_key not in {"tokyo", "nagoya", "sendai"}:
            raise ValueError(f"unsupported city_key: {self.city_key!r}")
        if self.normal_fare_yen is not None and self.normal_fare_yen < 0:
            raise ValueError("normal_fare_yen must be >= 0")
        for mode in self.ride_modes:
            if mode not in {"bus", "rail"}:
                raise ValueError(f"unsupported ride mode: {mode!r}")


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
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("candidate step must be an object")
        kind = step.get("kind")
        if kind in {"bus", "rail"}:
            ride_modes.append(kind)
    context = FarePolicyContext(
        city_key=city_key,
        normal_fare_yen=normal_fare_yen,
        ride_modes=tuple(ride_modes),
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

    if city_key == "tokyo":
        # Tokyo candidates can mix flat-fare buses with distance-based subway
        # rides. Do not infer a normal fare from geometry or a comfort score.
        # If a future adapter provides exact per-step fare_yen values, summing
        # them here becomes safe without changing the policy layer.
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

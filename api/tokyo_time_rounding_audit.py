"""Exact error-budget checks; not a proof of an unexpanded suffix step bound.

This opt-in auditor reads the existing guard. It never changes an arrival,
coefficient, priority, provider or runtime selection. Fractions below represent
stored binary64 values exactly, rather than reproducing the guard's helpers.
"""
from __future__ import annotations

from fractions import Fraction
import math
import struct

from route_engine import RouteContractError
from tokyo_time_rounding import TimeRoundingGuard


def float_bits(value):
    if type(value) is not float or not math.isfinite(value):
        raise RouteContractError("audit requires a finite binary64 value")
    return struct.pack(">d", value)


def _exact(value):
    float_bits(value)
    return Fraction.from_float(value)


def verify_guard_coefficients(guard, *, start_minute, deadline,
                              max_forward_steps, max_reverse_steps,
                              max_edge_minutes):
    """Check upward enclosures against rational arithmetic, independently.

    The result is conditional on a suffix having at most max_forward_steps
    transitions. max_visited only bounds the parents of a returnable path;
    it does not itself bound every hypothetical, unexpanded legal suffix.
    """
    if (type(guard) is not TimeRoundingGuard or not guard.report["enabled"]
            or not guard._enabled):
        reason = getattr(guard, "report", {}).get("disabled_reason", "wrong_guard_type")
        raise RouteContractError("rounding guard disabled: reason=" + str(reason))
    if (type(max_forward_steps) is not int or max_forward_steps < 0
            or type(max_reverse_steps) is not int or max_reverse_steps < 1):
        raise RouteContractError("rounding audit requires explicit integer step bounds")
    start, upper, weight = float(start_minute), float(deadline), float(max_edge_minutes)
    if not (0 <= start <= upper and 0 <= weight):
        raise RouteContractError("rounding audit clock/weight domain is invalid")
    expected = {
        "start_minute": start, "deadline": upper, "max_edge_minutes": weight,
    }
    for name, value in expected.items():
        if float_bits(guard.report[name]) != float_bits(value):
            raise RouteContractError("rounding guard parameter differs: field=" + name)
    if (guard.report["max_forward_steps"] != max_forward_steps
            or guard.report["max_reverse_steps"] != max_reverse_steps):
        raise RouteContractError("rounding guard step bounds differ")
    nr = Fraction(max_reverse_steps)
    product = nr / 2**53
    if product >= 1:
        raise RouteContractError("rounding audit gamma domain is invalid")
    reverse_sum = nr * _exact(weight)
    required_reverse_error = product / (1 - product) * reverse_sum
    reverse_error = _exact(guard.report["reverse_error_minutes"])
    transition_error = _exact(guard.report["transition_error_minutes"])
    priority_error = _exact(guard.report["priority_error_minutes"])
    remaining_upper = _exact(guard._remaining_upper)
    clock_ulp = _exact(math.ulp(upper))
    if (_exact(guard.report["clock_ulp_minutes"]) < clock_ulp
            or reverse_error < required_reverse_error
            or transition_error < max_forward_steps * clock_ulp
            or remaining_upper < reverse_sum + reverse_error):
        raise RouteContractError("rounding guard error enclosure is too small")
    exact_total_upper = _exact(upper) + remaining_upper
    # A directed ceiling of a rational, without using any guard helper.
    total_upper = float(exact_total_upper)
    if _exact(total_upper) < exact_total_upper:
        total_upper = math.nextafter(total_upper, math.inf)
    if priority_error < _exact(math.ulp(total_upper)):
        raise RouteContractError("rounding guard final-addition enclosure is too small")
    error = _exact(guard._error)
    if (error < reverse_error + transition_error + priority_error
            or float_bits(guard.report["fixed_error_minutes"]) != float_bits(guard._error)):
        raise RouteContractError("rounding guard fixed error enclosure is too small")
    if (float_bits(guard._start) != float_bits(start)
            or float_bits(guard._deadline) != float_bits(upper)):
        raise RouteContractError("rounding guard internal clock domain differs")
    return {
        "conditional_error_coefficients_verified": True,
        "coefficient_oracle": "exact_rationals_of_stored_binary64",
        "forward_steps_premise": "legal_suffix_transitions_le_declared_Nf",
        "unexpanded_suffix_step_bound_verified": False,
        "unconditional_priority_admissibility_verified": False,
    }


def verify_guard_equivalence(reference, common):
    """A one-ULP or signed-zero difference is a mismatch, not a tolerance."""
    if type(reference) is not TimeRoundingGuard or type(common) is not TimeRoundingGuard:
        raise RouteContractError("rounding audit requires original TimeRoundingGuard")
    if (not reference.report["enabled"] or not common.report["enabled"]
            or not reference._enabled or not common._enabled):
        raise RouteContractError("rounding guard disabled; no zero-priority acceptance")
    if reference.report.keys() != common.report.keys():
        raise RouteContractError("rounding guard report coverage differs")
    for name, value in reference.report.items():
        other = common.report[name]
        same = (float_bits(value) == float_bits(other) if type(value) is float
                else type(value) is type(other) and value == other)
        if not same:
            raise RouteContractError("rounding guard coefficient differs: field=" + name)
    for name in ("_start", "_deadline", "_remaining_upper", "_error"):
        if float_bits(getattr(reference, name)) != float_bits(getattr(common, name)):
            raise RouteContractError("rounding guard internal value differs: field=" + name)

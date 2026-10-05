"""Conservative priorities for Tokyo's operational binary64 arrival clocks.

Timetable rides replace the clock with a pinned arrival, rather than adding a
duration. Their rounding is therefore handled at the two shifted endpoints,
not by pretending the complete route is a cost sum starting at zero.
"""

from __future__ import annotations

import math


def _up_sum(first, second):
    if first == 0.0:
        return second
    if second == 0.0:
        return first
    return math.nextafter(first + second, math.inf)


def _up_product(first, second):
    if first == 0.0 or second == 0.0:
        return 0.0
    return math.nextafter(first * second, math.inf)


def _nonnegative_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0.0 else None


def _up_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if count < 0 or count != value:
        return None
    try:
        result = float(count)
    except OverflowError:
        return None
    return math.nextafter(result, math.inf) if count else 0.0


def _up_gamma(count):
    if count == 0.0:
        return 0.0
    product = _up_product(count, 2.0**-53)
    if not math.isfinite(product) or product >= 1.0:
        return math.inf
    denominator = math.nextafter(1.0 - product, -math.inf)
    if denominator <= 0.0:
        return math.inf
    return math.nextafter(product / denominator, math.inf)


class TimeRoundingGuard:
    """Lower a node-bound priority without changing any actual arrival clock.

    Every feasible suffix must keep its finite, nonnegative operational clock
    in [start_minute, deadline]. ``max_forward_steps`` bounds its transitions:
    every parent of a yielded label was popped, so the original pop budget is
    sufficient. ``max_reverse_steps`` bounds a simple relaxed path, including
    a virtual destination edge; node count plus one is sufficient. All relaxed
    elapsed weights must be finite, nonnegative and <= ``max_edge_minutes``.

    Let U=deadline and eps=ulp(U). For a physical addition fl(t+w), its exact
    elapsed time (a difference of two stored floats) is >= w-eps. Static ride
    weights must be rounded downward from raw_arrival-raw_departure. For a
    concrete ride with a common pinned float delay d, its operational endpoints
    are fl(raw_arrival+d) and fl(raw_departure+d), both inside the query range.
    Each endpoint addition loses at most half an ulp(U), so their difference
    is >= the raw interval minus eps. The label's current clock is <= the
    departure by TimetableChoices.ride_options' feasibility check. This also
    covers dwell. Bus delay may be *derived* by subtracting the boarding clock:
    its subtraction error changes the common d, but does not create another
    error between the two endpoints. No equality with the original route delay
    is assumed. Opaque/custom transition models must supply zero bounds.

    Consequently each relaxed weight along a legal suffix is at most that
    transition's exact operational elapsed time plus eps. Those exact elapsed
    times telescope, even when timetable assignments replace the clock. For
    Nf transitions, the summed overestimate is bounded by Nf*eps.

    Reverse Dijkstra's floating bound h is <= the rounded reverse evaluation
    of a mathematical minimum simple path. With Nr additions, W=max weight
    and binary64 unit roundoff u=2**-53, its error is <= gamma(Nr)*Nr*W.
    Thus h <= (final_clock-current_clock) + Nf*eps + reverse_error.

    The final fl(current_clock+h) addition is bounded by one ulp(U+Hmax),
    where Hmax=Nr*W+reverse_error. Subtract the query-wide sum of these errors
    with downward rounding. Nondecreasing operational clocks also imply that
    current_clock <= final_clock, so clamping to current_clock stays safe.
    All error coefficients/sums/products round upward; the gamma denominator
    and final subtraction round downward. The fixed error does not introduce
    a prefix-dependent preference among equal estimated arrival clocks.

    Goals/zero bounds return their actual clock exactly. Invalid domains,
    nonfinite arithmetic, clocks outside the query, and bounds above Hmax
    disable only this heuristic and return the current clock. The caller must
    preserve the exact resource/frontier checks and allow improved labels;
    this class is not a new dominance or pruning rule.
    """

    __slots__ = ("_enabled", "_start", "_deadline", "_remaining_upper", "_error", "report")

    def __init__(self, *, start_minute, deadline, max_forward_steps,
                 max_reverse_steps, max_edge_minutes):
        self._enabled = False
        self._start = self._deadline = self._remaining_upper = self._error = 0.0
        self.report = {"enabled": False, "scope": "operational absolute arrival clocks"}
        start = _nonnegative_float(start_minute)
        upper = _nonnegative_float(deadline)
        weight = _nonnegative_float(max_edge_minutes)
        forward = _up_count(max_forward_steps)
        reverse = _up_count(max_reverse_steps)
        if (any(value is None for value in (start, upper, weight, forward, reverse))
                or upper < start):
            self.report["disabled_reason"] = "invalid_clock_domain_or_parameters"
            return
        gamma = _up_gamma(reverse)
        reverse_sum = _up_product(reverse, weight)
        reverse_error = _up_product(gamma, reverse_sum)
        remaining_upper = _up_sum(reverse_sum, reverse_error)
        endpoint_ulp = math.nextafter(math.ulp(upper), math.inf)
        transition_error = _up_product(forward, endpoint_ulp)
        total_upper = _up_sum(upper, remaining_upper)
        if not all(math.isfinite(value) for value in (
                forward, reverse, gamma, reverse_sum, reverse_error,
                remaining_upper, transition_error, total_upper)):
            self.report["disabled_reason"] = "nonfinite_error_bound"
            return
        priority_error = math.nextafter(math.ulp(total_upper), math.inf)
        error = _up_sum(_up_sum(reverse_error, transition_error), priority_error)
        if not math.isfinite(error):
            self.report["disabled_reason"] = "nonfinite_error_bound"
            return
        self._start, self._deadline = start, upper
        self._remaining_upper, self._error = remaining_upper, error
        self._enabled = True
        self.report.update({
            "enabled": True, "start_minute": start, "deadline": upper,
            "max_forward_steps": max_forward_steps, "max_reverse_steps": max_reverse_steps,
            "max_edge_minutes": weight, "clock_ulp_minutes": endpoint_ulp,
            "reverse_error_minutes": reverse_error,
            "transition_error_minutes": transition_error,
            "priority_error_minutes": priority_error,
            "fixed_error_minutes": error,
        })

    def __call__(self, clock, remaining_minutes):
        current = float(clock)
        if (not self._enabled or not math.isfinite(current)
                or current < self._start or current > self._deadline):
            return current
        remaining = _nonnegative_float(remaining_minutes)
        if remaining is None or remaining == 0.0 or remaining > self._remaining_upper:
            return current
        total = current + remaining
        if not math.isfinite(total):
            return current
        return max(current, math.nextafter(total - self._error, -math.inf))

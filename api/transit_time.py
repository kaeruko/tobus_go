"""Exact MINUTE clocks for scheduled v2; no implicit seconds/unit switching.

Source seconds are explicitly divided by 60. Integer minute inputs are exact;
float minute inputs mean their finite decimal representation (e.g. 0.1 minute
is exactly six seconds). Fraction inputs retain their exact rational value.
Tokyo float clocks and static Python/Rust v1 integer clocks are unchanged.
"""
from fractions import Fraction
import math


def exact_minutes(value: int | float | Fraction, *, field: str) -> Fraction:
    if type(value) is Fraction:
        result = value
    elif type(value) is int:
        result = Fraction(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{field} must be a finite nonnegative minute value")
        result = Fraction(str(value))
    else:
        raise ValueError(f"{field} requires int/float/Fraction MINUTES, got {type(value).__name__}")
    if result < 0:
        raise ValueError(f"{field} must be a nonnegative minute value")
    return result


def source_clock_minutes(minute, seconds, *, trip_id, sequence, cache) -> Fraction | None:
    if minute is None:
        if seconds is not None:
            raise ValueError(f"source seconds without minute field: {trip_id} sequence={sequence}")
        return None
    if type(minute) is not int or minute < 0:
        raise ValueError(f"invalid service-day clock: {trip_id} sequence={sequence}")
    if seconds is not None:
        if type(seconds) is not int or seconds < 0:
            raise ValueError(f"invalid source seconds: {trip_id} sequence={sequence}")
        if minute != seconds // 60 + (1 if seconds % 60 >= 30 else 0):
            raise ValueError(f"source seconds/minutes mismatch: {trip_id} sequence={sequence}")
        key = seconds
    else:
        # Explicit minute-resolution Dataset records (e.g. hand-built fixtures).
        # This is the declared record format, not recovery from a parse failure.
        key = minute * 60
    if key not in cache:
        cache[key] = Fraction(key, 60)
    return cache[key]

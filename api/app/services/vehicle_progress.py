from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_STATUS_NAMES = {
    0: "INCOMING_AT",
    1: "STOPPED_AT",
    2: "IN_TRANSIT_TO",
}
_VALID_STATUS_NAMES = frozenset(_STATUS_NAMES.values())


@dataclass(frozen=True, slots=True)
class VehicleStopProgress:
    """GTFS-Realtime vehicle progress relative to the reported stop.

    `current_stop_sequence` identifies the stop the vehicle is approaching or
    currently at. `from_stop_sequence` is the most recently reached/departed
    stop used by navigation. It is intentionally `None` while a vehicle is
    still approaching the first stop; callers must not fabricate a previous
    stop for that state.
    """

    observed_stop_sequence: int
    from_stop_sequence: int | None
    before_first_stop: bool
    status_name: str


def normalize_vehicle_stop_status(value: Any) -> str:
    if isinstance(value, bool):
        raise RuntimeError(f"unsupported VehicleStopStatus: {value!r}")
    if isinstance(value, int):
        try:
            return _STATUS_NAMES[value]
        except KeyError as error:
            raise RuntimeError(
                f"unsupported VehicleStopStatus: {value!r}"
            ) from error
    if isinstance(value, str) and value in _VALID_STATUS_NAMES:
        return value
    raise RuntimeError(f"unsupported VehicleStopStatus: {value!r}")


def resolve_vehicle_stop_progress(
    *,
    observed_stop_sequence: int,
    current_status: Any,
    previous_stop_sequence: int | None,
) -> VehicleStopProgress:
    if (
        isinstance(observed_stop_sequence, bool)
        or not isinstance(observed_stop_sequence, int)
        or observed_stop_sequence <= 0
    ):
        raise RuntimeError(
            "VehiclePosition current_stop_sequence must be a positive integer"
        )

    if previous_stop_sequence is not None:
        if (
            isinstance(previous_stop_sequence, bool)
            or not isinstance(previous_stop_sequence, int)
            or previous_stop_sequence <= 0
        ):
            raise RuntimeError("previous stop sequence must be a positive integer")
        if previous_stop_sequence >= observed_stop_sequence:
            raise RuntimeError(
                "previous stop sequence must be before current_stop_sequence: "
                f"previous={previous_stop_sequence}, observed={observed_stop_sequence}"
            )

    status_name = normalize_vehicle_stop_status(current_status)

    if status_name == "STOPPED_AT":
        return VehicleStopProgress(
            observed_stop_sequence=observed_stop_sequence,
            from_stop_sequence=observed_stop_sequence,
            before_first_stop=False,
            status_name=status_name,
        )

    if status_name in {"INCOMING_AT", "IN_TRANSIT_TO"}:
        if previous_stop_sequence is None:
            return VehicleStopProgress(
                observed_stop_sequence=observed_stop_sequence,
                from_stop_sequence=None,
                before_first_stop=True,
                status_name=status_name,
            )
        return VehicleStopProgress(
            observed_stop_sequence=observed_stop_sequence,
            from_stop_sequence=previous_stop_sequence,
            before_first_stop=False,
            status_name=status_name,
        )

    raise RuntimeError(f"unsupported VehicleStopStatus: {current_status!r}")

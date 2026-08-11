class BusLocationMatchError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def select_bus_candidate(
    candidates: list[dict],
    *,
    route_id: str,
    trip_id: str,
    vehicle_id: str | None = None,
) -> dict:
    route_matches = [
        bus for bus in candidates if bus.get("odpt:busroute") == route_id
    ]
    if not route_matches:
        raise BusLocationMatchError(
            404,
            "bus_route_not_found",
            f"No bus found on route {route_id}",
        )

    trip_matches = [
        bus for bus in route_matches if bus.get("trip_id") == trip_id
    ]
    if not trip_matches:
        raise BusLocationMatchError(
            404,
            "bus_trip_not_found",
            f"No bus found for trip {trip_id} on route {route_id}",
        )
    if len(trip_matches) > 1:
        raise BusLocationMatchError(
            409,
            "ambiguous_bus_trip",
            f"Multiple buses found for trip {trip_id} on route {route_id}",
        )

    target = trip_matches[0]
    if vehicle_id is not None and target.get("vehicle_id") != vehicle_id:
        raise BusLocationMatchError(
            404,
            "vehicle_not_found",
            f"Vehicle {vehicle_id} is not serving trip {trip_id}",
        )
    return target

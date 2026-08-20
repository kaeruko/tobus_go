from __future__ import annotations

import bisect
import heapq
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from transit_dataset import TransitDataset, TransitMode, TransitStopTime


@dataclass(frozen=True, slots=True)
class TransitLeg:
    trip_id: str
    route_id: str
    mode: TransitMode
    from_stop_id: str
    to_stop_id: str
    departure_minute: int
    arrival_minute: int
    stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransitItinerary:
    departure_minute: int
    arrival_minute: int
    legs: tuple[TransitLeg, ...]

    @property
    def rides(self) -> int:
        return len(self.legs)

    @property
    def transfers(self) -> int:
        return max(0, self.rides - 1)

    @property
    def total_minutes(self) -> int:
        return self.arrival_minute - self.departure_minute


class TransitRouteEngine:
    """Static route engine that consumes only TransitDataset.

    It deliberately has no knowledge of GTFS field names, ODPT field names,
    operator names, or city names. Adapters must normalize those before the
    dataset reaches this class.
    """

    def __init__(self, dataset: TransitDataset):
        self.dataset = dataset
        self._trip_stop_times: dict[str, tuple[TransitStopTime, ...]] = {}
        self._departures_by_stop: dict[
            str, list[tuple[int, str, int]]
        ] = {}

        grouped: dict[str, list[TransitStopTime]] = {}
        for stop_time in dataset.stop_times:
            grouped.setdefault(stop_time.trip_id, []).append(stop_time)

        for trip_id, rows in grouped.items():
            rows.sort(key=lambda row: row.sequence)
            previous_sequence: int | None = None
            previous_clock: int | None = None
            for row in rows:
                if previous_sequence is not None and row.sequence <= previous_sequence:
                    raise ValueError(f"trip stop_sequence is not increasing: {trip_id}")
                event_clock = (
                    row.departure_minute
                    if row.departure_minute is not None
                    else row.arrival_minute
                )
                if (
                    previous_clock is not None
                    and event_clock is not None
                    and event_clock < previous_clock
                ):
                    raise ValueError(f"trip times go backwards: {trip_id}")
                previous_sequence = row.sequence
                if event_clock is not None:
                    previous_clock = event_clock
                if row.departure_minute is not None:
                    self._departures_by_stop.setdefault(row.stop_id, []).append(
                        (row.departure_minute, trip_id, row.sequence)
                    )
            self._trip_stop_times[trip_id] = tuple(rows)

        missing_stop_times = set(dataset.trips) - set(self._trip_stop_times)
        if missing_stop_times:
            sample = sorted(missing_stop_times)[0]
            raise ValueError(f"trip has no stop_times: {sample}")

        for departures in self._departures_by_stop.values():
            departures.sort()

    def search_fastest(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        *,
        departure: datetime,
        max_rides: int = 6,
    ) -> TransitItinerary | None:
        return self._search(
            origin_stop_id,
            destination_stop_id,
            departure=departure,
            objective="fastest",
            max_rides=max_rides,
        )

    def search_fewest_transfers(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        *,
        departure: datetime,
        max_rides: int = 6,
    ) -> TransitItinerary | None:
        return self._search(
            origin_stop_id,
            destination_stop_id,
            departure=departure,
            objective="fewest_transfers",
            max_rides=max_rides,
        )

    def _search(
        self,
        origin_stop_id: str,
        destination_stop_id: str,
        *,
        departure: datetime,
        objective: Literal["fastest", "fewest_transfers"],
        max_rides: int,
    ) -> TransitItinerary | None:
        if origin_stop_id not in self.dataset.stops:
            raise KeyError(f"unknown origin stop: {origin_stop_id}")
        if destination_stop_id not in self.dataset.stops:
            raise KeyError(f"unknown destination stop: {destination_stop_id}")
        if departure.tzinfo is None or departure.utcoffset() is None:
            raise ValueError("departure must be timezone-aware")
        if max_rides < 1:
            raise ValueError("max_rides must be >= 1")

        start_minute = departure.hour * 60 + departure.minute
        if origin_stop_id == destination_stop_id:
            return TransitItinerary(start_minute, start_minute, ())

        active_services = self.dataset.active_service_ids(departure.date())
        if not active_services:
            return None

        # State is (stop_id, rides_used). Keeping ride count in the state avoids
        # discarding an earlier multi-transfer option solely because a later
        # low-transfer state also reaches the same stop.
        start_state = (origin_stop_id, 0)
        best_time: dict[tuple[str, int], int] = {start_state: start_minute}
        predecessor: dict[
            tuple[str, int], tuple[tuple[str, int], TransitLeg]
        ] = {}

        queue: list[tuple[tuple[int, int], int, str, int]] = []

        def priority(time_minute: int, rides: int) -> tuple[int, int]:
            if objective == "fastest":
                return (time_minute, rides)
            return (rides, time_minute)

        serial = 0
        heapq.heappush(
            queue,
            (priority(start_minute, 0), serial, origin_stop_id, 0),
        )

        while queue:
            _, _, stop_id, rides_used = heapq.heappop(queue)
            state = (stop_id, rides_used)
            current_time = best_time.get(state)
            if current_time is None:
                continue
            if stop_id == destination_stop_id:
                return self._reconstruct(
                    predecessor,
                    state,
                    departure_minute=start_minute,
                    arrival_minute=current_time,
                )
            if rides_used >= max_rides:
                continue

            departures = self._departures_by_stop.get(stop_id, ())
            index = bisect.bisect_left(
                departures,
                (current_time, "", -1),
            )
            for departure_minute, trip_id, origin_sequence in departures[index:]:
                trip = self.dataset.trips[trip_id]
                if trip.service_id not in active_services:
                    continue
                route = self.dataset.routes[trip.route_id]
                rows = self._trip_stop_times[trip_id]
                downstream = [row for row in rows if row.sequence > origin_sequence]
                if not downstream:
                    continue
                next_rides = rides_used + 1
                traversed = [stop_id]
                for row in downstream:
                    traversed.append(row.stop_id)
                    if row.arrival_minute is None:
                        continue
                    next_state = (row.stop_id, next_rides)
                    prior = best_time.get(next_state)
                    if prior is not None and prior <= row.arrival_minute:
                        continue
                    leg = TransitLeg(
                        trip_id=trip.id,
                        route_id=trip.route_id,
                        mode=route.mode,
                        from_stop_id=stop_id,
                        to_stop_id=row.stop_id,
                        departure_minute=departure_minute,
                        arrival_minute=row.arrival_minute,
                        stop_ids=tuple(traversed),
                    )
                    best_time[next_state] = row.arrival_minute
                    predecessor[next_state] = (state, leg)
                    serial += 1
                    heapq.heappush(
                        queue,
                        (
                            priority(row.arrival_minute, next_rides),
                            serial,
                            row.stop_id,
                            next_rides,
                        ),
                    )
        return None

    @staticmethod
    def _reconstruct(
        predecessor: dict[
            tuple[str, int], tuple[tuple[str, int], TransitLeg]
        ],
        state: tuple[str, int],
        *,
        departure_minute: int,
        arrival_minute: int,
    ) -> TransitItinerary:
        legs: list[TransitLeg] = []
        cursor = state
        while cursor in predecessor:
            previous, leg = predecessor[cursor]
            legs.append(leg)
            cursor = previous
        legs.reverse()
        return TransitItinerary(
            departure_minute=departure_minute,
            arrival_minute=arrival_minute,
            legs=tuple(legs),
        )

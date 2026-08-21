import bisect
import csv
import datetime
import logging
import os
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _time_to_minute(value: str) -> int:
    """Convert a GTFS time (including 24:xx and later) to service-day minutes."""
    hour, minute, second = (int(part) for part in value.split(":"))
    return hour * 60 + minute + (1 if second >= 30 else 0)


@dataclass(frozen=True, slots=True)
class GtfsTripLeg:
    trip_id: str
    route_id: str
    service_id: str
    origin_stop_id: str
    destination_stop_id: str
    origin_sequence: int
    destination_sequence: int
    departure_minute: int
    arrival_minute: int


def _normalize_route_name(value: str) -> str:
    if not value:
        return ""
    table = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return value.translate(table).replace(" ", "")


def _validate_feed_id(feed_id: str) -> str:
    if not isinstance(feed_id, str) or not feed_id:
        raise ValueError("feed_id must be a non-empty string")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if any(character not in allowed for character in feed_id):
        raise ValueError(
            f"Invalid feed_id={feed_id!r}; only ASCII letters, digits, '_' and '-' are allowed"
        )
    return feed_id


class GtfsRepository:
    """One isolated static GTFS feed.

    A repository instance owns exactly one feed.  Raw GTFS IDs remain raw inside
    that instance for compatibility with the Tokyo routing code; use
    :meth:`qualified_id` when an ID leaves the feed boundary.
    """

    REQUIRED_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")

    def __init__(self, feed_id: str = "default"):
        self.feed_id = _validate_feed_id(feed_id)
        self.source_dir: str | None = None
        self._reset_data()

    def _reset_data(self) -> None:
        self.trips = {}
        self.stop_times = defaultdict(dict)
        self.stops = {}
        self.routes = {}
        self.route_name_to_id = {}
        self.timetable_index = defaultdict(list)
        self.service_calendar = {}
        self.service_exceptions = defaultdict(dict)
        self._active_service_cache = {}
        self.is_loaded = False

    def qualified_id(self, source_id: str) -> str:
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a non-empty string")
        return f"{self.feed_id}:{source_id}"

    def load_data(self, gtfs_dir: str):
        """Load one GTFS feed atomically.

        Required static files must all exist.  Parsing is performed into local
        structures first, so a malformed or partial feed never replaces the
        repository's current state.
        """
        source_dir = os.path.realpath(gtfs_dir)
        if self.is_loaded:
            if source_dir == self.source_dir:
                logger.info("GTFS feed %s already loaded from %s", self.feed_id, source_dir)
                return self
            raise RuntimeError(
                f"GTFS feed {self.feed_id!r} is already loaded from {self.source_dir}; "
                f"create another GtfsRepository for {source_dir}"
            )

        if not os.path.isdir(source_dir):
            raise FileNotFoundError(f"GTFS directory not found: {source_dir}")

        paths = {
            filename: os.path.join(source_dir, filename)
            for filename in self.REQUIRED_FILES
        }
        missing = [filename for filename, path in paths.items() if not os.path.isfile(path)]
        if missing:
            raise FileNotFoundError(
                f"GTFS feed {self.feed_id!r} is missing required files: {', '.join(missing)}"
            )

        trips = {}
        stop_times = defaultdict(dict)
        stops = {}
        routes = {}
        route_name_to_id = {}
        timetable_index = defaultdict(list)
        service_calendar = {}
        service_exceptions = defaultdict(dict)

        logger.info("Loading GTFS feed %s from %s", self.feed_id, source_dir)

        calendar_path = os.path.join(source_dir, "calendar.txt")
        if os.path.exists(calendar_path):
            with open(calendar_path, encoding="utf-8-sig") as file:
                for row in csv.DictReader(file):
                    service_calendar[row["service_id"]] = {
                        "weekdays": tuple(
                            row[name] == "1"
                            for name in (
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                                "saturday",
                                "sunday",
                            )
                        ),
                        "start_date": row["start_date"],
                        "end_date": row["end_date"],
                    }

        calendar_dates_path = os.path.join(source_dir, "calendar_dates.txt")
        if os.path.exists(calendar_dates_path):
            with open(calendar_dates_path, encoding="utf-8-sig") as file:
                for row in csv.DictReader(file):
                    service_exceptions[row["date"]][row["service_id"]] = int(
                        row["exception_type"]
                    )

        with open(paths["stops.txt"], encoding="utf-8") as file:
            for row in csv.DictReader(file):
                stops[row["stop_id"]] = {
                    "name": row["stop_name"],
                    "lat": float(row["stop_lat"]),
                    "lon": float(row["stop_lon"]),
                }

        with open(paths["routes.txt"], encoding="utf-8") as file:
            for row in csv.DictReader(file):
                route_id = row["route_id"]
                routes[route_id] = row
                short_name = row.get("route_short_name")
                if short_name:
                    route_name_to_id[_normalize_route_name(short_name)] = route_id

        trip_to_route = {}
        with open(paths["trips.txt"], encoding="utf-8") as file:
            for row in csv.DictReader(file):
                trip_id = row["trip_id"]
                route_id = row["route_id"]
                if route_id not in routes:
                    raise ValueError(
                        f"GTFS trip {trip_id!r} references unknown route_id {route_id!r}"
                    )
                trips[trip_id] = row
                trip_to_route[trip_id] = route_id

        count = 0
        with open(paths["stop_times.txt"], encoding="utf-8") as file:
            for row in csv.DictReader(file):
                trip_id = row["trip_id"]
                if trip_id not in trip_to_route:
                    raise ValueError(
                        f"GTFS stop_time references unknown trip_id {trip_id!r}"
                    )
                stop_id = row["stop_id"]
                if stop_id not in stops:
                    raise ValueError(
                        f"GTFS stop_time for trip {trip_id!r} references unknown stop_id {stop_id!r}"
                    )
                sequence = int(row["stop_sequence"])
                arrival_minute = _time_to_minute(row["arrival_time"])
                departure_minute = _time_to_minute(row["departure_time"])
                stop_times[trip_id][sequence] = (
                    stop_id,
                    arrival_minute,
                    departure_minute,
                )
                route_id = trip_to_route[trip_id]
                timetable_index[f"{route_id}|{stop_id}"].append(
                    (departure_minute, sequence, trip_id)
                )
                count += 1

        for schedule in timetable_index.values():
            schedule.sort()

        # Commit the fully parsed feed in one step.
        self.trips = trips
        self.stop_times = stop_times
        self.stops = stops
        self.routes = routes
        self.route_name_to_id = route_name_to_id
        self.timetable_index = timetable_index
        self.service_calendar = service_calendar
        self.service_exceptions = service_exceptions
        self._active_service_cache = {}
        self.source_dir = source_dir
        self.is_loaded = True

        logger.info(
            "Loaded GTFS feed %s: stops=%d routes=%d trips=%d stop_times=%d",
            self.feed_id,
            len(self.stops),
            len(self.routes),
            len(self.trips),
            count,
        )
        return self

    def get_active_service_ids(
        self,
        target_date: datetime.date | datetime.datetime | str,
    ) -> frozenset[str]:
        if isinstance(target_date, datetime.datetime):
            day = target_date.date()
        elif isinstance(target_date, datetime.date):
            day = target_date
        elif isinstance(target_date, str):
            try:
                day = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                return frozenset()
        else:
            return frozenset()

        date_key = day.strftime("%Y%m%d")
        cached = self._active_service_cache.get(date_key)
        if cached is not None:
            return cached

        active = {
            service_id
            for service_id, service in self.service_calendar.items()
            if service["start_date"] <= date_key <= service["end_date"]
            and service["weekdays"][day.weekday()]
        }
        for service_id, exception_type in self.service_exceptions.get(
            date_key, {}
        ).items():
            if exception_type == 1:
                active.add(service_id)
            elif exception_type == 2:
                active.discard(service_id)

        frozen = frozenset(active)
        self._active_service_cache[date_key] = frozen
        return frozen

    def get_bus_details(self, trip_id: str, stop_sequence: int):
        trip = self.trips.get(trip_id)
        if not trip:
            return None
        stop_time = self.stop_times.get(trip_id, {}).get(stop_sequence)
        if not stop_time:
            return None
        stop_id = stop_time[0]
        stop_info = self.stops.get(stop_id)
        stop_name = stop_info["name"] if stop_info else "Unknown"
        route_id = trip.get("route_id")
        route_info = self.routes.get(route_id, {})
        return {
            "route_id": route_id,
            "route_short_name": route_info.get("route_short_name", ""),
            "headsign": trip.get("headsign", ""),
            "next_stop_name": stop_name,
            "next_stop_id": stop_id,
        }

    def get_trip_stop_ids(self, trip_id: str) -> list[str]:
        stops_by_sequence = self.stop_times.get(trip_id, {})
        return [
            stop_time[0]
            for _, stop_time in sorted(stops_by_sequence.items())
        ]

    def get_trip_stop_schedule(self, trip_id: str) -> list[dict]:
        result = []
        for sequence, stop_time in sorted(
            self.stop_times.get(trip_id, {}).items()
        ):
            stop_id, arrival_minute, departure_minute = stop_time
            stop_info = self.stops.get(stop_id, {})

            def clock(minute: int) -> str:
                return f"{minute // 60:02d}:{minute % 60:02d}"

            result.append(
                {
                    "sequence": sequence,
                    "stop_id": stop_id,
                    "stop_name": stop_info.get("name", "Unknown"),
                    "arrival_minute": arrival_minute,
                    "departure_minute": departure_minute,
                    "arrival_time": clock(arrival_minute),
                    "departure_time": clock(departure_minute),
                }
            )
        return result

    def get_trip_stop_time_after(
        self,
        trip_id: str,
        stop_id: str,
        after_sequence: int = -1,
    ) -> tuple[int, int, int] | None:
        for sequence, stop_time in sorted(
            self.stop_times.get(trip_id, {}).items()
        ):
            current_stop_id, arrival_minute, departure_minute = stop_time
            if sequence > after_sequence and current_stop_id == stop_id:
                return sequence, arrival_minute, departure_minute
        return None

    def find_next_trip_leg(
        self,
        route_id: str,
        origin_stop_id: str,
        destination_stop_id: str,
        earliest_departure_minute: int,
        active_service_ids: frozenset[str] | set[str] | None = None,
        required_stop_ids: list[str] | tuple[str, ...] | None = None,
    ) -> GtfsTripLeg | None:
        schedule = self.timetable_index.get(f"{route_id}|{origin_stop_id}")
        if not schedule:
            return None

        index = bisect.bisect_left(
            schedule,
            (int(earliest_departure_minute), -1, ""),
        )
        for departure_minute, origin_sequence, trip_id in schedule[index:]:
            trip = self.trips.get(trip_id)
            if not trip:
                continue
            service_id = trip.get("service_id", "")
            if active_service_ids is not None and service_id not in active_service_ids:
                continue

            required_stops = list(required_stop_ids or ())
            if not required_stops or required_stops[0] != origin_stop_id:
                required_stops.insert(0, origin_stop_id)
            if required_stops[-1] != destination_stop_id:
                required_stops.append(destination_stop_id)

            current_sequence = origin_sequence
            destination = None
            for required_stop_id in required_stops[1:]:
                destination = self.get_trip_stop_time_after(
                    trip_id,
                    required_stop_id,
                    after_sequence=current_sequence,
                )
                if destination is None:
                    break
                current_sequence = destination[0]
            if destination is None or current_sequence == origin_sequence:
                continue
            destination_sequence, arrival_minute, _ = destination
            return GtfsTripLeg(
                trip_id=trip_id,
                route_id=route_id,
                service_id=service_id,
                origin_stop_id=origin_stop_id,
                destination_stop_id=destination_stop_id,
                origin_sequence=origin_sequence,
                destination_sequence=destination_sequence,
                departure_minute=departure_minute,
                arrival_minute=arrival_minute,
            )
        return None

    def find_route_id_by_name(self, short_name: str) -> str | None:
        return self.route_name_to_id.get(short_name)

    def find_trip_id(self, route_id: str, stop_id: str, time_str: str) -> str | None:
        key = f"{route_id}|{stop_id}"
        schedule = self.timetable_index.get(key)
        if not schedule:
            return None
        if len(time_str) == 5:
            time_str += ":00"
        minute = _time_to_minute(time_str)
        index = bisect.bisect_left(schedule, (minute, -1, ""))
        if index < len(schedule):
            return schedule[index][2]
        return None


class GtfsFeedRegistry:
    """Explicit registry of isolated GTFS repositories keyed by feed_id."""

    def __init__(self):
        self._feeds: dict[str, GtfsRepository] = {}

    def register(self, repository: GtfsRepository) -> GtfsRepository:
        existing = self._feeds.get(repository.feed_id)
        if existing is not None and existing is not repository:
            raise ValueError(f"GTFS feed_id already registered: {repository.feed_id}")
        self._feeds[repository.feed_id] = repository
        return repository

    def load(self, feed_id: str, gtfs_dir: str) -> GtfsRepository:
        feed_id = _validate_feed_id(feed_id)
        existing = self._feeds.get(feed_id)
        if existing is not None:
            return existing.load_data(gtfs_dir)

        repository = GtfsRepository(feed_id)
        # Register only after a complete successful load.  A failed feed never
        # leaves a half-loaded entry in the registry.
        repository.load_data(gtfs_dir)
        self._feeds[feed_id] = repository
        return repository

    def get(self, feed_id: str) -> GtfsRepository:
        feed_id = _validate_feed_id(feed_id)
        try:
            return self._feeds[feed_id]
        except KeyError as error:
            raise KeyError(f"GTFS feed is not registered: {feed_id}") from error

    def feed_ids(self) -> tuple[str, ...]:
        return tuple(self._feeds.keys())


# Compatibility handle for the currently deployed Tokyo runtime.  It is now a
# normal feed-scoped instance rather than a process-wide singleton.
gtfs_repo = GtfsRepository("toei_bus")
gtfs_feeds = GtfsFeedRegistry()
gtfs_feeds.register(gtfs_repo)

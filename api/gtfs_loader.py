import csv
import datetime
import os
from collections import defaultdict
from dataclasses import dataclass
import bisect
import logging

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

# ★追加: 正規化用ヘルパー関数
def _normalize_route_name(s: str) -> str:
    # 全角数字→半角数字、全角スペース→半角スペースなどの変換
    if not s: return ""
    tbl = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return s.translate(tbl).replace(" ", "")

class GtfsRepository:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GtfsRepository, cls).__new__(cls)
            cls._instance.trips = {}        # trip_id -> {headsign, route_id, direction_id}
            # trip_id -> {sequence: (stop_id, arrival_minute, departure_minute)}
            # This replaces the old stop-id-only value so the 1.3M GTFS rows
            # are not duplicated in a second in-memory index.
            cls._instance.stop_times = defaultdict(dict)
            cls._instance.stops = {}        # stop_id -> {name, lat, lon}
            cls._instance.routes = {}       # route_id -> {short_name, ...}
            cls._instance.route_name_to_id = {} # route_short_name -> route_id
            # "route|stop" -> [(departure_minute, sequence, trip_id), ...]
            cls._instance.timetable_index = defaultdict(list)
            cls._instance.service_calendar = {}
            cls._instance.service_exceptions = defaultdict(dict)
            cls._instance._active_service_cache = {}
            cls._instance.is_loaded = False
        return cls._instance

    def load_data(self, gtfs_dir: str):
        """
        Load static GTFS data from CSV files.
        Expected files: stops.txt, trips.txt, stop_times.txt, routes.txt
        """
        if self.is_loaded:
            logger.info("GTFS data already loaded.")
            return

        try:
            logger.info(f"Loading GTFS from {gtfs_dir}...")

            # GTFS service dates. calendar_dates exceptions override the
            # regular weekly flags from calendar for the exact requested date.
            calendar_path = os.path.join(gtfs_dir, "calendar.txt")
            if os.path.exists(calendar_path):
                with open(calendar_path, encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        self.service_calendar[row["service_id"]] = {
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

            calendar_dates_path = os.path.join(gtfs_dir, "calendar_dates.txt")
            if os.path.exists(calendar_dates_path):
                with open(calendar_dates_path, encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        self.service_exceptions[row["date"]][row["service_id"]] = int(
                            row["exception_type"]
                        )

            # 1. stops.txt
            stops_path = os.path.join(gtfs_dir, "stops.txt")
            if os.path.exists(stops_path):
                with open(stops_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # minimal data needed
                        self.stops[row['stop_id']] = {
                            "name": row['stop_name'],
                            "lat": float(row['stop_lat']),
                            "lon": float(row['stop_lon'])
                        }
                logger.info(f"Loaded {len(self.stops)} stops.")
            else:
                logger.warning("stops.txt not found.")

            # 2. routes.txt
            routes_path = os.path.join(gtfs_dir, "routes.txt")
            if os.path.exists(routes_path):
                with open(routes_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        r_id = row['route_id']
                        self.routes[r_id] = row
                        
                        short_name = row.get('route_short_name')
                        if short_name:
                             norm_name = _normalize_route_name(short_name)
                             self.route_name_to_id[norm_name] = r_id
                logger.info(f"Loaded {len(self.routes)} routes.")
            else:
                logger.warning("routes.txt not found.")

            # 3. trips.txt
            trip_to_route = {}
            trips_path = os.path.join(gtfs_dir, "trips.txt")
            if os.path.exists(trips_path):
                with open(trips_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        t_id = row['trip_id']
                        self.trips[t_id] = row
                        trip_to_route[t_id] = row['route_id']
                logger.info(f"Loaded {len(self.trips)} trips.")
            else:
                logger.warning("trips.txt not found.")

            # 4. stop_times.txt
            st_path = os.path.join(gtfs_dir, "stop_times.txt")
            if os.path.exists(st_path):
                logger.info("Building timetable index from stop_times.txt...")
                with open(st_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    count = 0
                    for row in reader:
                        t_id = row['trip_id']
                        s_id = row['stop_id']
                        seq = int(row['stop_sequence'])
                        arrival_minute = _time_to_minute(row['arrival_time'])
                        departure_minute = _time_to_minute(row['departure_time'])
                        
                        # Store the stop and its exact scheduled times together.
                        self.stop_times[t_id][seq] = (
                            s_id,
                            arrival_minute,
                            departure_minute,
                        )
                        
                        # Index for search: "route|stop" -> scheduled departures.
                        if t_id in trip_to_route:
                            r_id = trip_to_route[t_id]
                            key = f"{r_id}|{s_id}"
                            self.timetable_index[key].append(
                                (departure_minute, seq, t_id)
                            )
                        count += 1
                
                # Sort indices for bisect
                for key in self.timetable_index:
                    self.timetable_index[key].sort()
                    
                logger.info(f"Loaded {count} stop_times entries.")
            else:
                logger.warning("stop_times.txt not found.")

            self.is_loaded = True
            logger.info("GTFS Data Loaded Successfully.")

        except Exception as e:
            logger.error(f"Failed to load GTFS data: {e}")
            # Reset on failure so we can try again
            self.stops = {}
            self.trips = {}
            self.stop_times = defaultdict(dict)
            self.routes = {}
            self.route_name_to_id = {}
            self.timetable_index = defaultdict(list)
            self.service_calendar = {}
            self.service_exceptions = defaultdict(dict)
            self._active_service_cache = {}
            self.is_loaded = False
            raise

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
        if not trip: return None
        
        # Check specific sequence
        stop_time = self.stop_times.get(trip_id, {}).get(stop_sequence)
        
        # Fallback logic if sequence mismatch (optional, but keep simple for now)
        if not stop_time:
            return None
        stop_id = stop_time[0]
            
        stop_info = self.stops.get(stop_id)
        stop_name = stop_info['name'] if stop_info else "Unknown"
        
        route_id = trip.get('route_id') # Handle missing route_id gracefully
        route_info = self.routes.get(route_id, {})
        
        return {
            "route_id": route_id,
            "route_short_name": route_info.get('route_short_name', ''),
            "headsign": trip.get('headsign', ''), # Use .get for safety
            "next_stop_name": stop_name,
            "next_stop_id": stop_id
        }

    def get_trip_stop_ids(self, trip_id: str) -> list[str]:
        """Return the complete ordered stop list for one GTFS trip."""
        stops_by_sequence = self.stop_times.get(trip_id, {})
        return [
            stop_time[0]
            for _, stop_time in sorted(stops_by_sequence.items())
        ]

    def get_trip_stop_schedule(self, trip_id: str) -> list[dict]:
        """Return an ordered, log-friendly timetable for one GTFS trip."""
        result = []
        for sequence, stop_time in sorted(
            self.stop_times.get(trip_id, {}).items()
        ):
            stop_id, arrival_minute, departure_minute = stop_time
            stop_info = self.stops.get(stop_id, {})

            def clock(minute: int) -> str:
                return f"{minute // 60:02d}:{minute % 60:02d}"

            result.append({
                "sequence": sequence,
                "stop_id": stop_id,
                "stop_name": stop_info.get("name", "Unknown"),
                "arrival_minute": arrival_minute,
                "departure_minute": departure_minute,
                "arrival_time": clock(arrival_minute),
                "departure_time": clock(departure_minute),
            })
        return result

    def get_trip_stop_time_after(
        self,
        trip_id: str,
        stop_id: str,
        after_sequence: int = -1,
    ) -> tuple[int, int, int] | None:
        """Return (sequence, arrival_minute, departure_minute) after a stop."""
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
        """Find the next active trip that serves origin then destination."""
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
            if (
                active_service_ids is not None
                and service_id not in active_service_ids
            ):
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

    # ★追加: 名前からIDを引くメソッド
    def find_route_id_by_name(self, short_name: str) -> str:
        # 完全一致検索
        return self.route_name_to_id.get(short_name)

    # ★追加: 最適なTripIDを探すメソッド
    def find_trip_id(self, route_id: str, stop_id: str, time_str: str) -> str:
        key = f"{route_id}|{stop_id}"
        schedule = self.timetable_index.get(key)
        if not schedule: return None
        
        # Binary search for the first trip at or after time_str
        if len(time_str) == 5:
            time_str += ":00"
        minute = _time_to_minute(time_str)
        idx = bisect.bisect_left(schedule, (minute, -1, ""))
        if idx < len(schedule):
            return schedule[idx][2] # trip_id
        return None

gtfs_repo = GtfsRepository()

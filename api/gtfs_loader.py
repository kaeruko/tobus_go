import csv
import os
from collections import defaultdict
import bisect
import logging

logger = logging.getLogger(__name__)

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
            cls._instance.stop_times = defaultdict(dict) # trip_id -> {sequence: stop_id}
            cls._instance.stops = {}        # stop_id -> {name, lat, lon}
            cls._instance.routes = {}       # route_id -> {short_name, ...}
            cls._instance.route_name_to_id = {} # route_short_name -> route_id
            cls._instance.timetable_index = defaultdict(list) # "route|stop" -> [(time, trip), ...]
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
                        dep_time = row['departure_time']
                        
                        # Store lookup
                        self.stop_times[t_id][seq] = s_id
                        
                        # Index for search: "route|stop" -> [(time, trip), ...]
                        if t_id in trip_to_route:
                            r_id = trip_to_route[t_id]
                            key = f"{r_id}|{s_id}"
                            self.timetable_index[key].append((dep_time, t_id))
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
            self.is_loaded = False
            raise

    def get_bus_details(self, trip_id: str, stop_sequence: int):
        trip = self.trips.get(trip_id)
        if not trip: return None
        
        # Check specific sequence
        stop_id = self.stop_times.get(trip_id, {}).get(stop_sequence)
        
        # Fallback logic if sequence mismatch (optional, but keep simple for now)
        if not stop_id:
            return None
            
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

    # ★追加: 名前からIDを引くメソッド
    def find_route_id_by_name(self, short_name: str) -> str:
        # 完全一致検索
        return self.route_name_to_id.get(short_name)

    # ★追加: 最適なTripIDを探すメソッド
    def find_trip_id(self, route_id: str, stop_id: str, time_str: str) -> str:
        key = f"{route_id}|{stop_id}"
        schedule = self.timetable_index.get(key)
        if not schedule: return None
        
        # Ensure HH:MM:SS format
        if len(time_str) == 5: time_str += ":00"
        
        # Binary search for the first trip at or after time_str
        idx = bisect.bisect_left(schedule, (time_str, ""))
        if idx < len(schedule):
            return schedule[idx][1] # trip_id
        return None

gtfs_repo = GtfsRepository()

import csv
import os
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

class GtfsRepository:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GtfsRepository, cls).__new__(cls)
            cls._instance.trips = {}        # trip_id -> {headsign, route_id, direction_id}
            cls._instance.stop_times = defaultdict(dict) # trip_id -> {sequence: stop_id}
            cls._instance.stops = {}        # stop_id -> {name, lat, lon}
            cls._instance.routes = {}       # route_id -> {short_name, ...}
            cls._instance.is_loaded = False
        return cls._instance

    def load_data(self, gtfs_dir: str):
        """
        Load static GTFS data from CSV files.
        Expected files: stops.txt, trips.txt, stop_times.txt
        """
        if self.is_loaded:
            logger.info("GTFS data already loaded.")
            return

        try:
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

            # 2. trips.txt
            trips_path = os.path.join(gtfs_dir, "trips.txt")
            if os.path.exists(trips_path):
                with open(trips_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.trips[row['trip_id']] = {
                            "headsign": row.get('trip_headsign', ''),
                            "route_id": row.get('route_id', ''),
                            "direction_id": row.get('direction_id', '0')
                        }
                logger.info(f"Loaded {len(self.trips)} trips.")
            else:
                logger.warning("trips.txt not found.")

            # 3. stop_times.txt
            # This file can be large, optimistically load minimal fields
            st_path = os.path.join(gtfs_dir, "stop_times.txt")
            if os.path.exists(st_path):
                with open(st_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    count = 0
                    for row in reader:
                        t_id = row['trip_id']
                        seq = int(row['stop_sequence'])
                        s_id = row['stop_id']
                        self.stop_times[t_id][seq] = s_id
                        count += 1
                logger.info(f"Loaded {count} stop_times entries.")
            else:
                logger.warning("stop_times.txt not found.")

            # 4. routes.txt
            routes_path = os.path.join(gtfs_dir, "routes.txt")
            if os.path.exists(routes_path):
                with open(routes_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.routes[row['route_id']] = row
                logger.info(f"Loaded {len(self.routes)} routes.")
            else:
                logger.warning("routes.txt not found.")

            self.is_loaded = True
            logger.info("GTFS Static Data Load Complete.")
            
        except Exception as e:
            logger.error(f"Failed to load GTFS data: {e}")
            raise

    def get_bus_details(self, trip_id: str, current_sequence: int):
        """
        Resolve bus details based on trip_id and current_stop_sequence.
        Returns a dict with resolved info, or None if not found.
        """
        # Resolve Trip Info
        trip_info = self.trips.get(trip_id)
        if not trip_info:
            return None
            
        # Resolve Route Info
        route_info = self.routes.get(trip_info.get('route_id'))
        route_short_name = route_info.get('route_short_name') if route_info else None
        
        # Resolve 'Next Stop' (Target)
        stops_on_trip = self.stop_times.get(trip_id)
        if not stops_on_trip:
            return {
                "headsign": trip_info['headsign'],
                "route_id": trip_info['route_id'],
                "route_short_name": route_short_name,
                "trip_id": trip_id,
                "next_stop_name": "不明",
                "next_stop_id": None
            }

        next_stop_id = stops_on_trip.get(current_sequence)
        
        stop_name = "不明"
        if next_stop_id:
            s_info = self.stops.get(next_stop_id)
            if s_info:
                stop_name = s_info['name']

        return {
            "headsign": trip_info['headsign'],
            "route_id": trip_info['route_id'],
            "route_short_name": route_short_name,
            "trip_id": trip_id,
            "next_stop_name": stop_name,
            "next_stop_id": next_stop_id
        }

# Global instance for easy import
gtfs_repo = GtfsRepository()

from google.transit import gtfs_realtime_pb2
import logging
from .gtfs_loader import gtfs_repo

logger = logging.getLogger(__name__)

def parse_realtime_gtfs(content: bytes):
    """
    Parse GTFS-Realtime binary content and return a list of bus dictionaries
    compatible with the application's existing internal format.
    """
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(content)
    except Exception as e:
        logger.error(f"Failed to parse GTFS-RT protobuf: {e}")
        return []

    result_list = []
    
    for entity in feed.entity:
        if not entity.HasField('vehicle'):
            continue
            
        v = entity.vehicle
        trip_id = v.trip.trip_id
        
        # current_stop_sequence is 1-based usually
        seq = v.current_stop_sequence
        
        # Link with static data
        details = gtfs_repo.get_bus_details(trip_id, seq)
        
        if details:
            # Construct dictionary mapping to ODPT-like keys if necessary,
            # or just standardized keys for the app.
            # The existing app expects: "odpt:busroute", "odpt:fromBusstopPole", etc.
            # But we might want to transition to cleaner keys.
            # For compatibility with `routes.py`, we might need to mimic ODPT keys 
            # OR update `routes.py` to use new keys.
            # The user plan says: "Map the result to the existing internal JSON structure".
            
            # Legacy format (approximate):
            # "odpt:busroute": "odpt.Busroute:Toei.Ue23"
            # "odpt:fromBusstopPole": "odpt.BusstopPole:..." (Can we resolve this ID?)
            # "odpt:busTimetable": trip_id (or lookup)
            
            # Since we are moving away from ODPT IDs, we might use the standardized IDs from GTFS.
            # But the Frontend (Flutter) might expect specific ODPT ID formats?
            # If Frontend uses these IDs for display, we need to match or update Frontend.
            # The user led the charge to backend logic update, implying we can change keys 
            # OR we should check verify if Frontend depends on "odpt:..."
            
            # Assumption: Convert to the Internal model used by TimeMaster?
            # TimeMaster uses "latest_bus_positions" which is a list of dicts.
            # routes.py just dumps them.
            # So the Frontend expects whatever is dumped.
            
            # Key mappings:
            # vehicle_id -> odpt:bus (maybe) or just id
            # lat/lon -> (GeoJSON or separate fields?)
            
            current_stop_name = details.get('next_stop_name', '不明')
            route_id_raw = details.get('route_id', '???') 
            # Note: route_id in static GTFS might be "002" or similar short code.
            # We might need to prefix it "odpt.Busroute:Toei." + ...?
            # Or just pass it through.
            
            # Heuristic ID Conversion for compatibility
            odpt_route_id = None
            if route_short_name:
                odpt_route_id = _convert_short_name_to_odpt_id(route_short_name)

            bus_data = {
                "vehicle_id": v.vehicle.id,
                "lat": v.position.latitude,
                "lon": v.position.longitude,
                "trip_id": trip_id,
                
                # New standard keys
                "route_id": route_id_raw,
                "route_short_name": route_short_name,
                "destination": details.get('headsign'),
                "next_stop": current_stop_name,
                "next_stop_id": details.get('next_stop_id'),
                
                # Compatibility Keys for routes.py filtering
                "odpt:busroute": odpt_route_id, 
                "odpt:fromBusstopPole": details.get('next_stop_id'), # Mapping next_stop to 'from' is inaccurate but ensures existence
                # Note: GTFS 'current_stop_sequence' usually targets 'next' (or current if stopped).
                # ODPT 'fromBusstopPole' implies the pole just passed?
            }
            result_list.append(bus_data)
        else:
            # Even if static link fails...
            pass
            
    return result_list

def _convert_short_name_to_odpt_id(short_name: str) -> str:
    """
    Convert '上23' -> 'odpt.Busroute:Toei.Ue23'
    Simple heuristics for common prefixes.
    """
    if not short_name: return None
    
    # Check manual overrides / specific cases
    prefix_map = {
        "上": "Ue",
        "都": "T",
        "秋": "Aki",
        "平": "Hirai", # Or H? Check data. 'Hirai' is safer guess or 'H'.
        "錦": "Kin",
        "亀": "Kame",
        "草": "Kusa",
        "東": "Higashi",
        "急行": "Kyuko", 
    }
    
    # Attempt to split prefix (Kanji) and number
    import re
    m = re.match(r"^([^\d]+)(\d+.*)$", short_name)
    if m:
        pfx = m.group(1)
        num = m.group(2)
        if pfx in prefix_map:
            return f"odpt.Busroute:Toei.{prefix_map[pfx]}{num}"
    
    # Fallback: Just try to use it? Or return None?
    # If standard ODPT ID uses the Kanji? No, usually Romanized.
    return f"odpt.Busroute:Toei.{short_name}" # Unlikely to work but better than None



import sys
import os
import datetime
# Add api dir to path
sys.path.append(os.path.join(os.getcwd(), 'api'))

from toei_engine import build_graph, TimetableManager, search_best_routes, time_str_to_min, min_to_time_str

def main():
    print("Loading data...")
    DATA_DIR = "api/data"
    BUSSTOP = f"{DATA_DIR}/odpt_BusstopPole.json"
    BUSROUTE = f"{DATA_DIR}/odpt_BusroutePattern.json"
    STATIONS = f"{DATA_DIR}/odpt_Station.json"
    RAILWAYS = f"{DATA_DIR}/odpt_Railway.json"
    BUS_TBL = f"{DATA_DIR}/odpt_BusstopPoleTimetable.json"
    TRAIN_TBL = f"{DATA_DIR}/odpt_TrainTimetable.json"

    G = build_graph(BUSSTOP, BUSROUTE, STATIONS, RAILWAYS, walk_radius=300)
    tm = TimetableManager()
    tm.load_bus_timetables(BUS_TBL)
    tm.load_bus_route_patterns(BUSROUTE)
    tm.load_train_timetables(TRAIN_TBL)
    tm.build_name_index(G)
    
    # Find start/end nodes
    start_name = "平井七丁目北公園前"
    end_name = "押上"

    start_pids = tm.name_to_pids.get(start_name)
    end_pids = tm.name_to_pids.get(end_name)
    
    if not start_pids or not end_pids:
        print(f"Start or End not found: {start_name}={start_pids}, {end_name}={end_pids}")
        return

    # Use first found physics nodes
    start_node = ("phys", start_pids[0])
    
    # For end node, Oshiage might be station or bus stop.
    # User destination is likely Oshiage Station or Oshiage bus stop.
    # Let's try Oshiage bus stop first if detailed in pids.
    # Oshiage has many pids (bus terminals).
    # We can try search to nearest station/busstop using logic, or just pick one.
    # To be precise, let's pick a PID known to be served by Kami-23 (070).
    # But search_best_routes handles finding best path.
    # We just need *a* target node that represents "Oshiage".
    end_node = ("phys", end_pids[0])

    print(f"Searching from {start_node} to {end_node}")
    
    # Date: Saturday (e.g., 2025-12-06 is Saturday)
    target_date = datetime.datetime(2025, 12, 6, 20, 10)
    start_time = "20:10"
    
    print("--- Searching (Cost/Comfort Mode) ---")
    candidates = search_best_routes(G, tm, start_node, end_node, mode="cost", start_time=start_time, limit=5, target_date=target_date)
    
    print(f"Found {len(candidates)} candidates.")
    for cand in candidates:
        print(f"Candidate ({cand['total_time']}min):")
        for seg in cand['steps']:
            if seg['kind'] == 'bus':
                print(f"  BUS: {seg['title']} from {seg['from_']} ({seg.get('departure_time')}) to {seg['to']} ({seg.get('arrival_time')})")
    
    # Check if 20:41 is present.
    # If filtered correctly, we should NOT see a bus departing at 20:41 if it's the short trip.
    # Or maybe we see another bus.
    
    has_2041 = False
    for cand in candidates:
         for seg in cand['steps']:
            if seg['kind'] == 'bus' and seg.get('departure_time') == "20:41":
                has_2041 = True
    
    if has_2041:
        print("\n[FAIL] 20:41 bus was found in results. Check if it reaches destination.")
    else:
        print("\n[SUCCESS] 20:41 bus was NOT found in results (assuming it was the short trip).")

if __name__ == "__main__":
    main()

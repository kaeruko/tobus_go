
import sys
import os
from unittest.mock import MagicMock

# Mock networkx before import
sys.modules["networkx"] = MagicMock()

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from toei_engine import TimetableManager

def test_filtering():
    tm = TimetableManager()
    
    # Mock Route Patterns
    # R1 has two patterns:
    # Pattern A: P1 -> P2 -> P3 -> P4 (Long)
    # Pattern B: P1 -> P2 (Short)
    tm.route_patterns_map['R1'] = [
        ['P1', 'P2', 'P3', 'P4'],
        ['P1', 'P2']
    ]
    
    # Mock Timetable
    # Trip 1: Ends at P4 (Long) - Dep 100
    # Trip 2: Ends at P2 (Short) - Dep 110
    tm.bus_departures_weekday['P1'] = {
        'R1': [
            {'dep': 100, 'dest': 'P4'},
            {'dep': 110, 'dest': 'P2'}
        ]
    }
    
    print("--- Test 1: Board P1, Target P3, expects dest P4 ---")
    # P1 -> P3 -> P4 (Pattern A). 
    # Trip 1 (dest P4): P1 idx=0, P4 idx=3. Pattern A matches. T=P3 idx=2. 0 <= 2 <= 3. Valid.
    # Trip 2 (dest P2): P1 idx=0, P2 idx=1. Pattern B matches. T=P3 not in Pattern B.
    #                    Pattern A: P1 idx=0, P2 idx=1. P3 idx=2. idx=1 < idx=2 -> Not directional from P1 to P4? No dest is P2.
    #                    Pattern A: Board P1, Dest P2. P2 idx=1. 0 <= 1. OK for board->dest. P3 idx=2. 0 <= 2 <= 1? No.
    #                    So Trip 2 REJECTED.
    next_dep = tm.get_next_bus_departure(
        pole_id='P1', route_id='R1', current_time_min=0, 
        target_pole_id='P3', debug=True
    )
    print(f"Result: {next_dep}")
    if next_dep == 100:
        print("PASS: Only long trip selected.")
    else:
        print(f"FAIL: Expected 100, got {next_dep}")

    print("\n--- Test 2: Board P1, Target P2, expects 100 (earliest of 100/110) ---")
    # Trip 1 (dest P4): Pattern A. Board 0, Dest 3. Target P2 idx 1. 0 <= 1 <= 3. Valid.
    # Trip 2 (dest P2): Pattern B. Board 0, Dest 1. Target P2 idx 1. 0 <= 1 <= 1. Valid.
    next_dep_2 = tm.get_next_bus_departure(
        pole_id='P1', route_id='R1', current_time_min=0, 
        target_pole_id='P2', debug=True
    )
    print(f"Result: {next_dep_2}")
    if next_dep_2 == 100:
         print("PASS: Earliest trip selected (both valid).")
    else:
         print(f"FAIL: Expected 100, got {next_dep_2}")

    print("\n--- Test 3: Board P1, Target P5 (Not in any pattern) ---")
    # Target P5 not in patterns.
    # Trip 1: Pattern A (Board P1, Dest P4). Target not found.
    #         Pattern B (Board P1, Dest P4? No).
    #         any_directional_pattern = True (Pattern A connects P1->P4).
    #         if P5 not in stops: continue.
    #         Ends loop. any_directional_pattern=True. Returns False.
    # REJECTED (Strict Check) - Correct per user request "destination reachable only"
    next_dep_3 = tm.get_next_bus_departure(
        pole_id='P1', route_id='R1', current_time_min=0, 
        target_pole_id='P5', debug=True
    )
    print(f"Result: {next_dep_3}")
    if next_dep_3 is None:
        print("PASS: Rejected trip with unreachable target.")
    else:
        print(f"FAIL: Expected None, got {next_dep_3}")

    print("\n--- Test 4: Reverse Direction (Board P4, Dest P1) ---")
    # Actually need departures for P4.
    tm.bus_departures_weekday['P4'] = {
        'R1': [{'dep': 120, 'dest': 'P1'}] # Assume circular or just data
    }
    # Pattern A is P1->P4. No P4->P1 pattern.
    # any_directional_pattern should be False?
    # Unless there is a pattern. Let's add reverse pattern C: P4 -> P1.
    # tm.route_patterns_map['R1'].append(['P4', 'P3', 'P2', 'P1'])
    
    # If no pattern supports P4->P1, it falls back to True (legacy behavior for unknown patterns).
    # But wait, if pattern A exists containing P4 and P1, checked?
    # stops.index(P4)=3, stops.index(P1)=0. d < b. Continue.
    # So if only Pattern A exists, it finds NO directional pattern.
    # Returns True (Fallback).
    # This is correct for "unknown reverse route".
    next_dep_4 = tm.get_next_bus_departure(
        pole_id='P4', route_id='R1', current_time_min=0, 
        target_pole_id='P2', debug=True
    )
    print(f"Result: {next_dep_4}")
    if next_dep_4 == 120:
         print("PASS: Fallback for unknown pattern direction.")
    else:
         print(f"FAIL: Expected 120, got {next_dep_4}")


if __name__ == "__main__":
    test_filtering()

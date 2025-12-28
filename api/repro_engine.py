
import networkx as nx
import math

# Mocking necessary parts of toei_engine
def min_to_time_str(m):
    h = int(m // 60)
    mn = int(m % 60)
    return f"{h:02d}:{mn:02d}"

def time_str_to_min(t_str):
    if not t_str: return 99999
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

class MockTM:
    def get_next_bus_departure(self, pole_id, route_id, curr_time, pole_name=None, day_type="weekday", target_pole_id=None):
        return curr_time + 5 # returns dep time

    def get_next_train_arrival(self, u, v, curr_time, day_type, delays_snapshot):
        return curr_time + 5

# Copying segments_detailed from toei_engine.py (simplified or exact)
def segments_detailed(G, path, tm, start_time_str="10:00", day_type="weekday", delays_snapshot=None, virtual_dest_connections=None):
    segs = []
    cur = None
    last_phys = None
    curr_time = time_str_to_min(start_time_str)
    
    # Needs WALK_SPEED_M_PER_MIN
    WALK_SPEED_M_PER_MIN = 80.0

    def flush():
        nonlocal cur
        if cur:
            if cur["kind"] == "walk":
                if cur.get("meters", 0) <= 0 or cur.get("from_") == cur.get("to"):
                    cur = None
                    return
                cur["minutes"] = max(1, math.ceil(cur.get("meters", 0) / WALK_SPEED_M_PER_MIN))
            elif cur["kind"] in ("bus", "rail"):
                if cur.get("arrival_time"):
                    d = time_str_to_min(cur.get("departure_time"))
                    a = time_str_to_min(cur.get("arrival_time"))
                    cur["minutes"] = max(1, int(a - d))
                else:
                    cur["minutes"] = max(1, int(cur.get("edges", 0) * 2.0))
            segs.append(cur)
            cur = None

    for i, (u, v) in enumerate(zip(path, path[1:])):
        edge = G.get_edge_data(u, v)
        if not edge: continue
        
        etype = edge.get("etype")
        if u[0] == "phys": last_phys = u

        if etype == "walk":
            if not cur or cur["kind"] != "walk":
                flush()
                from_name = G.nodes[u]["name"] if u[0]=="phys" else "???"
                cur = { "kind": "walk", "title": "徒歩", "edges": 0, "from_": from_name, "to": None, "meters": 0 }
            cur["edges"] += 1
            cur["meters"] += edge.get("meters", 0)
            if v[0] == "phys":
                if str(v[1]).startswith("dest:"): cur["to"] = "目的地"
                elif v in G.nodes: cur["to"] = G.nodes[v]["name"]
                else: cur["to"] = str(v[1])
            curr_time += (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
            continue

        node = v if v[0] == "line" else (u if u[0] == "line" else None)
        if not node: continue
        line_disp = G.nodes[node].get("disp") or "???"
        mode = G.nodes[node].get("mode")

        if etype == "board":
            flush()
            from_name = G.nodes[last_phys]["name"] if last_phys else "???"
            origin_lat = G.nodes[last_phys].get("lat") if last_phys else None
            origin_lon = G.nodes[last_phys].get("lon") if last_phys else None
            
            curr_stops = [{"name": from_name, "is_origin": True, "lat": origin_lat, "lon": origin_lon}]
            
            phys_id = u[1]
            if mode == "bus":
                route_id = G.nodes[v].get("route_id")
                target_pid = None
                # Simplifying target_pid logic for mock
                dep = tm.get_next_bus_departure(phys_id, route_id, curr_time, pole_name=from_name, day_type=day_type, target_pole_id=target_pid)
                
                if dep and dep > curr_time:
                    wait_min = int(dep - curr_time)
                    if wait_min > 0:
                        flush()
                        segs.append({
                            "kind": "wait", "title": "待ち時間", "minutes": wait_min,
                            "edges": 0, "from_": from_name, "to": from_name, "meters": 0,
                            "departure_time": min_to_time_str(curr_time),
                            "arrival_time": min_to_time_str(dep),
                            "startLabel": "待ち時間", "place": from_name
                        })
                if dep and dep >= curr_time: curr_time = dep
            else:
                curr_time += 2.0 # Rail wait

            cur = {
                "kind": mode, "title": line_disp, "edges": 0, 
                "from_": from_name, "to": None, "stops": curr_stops,
                "departure_time": min_to_time_str(curr_time)
            }

        elif etype == "ride":
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] += 1
                stop_name = "???"
                phys_key = ("phys", v[1]) if v[0] == "line" else ("phys", u[1])
                if phys_key in G: stop_name = G.nodes[phys_key]["name"]
                if not cur["stops"] or cur["stops"][-1]["name"] != stop_name:
                    cur["stops"].append({
                        "name": stop_name,
                        "lat": G.nodes[phys_key].get("lat"),
                        "lon": G.nodes[phys_key].get("lon")
                    })
            
            if mode == "rail":
                arr = tm.get_next_train_arrival(u[1], v[1], curr_time, day_type, delays_snapshot)
                if arr: curr_time = arr
                else: curr_time += edge.get("w", 2.0)
            else:
                dist = edge.get("meters", 0)
                curr_time += (dist/250.0 if dist>0 else 2.5) + 0.8

        elif etype in ("alight", "xfer"):
            if cur and cur["kind"] in ("bus", "rail"):
                to_phys = v if v[0] == "phys" else last_phys
                if to_phys:
                    to_name = G.nodes[to_phys]["name"]
                    cur["to"] = to_name
                    stop_lat = G.nodes[to_phys].get("lat")
                    stop_lon = G.nodes[to_phys].get("lon")
                    
                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({
                            "name": to_name,
                            "is_destination": True,
                            "lat": stop_lat,
                            "lon": stop_lon
                        })
                    else:
                        cur["stops"][-1]["is_destination"] = True
                        cur["stops"][-1]["lat"] = stop_lat
                        cur["stops"][-1]["lon"] = stop_lon
                cur["arrival_time"] = min_to_time_str(curr_time)
                flush()
            curr_time += 1.0
            
    if cur: flush()
    return segs

# Build a simple graph
G = nx.DiGraph()
# Phys Nodes
phys1 = ("phys", "p1")
phys2 = ("phys", "p2")
phys3 = ("phys", "p3")
G.add_node(phys1, lat=35.0, lon=139.0, name="Stop 1", kind="phys")
G.add_node(phys2, lat=35.01, lon=139.01, name="Stop 2", kind="phys")
G.add_node(phys3, lat=35.02, lon=139.02, name="Stop 3", kind="phys")

# Line Nodes
line1 = ("line", "p1", "L1")
line2 = ("line", "p2", "L1")
line3 = ("line", "p3", "L1")

G.add_node(line1, lat=35.0, lon=139.0, name="Stop 1@Bus", mode="bus", route_id="R1", disp="Bus 1")
G.add_node(line2, lat=35.01, lon=139.01, name="Stop 2@Bus", mode="bus", route_id="R1", disp="Bus 1")
G.add_node(line3, lat=35.02, lon=139.02, name="Stop 3@Bus", mode="bus", route_id="R1", disp="Bus 1")

# Edges
# Walk p1 -> p2 (just for fun? No)
# Board p1 -> line1
G.add_edge(phys1, line1, etype="board", w=1.0)

# Ride line1 -> line2
G.add_edge(line1, line2, etype="ride", w=2.0, mode="bus", meters=500, line="L1")
# Ride line2 -> line3
G.add_edge(line2, line3, etype="ride", w=2.0, mode="bus", meters=500, line="L1")

# Alight line3 -> phys3
G.add_edge(line3, phys3, etype="alight", w=1.0)

path = [phys1, line1, line2, line3, phys3]

tm = MockTM()
segs = segments_detailed(G, path, tm)

print("Segments:", len(segs))
for s in segs:
    print(s["kind"], s["title"])
    if "stops" in s:
        print(" Stops:", len(s["stops"]))
        for st in s["stops"]:
            print("  ", st["name"], st["lat"], st["lon"])

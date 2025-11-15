#!/usr/bin/env python3
# debug_ueno_walk.py

from toei_reach_min_transfers import build_graph, haversine

DATA_DIR   = "data"
BUSSTOP    = f"{DATA_DIR}/busstop_poles.json"
BUSROUTE   = f"{DATA_DIR}/busroute_patterns.json"
STATIONS   = f"{DATA_DIR}/stations.json"
RAILWAYS   = f"{DATA_DIR}/railways.json"

UENO_BUS_ID   = "odpt.BusstopPole:Toei.UenoMatsuzakaya.2000.4"
UENO_OEDO_ID  = "odpt.Station:Toei.Oedo.UenoOkachimachi"

def main():
    G, st = build_graph(BUSSTOP, BUSROUTE, STATIONS, RAILWAYS, walk_radius=300)
    u_bus  = ("phys", UENO_BUS_ID)
    u_oedo = ("phys", UENO_OEDO_ID)

    du = G.nodes[u_bus]
    ds = G.nodes[u_oedo]
    geo_dist = haversine(du["lat"], du["lon"], ds["lat"], ds["lon"])
    print(f"[DBG] geodesic distance ≒ {geo_dist:.1f}m")

    if G.has_edge(u_bus, u_oedo):
        print("[DBG] direct walk edge exists bus -> station")
        print("   edge data:", G.edges[u_bus, u_oedo])
    else:
        print("[DBG] NO direct walk edge bus -> station")

    # 念のため station -> bus も
    if G.has_edge(u_oedo, u_bus):
        print("[DBG] direct walk edge exists station -> bus")
        print("   edge data:", G.edges[u_oedo, u_bus])
    else:
        print("[DBG] NO direct walk edge station -> bus")

if __name__ == "__main__":
    main()

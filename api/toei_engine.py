#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# toei_engine.py

# バス停情報 / Bus stop information
# https://api-public.odpt.org/api/v4/odpt:BusstopPole?odpt:operator=odpt.Operator:Toei
# [
#   {
#     "@id": "urn:ucode:_00001C0000000000000100000330C4F0",
#     "@type": "odpt:BusstopPole",
#     "title": {
#       "en": "Shinjuku-Itchōme (Shinjuku 1)",
#       "ja": "新宿一丁目(しんじゅくいっちょうめ)",
#       "ja-Hrkt": "しんじゅくいっちょうめ"
#     },
#     "dc:date": "2026-01-02T03:16:30+09:00",
#     "geo:lat": 35.687947,
#     "@context": "http://vocab.odpt.org/context_odpt_BusstopPole.jsonld",
#     "dc:title": "新宿一丁目(しんじゅくいっちょうめ)",
#     "geo:long": 139.713199,
#     "odpt:kana": "しんじゅくいっちょうめ",
#     "odpt:note": "新宿一丁目",
#     "owl:sameAs": "odpt.BusstopPole:Toei.ShinjukuItchome.711.3",
#     "odpt:operator": [
#       "odpt.Operator:Toei"
#     ],
#     "odpt:busroutePattern": [
#       "odpt.BusroutePattern:Toei.Shina97.24001.1",
#       "odpt.BusroutePattern:Toei.Shina97.24002.1",
#       "odpt.BusroutePattern:Toei.Shina97.24004.1",
#       "odpt.BusroutePattern:Toei.Shina97.24005.1"
#     ],
#     "odpt:busstopPoleNumber": "3",
#     "odpt:busstopPoleTimetable": [
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.06-100",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.06-160",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.06-170",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.06-301",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.13-100",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.13-160",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.13-170",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.21-100",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.21-160",
#       "odpt.BusstopPoleTimetable:Toei.Shina97.ShinjukuItchome.711.3.ShinjukuStationNishiguchi.21-170"
#     ]
#   },

# ##################################
# バス路線情報 / Bus route information
# https://api-public.odpt.org/api/v4/odpt:BusroutePattern?odpt:operator=odpt.Operator:Toei

# [
#   {
#     "@id": "urn:ucode:_00001C0000000000000100000322BD81",
#     "@type": "odpt:BusroutePattern",
#     "dc:date": "2026-01-02T03:16:30+09:00",
#     "@context": "http://vocab.odpt.org/context_odpt_BusroutePattern.jsonld",
#     "dc:title": "秋２６ 秋葉原駅前行",
#     "odpt:note": "秋２６:旧葛西橋→秋葉原駅前:64103:1",
#     "ug:region": {
#       "type": "LineString",
#       "coordinates": [
#         [139.84005, 35.675472],
#         [139.83926, 35.67558],
# ...
#         [139.77373, 35.699]
#       ]
#     },
#     "owl:sameAs": "odpt.BusroutePattern:Toei.Aki26.64103.1",
#     "odpt:pattern": "64103",
#     "odpt:busroute": "odpt.Busroute:Toei.Aki26",
#     "odpt:operator": "odpt.Operator:Toei",
#     "odpt:direction": "1",
#     "odpt:busstopPoleOrder": [
#       {
#         "odpt:note": "旧葛西橋",
#         "odpt:index": 1,
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.KyuKasaibashi.430.4"
#       },
#       {
#         "odpt:note": "東砂四丁目",
#         "odpt:index": 2,
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.HigashisunaYonchome.1295.2"
#       },
#       {
#         "odpt:note": "亀高橋",
#         "odpt:index": 3,
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.Kametakabashi.377.4"
#       },
#       {
#         "odpt:note": "北砂四丁目",
#         "odpt:index": 4,
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.KitasunaYonchome.412.2"
#       },
#       {
#         "odpt:note": "境川",
#         "odpt:index": 5,
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.Sakaigawa.565.3"
#       },
#       {
#         "odpt:note": "南砂一丁目",
#         "odpt:index": 6,
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.MinamisunaItchome.1474.2"
#       },
#       ...
#       {
#         "odpt:note": "秋葉原駅前",
#         "odpt:index": 24,
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.AkihabaraStation.27.4"
#       }
#     ]
#   },

# ##################################
# バス関連リアルタイム情報(VehiclePosition)
# https://api-public.odpt.org/api/v4/gtfs/realtime/ToeiBus
# 2 {                       <-- FeedEntity (データ本体)
#   1: "H993"               <-- id (エンティティID)
#   4 {                     <-- vehicle (VehiclePosition: バスの位置情報) ★ここから重要
#     1 {                   <-- trip (TripDescriptor: 運行情報)
#       1: "04801-2-85-170-1133"  <-- ★ trip_id (運行ID) 【超重要】
#       5: "002"            <-- route_id (系統ID)
#       6: 0                <-- direction_id (0: 往路/1: 復路 など)
#     }
#     8 {                   <-- vehicle (車両情報)
#       1: "H993"           <-- 車両番号
#     }
#     2 {                   <-- position (座標)
#       1: 0x420e6b39       <-- 緯度 (Hexデコードすると数値になる)
#       2: 0x430bcf1b       <-- 経度
#     }
#     3: 2                  <-- ★ current_stop_sequence (現在の停まり順) 【超重要】
#     7: "2630-02"          <-- ★ stop_id (次の/現在のバス停ID) 【超重要】
#     5: 1767926114         <-- timestamp
#   }
# }

# #########################
# バス停時刻表 / Bus stop timetable

# https://api-public.odpt.org/api/v4/odpt:BusstopPoleTimetable?odpt:operator=odpt.Operator:Toei
# [
#   {
#     "@id": "urn:ucode:_00001C00000000000001000003C04DCE",
#     "@type": "odpt:BusstopPoleTimetable",
#     "dc:date": "2026-01-02T03:16:30+09:00",
#     "@context": "http://vocab.odpt.org/context_odpt_BusstopPoleTimetable.jsonld",
#     "dc:title": "都０１（Ｔ０１）:青山学院中等部前:渋谷駅前:",
#     "odpt:note": "青山学院中等部前:0007-02:都０１（Ｔ０１）:渋谷駅前::09-173",
#     "owl:sameAs": "odpt.BusstopPoleTimetable:Toei.T01.AoyamagakuinChutobu.7.2.ShibuyaStation.09-173",
#     "odpt:busroute": "odpt.Busroute:Toei.T01",
#     "odpt:calendar": "odpt.Calendar:Specific.Toei.09-173",
#     "odpt:operator": "odpt.Operator:Toei",
#     "odpt:busstopPole": "odpt.BusstopPole:Toei.AoyamagakuinChutobu.7.2",
#     "odpt:busDirection": "odpt.BusDirection:Toei.ShibuyaStation",
#     "odpt:busstopPoleTimetableObject": [
#       {
#         "odpt:isMidnight": false,
#         "odpt:isNonStepBus": true,
#         "odpt:departureTime": "06:43",
#         "odpt:busroutePattern": "odpt.BusroutePattern:Toei.T01.8505.2",
#         "odpt:destinationSign": "渋谷駅前",
#         "odpt:busroutePatternOrder": 8,
#         "odpt:destinationBusstopPole": "odpt.BusstopPole:Toei.ShibuyaStation.636.8"
#       },
#       {
#         "odpt:isMidnight": false,
#         "odpt:isNonStepBus": true,
#         "odpt:departureTime": "06:58",
#         "odpt:busroutePattern": "odpt.BusroutePattern:Toei.T01.8505.2",
#         "odpt:destinationSign": "渋谷駅前",
#         "odpt:busroutePatternOrder": 8,
#         "odpt:destinationBusstopPole": "odpt.BusstopPole:Toei.ShibuyaStation.636.8"
#       },
#       {
#         "odpt:isMidnight": false,
#         "odpt:isNonStepBus": true,
#         "odpt:departureTime": "07:08",
#         "odpt:busroutePattern": "odpt.BusroutePattern:Toei.T01.8505.2",
#         "odpt:destinationSign": "渋谷駅前",
#         "odpt:busroutePatternOrder": 8,
#         "odpt:destinationBusstopPole": "odpt.BusstopPole:Toei.ShibuyaStation.636.8"
#       },

# バス時刻表 / Bus timetable
# https://api-public.odpt.org/api/v4/odpt:BusTimetable?odpt:operator=odpt.Operator:Toei

# [
#   {
#     "@id": "urn:ucode:_00001C0000000000000100000338376B",
#     "@type": "odpt:BusTimetable",
#     "dc:date": "2026-01-02T03:16:30+09:00",
#     "@context": "http://vocab.odpt.org/context_odpt_BusTimetable.jsonld",
#     "dc:title": "都０２ 大塚駅前行",
#     "odpt:note": "都０２:錦糸町駅前→大塚駅前:都０２ 大塚駅前行:32301:2:45-100",
#     "owl:sameAs": "odpt.BusTimetable:Toei.T02.32301-2-45-100-0821",
#     "odpt:calendar": "odpt.Calendar:Specific.Toei.45-100",
#     "odpt:operator": "odpt.Operator:Toei",
#     "odpt:busroutePattern": "odpt.BusroutePattern:Toei.T02.32301.2",
#     "odpt:busTimetableObject": [
#       {
#         "odpt:note": "錦糸町駅前:442:11",
#         "odpt:index": 1,
#         "odpt:isMidnight": false,
#         "odpt:arrivalTime": "08:21",
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.KinshichoStation.442.11",
#         "odpt:isNonStepBus": true,
#         "odpt:departureTime": "08:21",
#         "odpt:destinationSign": "大塚駅前"
#       },
#       {
#         "odpt:note": "錦糸公園前:441:1",
#         "odpt:index": 2,
#         "odpt:isMidnight": false,
#         "odpt:arrivalTime": "08:22",
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.KinshiKoen.441.1",
#         "odpt:isNonStepBus": true,
#         "odpt:departureTime": "08:22",
#         "odpt:destinationSign": "大塚駅前"
#       },
#       {
#         "odpt:note": "太平二丁目:2129:2",
#         "odpt:index": 3,
#         "odpt:isMidnight": false,
#         "odpt:arrivalTime": "08:23",
#         "odpt:busstopPole": "odpt.BusstopPole:Toei.TaiheiNichome.2129.2",
#         "odpt:isNonStepBus": true,
#         "odpt:departureTime": "08:23",
#         "odpt:destinationSign": "大塚駅前"
#       },
import json, argparse, math, sys, heapq, datetime, bisect
import os
import re # Added for ID parsing
import gc
import time
import networkx as nx
from collections import defaultdict
from datetime import datetime as dt_class # datetime.datetimeと競合しないようにalias
from google.transit import gtfs_realtime_pb2
from gtfs_loader import gtfs_repo
from google.transit import gtfs_realtime_pb2
from gtfs_loader import gtfs_repo

# -------------------- チューニング定数 --------------------
print("[INFO] toei_engine loaded: build=2025-12-29-realtime", flush=True)
BUS_RIDE_COST = 0.8
RAIL_RIDE_COST = 0.8
WALK_COST = 1.5
WALK_SPEED_M_PER_MIN = 80.0 

TRANSFER_PENALTY = 5.0

MAX_WALK_SEG_M = 1000.0

# 追加: 経路として許容する最大所要時間・総徒歩距離
MAX_TRAVEL_MIN = 240.0      # 例: 4 時間を上限
MAX_TOTAL_WALK_M = 3000.0   # 例: 総徒歩 3km まで

DEBUG_PHASE = os.getenv("DEBUG_PHASE", "0") == "1"


# -------------------- ユーティリティ --------------------
def _rss_mb() -> float:
    try:
        with open("/proc/self/statm", "r") as f:
            parts = f.read().strip().split()
        if not parts:
            return -1.0
        rss_pages = int(parts[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (rss_pages * page_size) / (1024.0 * 1024.0)
    except Exception:
        try:
            import resource
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return r / (1024.0 * 1024.0)
            return r / 1024.0
        except:
            return -1.0

def _mem_log(tag: str, extra: str = "") -> None:
    rss = _rss_mb()
    if extra:
        print(f"[MEM] {tag} rss={rss:.1f}MB {extra}", flush=True)
    else:
        print(f"[MEM] {tag} rss={rss:.1f}MB", flush=True)

def _phase_log(tag: str, extra: str = "") -> None:
    if not DEBUG_PHASE:
        return
    if extra:
        print(f"[PHASE] {tag} {extra}", flush=True)
    else:
        print(f"[PHASE] {tag}", flush=True)

def _file_size_bytes(path: str) -> int:
    try:
        return int(os.path.getsize(path))
    except Exception:
        return -1

def _line_norm(s: str) -> str:
    tbl = str.maketrans("０１２３４５６７８９　（）", "0123456789 ()")
    return (s or "").translate(tbl).replace(" ", "")

def _norm_line(s): return _line_norm(s)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))

def is_station_id(pid: str) -> bool:
    return isinstance(pid, str) and pid.startswith("odpt.Station:")

def is_toei(op):
    if isinstance(op, list): return any("Toei" in x for x in op)
    return isinstance(op, str) and "Toei" in op

def load_json(path):
    _phase_log("load_json begin", f"path={path}")
    t0 = time.perf_counter()
    size_b = _file_size_bytes(path)
    _mem_log("load_json begin", f"path={path} size={size_b}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dt = time.perf_counter() - t0
    
    if isinstance(data, list):
        n = len(data)
    elif isinstance(data, dict):
        n = len(data.get("result", [])) if isinstance(data.get("result"), list) else 1
    else:
        n = 1

    _mem_log("load_json end", f"sec={dt:.2f} items={n}")
    if isinstance(data, dict):
        if "result" in data and isinstance(data["result"], list):
            return data["result"]
        return [data]
    return data if isinstance(data, list) else [data]

def get_id(o): return o.get("owl:sameAs") or o.get("@id") or o.get("id")
def get_lat(o): return o.get("geo:lat")
def get_lon(o): return o.get("geo:long")
def time_str_to_min(t_str):
    if not t_str: return 99999
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def min_to_time_str(m):
    h = int(m // 60)
    mn = int(m % 60)
    return f"{h:02d}:{mn:02d}"



# -------------------- Path Chain Logic (Integer Index Based) --------------------
def _chain_new(chain_store, node, parent_idx):
    chain_store.append((node, parent_idx))
    return len(chain_store) - 1

def reconstruct_path_idx(chain_store, idx):
    path = []
    cur = idx
    while cur is not None:
        node, parent = chain_store[cur]
        path.append(node)
        cur = parent
    path.reverse()
    return path


# -------------------- [追加] 共通化した日付判定ロジック --------------------
def determine_day_type(target_date: datetime.date | datetime.datetime | str | None) -> str:
    """
    日付を受け取り、平日(weekday)/土曜(saturday)/休日(holiday) を判定して返す。
    japanese_holidays があれば祝日判定も行う。
    """
    d = None
    if target_date is None:
        d = datetime.date.today()
    elif isinstance(target_date, str):
        try:
            d = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            d = datetime.date.today()
    elif isinstance(target_date, datetime.datetime):
        d = target_date.date()
    elif isinstance(target_date, datetime.date):
        d = target_date
    else:
        d = datetime.date.today()

    weekday = d.weekday()

    # 祝日判定
    try:
        import japanese_holidays
        is_holiday = japanese_holidays.is_holiday(d)
    except ImportError:
        is_holiday = False

    if weekday == 6 or is_holiday:
        return "holiday"
    if weekday == 5:
        return "saturday"
    return "weekday"




# -------------------- 空間インデックス (Grid Index) --------------------
REF_LAT = 35.681236  # Tokyo Station
REF_LON = 139.767125
METERS_PER_DEG_LAT = 111_132.954
METERS_PER_DEG_LON = 91_387.818 

def to_local_meters(lat, lon):
    y = (lat - REF_LAT) * METERS_PER_DEG_LAT
    x = (lon - REF_LON) * METERS_PER_DEG_LON
    return x, y

class SpatialIndex:
    def __init__(self, G=None, cell_size_m=500.0):
        self.cell_size_m = cell_size_m
        self.grid = defaultdict(list)
        if G:
            self.build(G)

    def build(self, G):
        print(f"[INFO] Building SpatialIndex (cell={self.cell_size_m}m)...", flush=True)
        count = 0
        for n, d in G.nodes(data=True):
            if n[0] == "phys" and "lat" in d and "lon" in d:
                x, y = to_local_meters(d["lat"], d["lon"])
                cx = int(x // self.cell_size_m)
                cy = int(y // self.cell_size_m)
                self.grid[(cx, cy)].append((n, d["lat"], d["lon"]))
                count += 1
        print(f"[INFO] Indexed {count} phys nodes.", flush=True)

    def nearby_candidates(self, lat, lon, radius_m):
        x, y = to_local_meters(lat, lon)
        cx = int(x // self.cell_size_m)
        cy = int(y // self.cell_size_m)
        
        candidates = []
        range_val = int(math.ceil(radius_m / self.cell_size_m))
        
        for dx in range(-range_val, range_val + 1):
            for dy in range(-range_val, range_val + 1):
                cell = (cx + dx, cy + dy)
                for item in self.grid.get(cell, []):
                    candidates.append(item)
        return candidates

def pole_base(pid: str) -> str:
    # NOTE: With normalization removed, pole_base_index_* and finalize_indexes()
    # will effectively be non-merged indexes (harmless but less meaningful),
    # and are candidates for future cleanup if normalization is fully removed.
    return pid

# -------------------- 時刻表マネージャー (名寄せ強化版 + リアルタイム) --------------------
class TimetableManager:
    def __init__(self):
        # key: pole_id, value: { route_id: [{'dep': minutes, 'dest': dest_pole_id}, ...] }
        self.bus_departures_weekday = {}
        self.bus_departures_saturday = {}
        self.bus_departures_holiday = {}
        
        # ID-based indexes (pole_base -> [pole_id, ...])
        self.pole_base_index_weekday = defaultdict(list)
        self.pole_base_index_saturday = defaultdict(list)
        self.pole_base_index_holiday = defaultdict(list)
        
        self._resolved_pole_cache = {}
        
        self._debug_once = set()
        self._debug_counts = defaultdict(int)

        self.route_patterns_map = defaultdict(list) 
        self.pattern_stops_map = {}
        
        # key: station_id, value: [ {dep, arr, next_sta, train_id} ]
        self.train_patterns_weekday = {}
        self.train_patterns_weekend = {}
        
        self.name_to_pids = defaultdict(list)
        self.realtime_delays = {} # Train location delays

        # === Realtime Extensions ===
        self.bus_realtime_delays = defaultdict(float) # route_id -> avg_delay_min
        self.latest_bus_positions = [] # Store raw realtime bus data
        self.train_status_text = {} # railway_id -> text
        self.train_service_suspended = set() # railway_id
        self.latest_train_info = [] # Store raw realtime train info
        self.latest_gtfsrt_vehicles = {} # vehicle_id -> {lat, lon, timestamp, etc}

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Fail-safe initializations for backward compatibility of pickle
        if not hasattr(self, "bus_realtime_delays"): self.bus_realtime_delays = defaultdict(float)
        if not hasattr(self, "latest_bus_positions"): self.latest_bus_positions = []
        if not hasattr(self, "train_status_text"): self.train_status_text = {}
        if not hasattr(self, "train_service_suspended"): self.train_service_suspended = set()
        if not hasattr(self, "latest_train_info"): self.latest_train_info = []
        if not hasattr(self, "latest_gtfsrt_vehicles"): self.latest_gtfsrt_vehicles = {}
        if not hasattr(self, "pattern_stops_map"): self.pattern_stops_map = {}
        
        need_rebuild_indexes = False
        if (not hasattr(self, "pole_base_index_weekday")) or (self.pole_base_index_weekday is None): need_rebuild_indexes = True
        if need_rebuild_indexes:
            self.pole_base_index_weekday = defaultdict(list)
            self.pole_base_index_saturday = defaultdict(list)
            self.pole_base_index_holiday = defaultdict(list)

        if (not hasattr(self, "_resolved_pole_cache")) or (self._resolved_pole_cache is None):
            self._resolved_pole_cache = {}

        has_any_bus_data = False
        if hasattr(self, "bus_departures_weekday") and self.bus_departures_weekday: has_any_bus_data = True
        
        if has_any_bus_data:
            self.finalize_indexes()

    def update_train_info_text(self, info_list):
        self.train_status_text.clear()
        self.train_service_suspended.clear()
        for info in info_list:
            railway_id = info.get("odpt:railway")
            text_obj = info.get("odpt:trainInformationText") or {}
            text = text_obj.get("ja", "")
            if not railway_id: continue
            
            self.train_status_text[railway_id] = text
            if "見合わせ" in text or "運休" in text:
                self.train_service_suspended.add(railway_id)

    def _guess_railway_id(self, station_id):
        # odpt.Station:Toei.Asakusa.Oshiage -> odpt.Railway:Toei.Asakusa
        if "Toei." in station_id:
            parts = station_id.split(".")
            if len(parts) >= 2:
                return f"odpt.Railway:Toei.{parts[1]}"
        return None

    def debug_once(self, key, msg):
        self._debug_counts[key] += 1
        if key not in self._debug_once:
            self._debug_once.add(key)
            print(msg, flush=True)
            
    def _build_pole_base_index_for(self, departures_dict, out_index):
        out_index.clear()
        for pid in departures_dict.keys():
            out_index[pole_base(pid)].append(pid)

    def finalize_indexes(self):
        self._build_pole_base_index_for(self.bus_departures_weekday, self.pole_base_index_weekday)
        self._build_pole_base_index_for(self.bus_departures_saturday, self.pole_base_index_saturday)
        self._build_pole_base_index_for(self.bus_departures_holiday, self.pole_base_index_holiday)
        print("[INFO] Bus ID-based indexes finalized.", flush=True)
        
    def update_delays(self, train_data_list):
        count = 0
        for t in train_data_list:
            t_num = t.get("odpt:trainNumber")
            delay = t.get("odpt:delay", 0)
            if t_num:
                self.realtime_delays[t_num] = delay
                count += 1

    def get_delays_snapshot(self):
        return self.realtime_delays.copy()

    def load_bus_route_patterns(self, json_path):
        data = load_json(json_path)
        count = 0
        seen = defaultdict(set)
        for entry in data:
            route_id = entry.get("odpt:busroute")
            pattern_id = entry.get("odpt:busroutePattern") or entry.get("owl:sameAs")
            orders = entry.get("odpt:busstopPoleOrder") or []
            try: orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
            except: pass
            seq = [o.get("odpt:busstopPole") for o in orders if o.get("odpt:busstopPole")]
            if not route_id or not seq: continue
            if pattern_id:
                self.pattern_stops_map[pattern_id] = seq
            key = tuple(seq)
            if key in seen[route_id]:
                continue
            seen[route_id].add(key)
            if route_id not in self.route_patterns_map: self.route_patterns_map[route_id] = []
            self.route_patterns_map[route_id].append(seq)
            count += 1
        del data
        gc.collect()
        _mem_log("load_bus_route_patterns done", f"entries={count}")

    def load_bus_timetables(self, json_path):
        _phase_log("load_bus_timetables begin", f"path={json_path}")
        data = load_json(json_path)
        count = 0
        for entry in data:
            pole_id = entry.get("odpt:busstopPole")
            route_id = entry.get("odpt:busroute")
            calendar = entry.get("odpt:calendar", "")
            if not pole_id: continue
            times = []
            for obj in entry.get("odpt:busstopPoleTimetableObject", []):
                dep = obj.get("odpt:departureTime")
                dest = obj.get("odpt:destinationBusstopPole")
                # In our dataset, odpt:trip is missing. We use odpt:busroutePattern as a proxy for identification.
                pattern_id = obj.get("odpt:busroutePattern")
                if dep:
                    times.append({ "dep": time_str_to_min(dep), "dest": dest, "trip": pattern_id })
            times.sort(key=lambda x: x["dep"])
            if not times: continue

            targets = []
            is_wk = ("Weekday" in calendar or calendar.endswith("-170") or calendar.endswith("-174"))
            is_sat = ("Saturday" in calendar or calendar.endswith("-160"))
            is_hol = ("Holiday" in calendar or calendar.endswith("-100") or calendar.endswith("-109"))

            if is_wk: targets.append(self.bus_departures_weekday)
            if is_sat: targets.append(self.bus_departures_saturday)
            if is_hol: targets.append(self.bus_departures_holiday)
            
            for target_dict in targets:
                if pole_id not in target_dict: target_dict[pole_id] = {}
                if route_id not in target_dict[pole_id]: target_dict[pole_id][route_id] = []
                target_dict[pole_id][route_id].extend(times)
            count += 1
        
        del data
        gc.collect()
        for d in [self.bus_departures_weekday, self.bus_departures_saturday, self.bus_departures_holiday]:
            for pid in d:
                for rid in d[pid]:
                    d[pid][rid].sort(key=lambda x: x["dep"])
        self.finalize_indexes()
        _phase_log("load_bus_timetables end", f"entries={count}")

    def load_train_timetables(self, json_path):
        _phase_log("load_train_timetables begin", f"path={json_path}")
        data = load_json(json_path)
        count = 0
        for entry in data:
            train_num = entry.get("odpt:trainNumber")
            calendar = entry.get("odpt:calendar", "")
            objs = entry.get("odpt:trainTimetableObject", [])
            target_dict = self.train_patterns_weekend
            if "Weekday" in calendar: target_dict = self.train_patterns_weekday

            prev = None
            for obj in objs:
                sid = obj.get("odpt:departureStation") or obj.get("odpt:arrivalStation")
                if not sid: continue
                dep_str = obj.get("odpt:departureTime")
                arr_str = obj.get("odpt:arrivalTime")

                if prev:
                    prev_sid, prev_dep_str = prev
                    if prev_sid and sid:
                        if prev_dep_str and arr_str:
                            real_dep = time_str_to_min(prev_dep_str)
                            real_arr = time_str_to_min(arr_str)
                            if real_dep < 99999 and real_arr < 99999 and real_arr >= real_dep:
                                if prev_sid not in target_dict: target_dict[prev_sid] = []
                                target_dict[prev_sid].append({
                                    "dep": real_dep, 
                                    "arr": real_arr, 
                                    "next_sta": sid,
                                    "train_num": train_num
                                })
                next_dep_str = dep_str if dep_str else arr_str
                prev = (sid, next_dep_str)
            count += 1
        for d in [self.train_patterns_weekday, self.train_patterns_weekend]:
            for sid in d: d[sid].sort(key=lambda x: x["dep"])
        _phase_log("load_train_timetables end", f"entries={count}")

    def build_name_index(self, G):
        print("[INFO] Building Name Index for fuzzy matching...", flush=True)
        count = 0
        for n, d in G.nodes(data=True):
            if n[0] == "phys":
                name = d.get("name")
                pid = n[1]
                if name:
                    self.name_to_pids[name].append(pid)
                    count += 1
        print(f"[INFO] Index built. Total {count} nodes.", flush=True)

    def get_next_bus_departure(self, pole_id, route_id, current_time_min, pole_name=None, day_type="weekday", target_pole_id=None, debug=False):
        if not debug:
            dbg_env = os.getenv("DEBUG_BUS", "0")
            if dbg_env == "1":
                debug = True
            elif dbg_env != "0" and pole_name and dbg_env in pole_name:
                debug = True

        if day_type == "saturday":
            target_dict = self.bus_departures_saturday
        elif day_type == "holiday":
            target_dict = self.bus_departures_holiday
        else:
            target_dict = self.bus_departures_weekday

        delay_min = self.bus_realtime_delays.get(route_id, 0.0)
        effective_search_time = current_time_min - delay_min

        routes_dict = target_dict.get(pole_id)
        if not routes_dict:
            return None, None

        candidate_trips = routes_dict.get(route_id)
        if not candidate_trips:
            return None, None

        def is_valid_trip(trip, rid, board_pole_id):
            if not target_pole_id:
                return True
            dest_id = trip.get("dest")
            pattern_id = trip.get("trip")
            if pattern_id and pattern_id in self.pattern_stops_map:
                stops = self.pattern_stops_map[pattern_id]
                # Policy: when destination is missing or not in the pattern sequence, allow the trip.
                if not dest_id or dest_id not in stops:
                    return True
                if board_pole_id not in stops:
                    return True
                b = stops.index(board_pole_id)
                d = stops.index(dest_id)
                if d < b:
                    return False
                # Policy: if target stop is not in the pattern sequence, treat it as invalid.
                if target_pole_id not in stops:
                    return False
                t = stops.index(target_pole_id)
                return b <= t <= d

            patterns = self.route_patterns_map.get(rid) or []
            if not patterns:
                return True

            any_directional_pattern = False
            for stops in patterns:
                if board_pole_id not in stops:
                    continue
                if dest_id not in stops:
                    continue
                b = stops.index(board_pole_id)
                d = stops.index(dest_id)
                if d < b:
                    continue

                any_directional_pattern = True

                if target_pole_id not in stops:
                    continue
                t = stops.index(target_pole_id)
                if b <= t <= d:
                    return True

            if any_directional_pattern:
                return False
            return True

        L = len(candidate_trips)
        lo, hi = 0, L
        while lo < hi:
            mid = (lo + hi) // 2
            if candidate_trips[mid]["dep"] < effective_search_time:
                lo = mid + 1
            else:
                hi = mid

        for i in range(lo, L):
            trip = candidate_trips[i]
            if is_valid_trip(trip, route_id, pole_id):
                return trip["dep"] + delay_min, trip.get("trip")

        return None, None

    def get_future_bus_trips(self, pole_id, route_id, current_time_min, limit=10, pole_name=None, day_type="weekday", target_pole_id=None, debug=False):
        delay_min = self.bus_realtime_delays.get(route_id, 0.0)
        effective_search_time = current_time_min - delay_min

        if not debug:
            debug = os.getenv("DEBUG_BUS") == "1"

        if day_type == "saturday":
            target_dict = self.bus_departures_saturday
        elif day_type == "holiday":
            target_dict = self.bus_departures_holiday
        else:
            target_dict = self.bus_departures_weekday

        routes_dict = target_dict.get(pole_id)
        if not routes_dict:
            return []

        candidate_trips = routes_dict.get(route_id)
        if not candidate_trips:
            return []

        def is_valid_trip(trip, rid, board_pole_id):
            if not target_pole_id:
                return True
            dest_id = trip.get("dest")
            if not dest_id:
                return True
            patterns = self.route_patterns_map.get(rid) or []
            if not patterns:
                return True

            for stops in patterns:
                if board_pole_id not in stops or dest_id not in stops:
                    continue
                b = stops.index(board_pole_id)
                d = stops.index(dest_id)
                if d < b:
                    continue
                if target_pole_id not in stops:
                    continue
                t = stops.index(target_pole_id)
                if b <= t <= d:
                    return True
            return True

        L = len(candidate_trips)
        lo, hi = 0, L
        while lo < hi:
            mid = (lo + hi) // 2
            if candidate_trips[mid]["dep"] < effective_search_time:
                lo = mid + 1
            else:
                hi = mid

        out = []
        for i in range(lo, L):
            trip = candidate_trips[i]
            if is_valid_trip(trip, route_id, pole_id):
                out.append(trip)
                if len(out) >= limit:
                    break
        return out

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min, day_type="weekday", delays_snapshot=None):
        # 1. Suspension Check
        railway_id = self._guess_railway_id(current_sta)
        if railway_id and railway_id in self.train_service_suspended:
            return None # Line suspended

        target_dict = self.train_patterns_weekday if day_type == "weekday" else self.train_patterns_weekend
        trains = target_dict.get(current_sta)
        if not trains: return None
        
        delays_source = delays_snapshot if delays_snapshot is not None else self.realtime_delays
        
        # 2. Status Text Fallback Check
        status_delay_penalty = 0.0
        if railway_id:
            text = self.train_status_text.get(railway_id, "")
            if "遅延" in text:
                 # If explicit delay data is missing but text says delay, apply penalty
                 status_delay_penalty = 10.0

        for t in trains:
            base_dep = t["dep"]
            base_arr = t["arr"]
            
            # Numeric delay from odpt:Train
            delay_sec = delays_source.get(t["train_num"], 0)
            delay_min = delay_sec / 60.0
            
            # If no numeric delay but status says delay, use penalty
            if delay_min == 0 and status_delay_penalty > 0:
                delay_min = status_delay_penalty

            actual_dep = base_dep + delay_min
            actual_arr = base_arr + delay_min

            if actual_dep >= current_time_min and t["next_sta"] == next_sta:
                return actual_arr
        return None

# -------------------- グラフ構築 --------------------
def build_graph(busstop_poles_path, busroute_patterns_path, stations_path, railways_path, walk_radius=300):
    _phase_log("build_graph begin", f"walk_radius={walk_radius}")
    G = nx.DiGraph()
    poles = load_json(busstop_poles_path)
    phys = {}
    for p in poles:
        pid = get_id(p)
        lat, lon = get_lat(p), get_lon(p)
        if pid and lat and lon:
            phys[pid] = {"lat": float(lat), "lon": float(lon), "name": p.get("dc:title") or pid}
    stations = load_json(stations_path)
    for s in stations:
        if not is_toei(s.get("odpt:operator")): continue
        sid = get_id(s)
        lat, lon = get_lat(s), get_lon(s)
        if sid and lat and lon:
            phys[sid] = {"lat": float(lat), "lon": float(lon), "name": s.get("dc:title") or sid}
    for pid, d in phys.items():
        G.add_node(("phys", pid), **d, kind="phys")

    def ensure_line_node(phys_id, line_id, display_name, mode, real_route_id=None):
        n = ("line", phys_id, line_id)
        if n not in G:
            base = phys[phys_id]
            G.add_node(n, lat=base["lat"], lon=base["lon"], name=f"{base['name']}@{display_name}",
                       line=line_id, kind="line", disp=display_name, norm=_norm_line(display_name), 
                       mode=mode, route_id=real_route_id)
            G.add_edge(("phys", phys_id), n, w=TRANSFER_PENALTY, etype="board")
            G.add_edge(n, ("phys", phys_id), w=0, etype="alight")
        return n

    patterns = load_json(busroute_patterns_path)
    for pat in patterns:
        if not is_toei(pat.get("odpt:operator")): continue
        route_id = pat.get("odpt:busroute")
        pattern_id = get_id(pat)
        full_title = pat.get("dc:title") or "???"
        disp = full_title
        line_id = f"buspat:{pattern_id}" if pattern_id else route_id
        orders = pat.get("odpt:busstopPoleOrder") or []
        try: orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
        except: pass
        seq = [o.get("odpt:busstopPole") for o in orders if o.get("odpt:busstopPole") in phys]
        
        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, line_id, disp, "bus", route_id)
            nb = ensure_line_node(b, line_id, disp, "bus", route_id)
            if not G.has_edge(na, nb):
                G.add_edge(na, nb, w=BUS_RIDE_COST, etype="ride", line=line_id, mode="bus")

    railways = load_json(railways_path)
    for rw in railways:
        if not is_toei(rw.get("odpt:operator")): continue
        line_id = get_id(rw)
        disp = rw.get("dc:title") or line_id
        orders = rw.get("odpt:stationOrder") or []
        try: orders = sorted(orders, key=lambda x: x.get("odpt:index", 0))
        except: pass
        seq = [o.get("odpt:station") for o in orders if o.get("odpt:station") in phys]
        for a, b in zip(seq, seq[1:]):
            na = ensure_line_node(a, line_id, disp, "rail")
            nb = ensure_line_node(b, line_id, disp, "rail")
            G.add_edge(na, nb, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail")
            G.add_edge(nb, na, w=RAIL_RIDE_COST, etype="ride", line=line_id, mode="rail")

    print("[INFO] Adding ConnectingStation edges...", flush=True)
    count_connect = 0
    for s in stations:
        if not is_toei(s.get("odpt:operator")): continue
        sid = get_id(s)
        connects = s.get("odpt:connectingStation")
        if connects:
            if isinstance(connects, str): connects = [connects]
            u = ("phys", sid)
            if u not in G: continue
            
            for target in connects:
                v = ("phys", target)
                if G.has_node(v):
                    if G.has_edge(u, v): continue
                    
                    d_u = G.nodes[u]
                    d_v = G.nodes[v]
                    dist = haversine(d_u.get("lat",0), d_u.get("lon",0), d_v.get("lat",0), d_v.get("lon",0))
                    
                    minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                    w = WALK_COST * minutes
                    G.add_edge(u, v, w=w, etype="walk", meters=dist)
                    G.add_edge(v, u, w=w, etype="walk", meters=dist)
                    count_connect += 1
    print(f"[INFO] Added {count_connect} connecting station edges.", flush=True)

    _phase_log("connect_walk_edges_phys begin", f"radius_m={walk_radius}")
    connect_walk_edges_phys(G, radius_m=walk_radius)
    _phase_log("connect_walk_edges_phys end")
    
    del poles
    del stations
    del patterns
    del railways
    import gc
    gc.collect()
    _mem_log("build_graph done")
    _phase_log("build_graph end")
    return G

def connect_walk_edges_phys(G, radius_m=300):
    si = SpatialIndex(G)
    phys_nodes = []
    for n, d in G.nodes(data=True):
        if n[0] != "phys": continue
        phys_nodes.append((n, d))

    for u, du in phys_nodes:
        candidates = si.nearby_candidates(du["lat"], du["lon"], radius_m)
        for v, lat, lon in candidates:
            if u == v: continue
            dist = haversine(du["lat"], du["lon"], lat, lon)
            if dist <= radius_m:
                 minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                 w = WALK_COST * minutes
                 if not G.has_edge(u, v):
                     G.add_edge(u, v, w=w, etype="walk", meters=dist)
                 if not G.has_edge(v, u):
                     G.add_edge(v, u, w=w, etype="walk", meters=dist)

def get_virtual_connections(G, lat, lon, name="目的地", walk_radius=300, spatial_index=None):
    dest_id = f"dest:{lat:.6f},{lon:.6f}"
    dest_node = ("phys", dest_id)
    connections = []
    
    if spatial_index:
        candidates = spatial_index.nearby_candidates(lat, lon, walk_radius)
        for nid, nlat, nlon in candidates:
             dist = haversine(lat, lon, nlat, nlon)
             if dist <= walk_radius:
                 minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                 w = WALK_COST * minutes
                 connections.append((nid, w, dist))
    else:
        for n, d in G.nodes(data=True):
            if n[0] != "phys": continue
            dist = haversine(lat, lon, d.get("lat"), d.get("lon"))
            if dist <= walk_radius:
                minutes = max(1.0, dist / WALK_SPEED_M_PER_MIN)
                w = WALK_COST * minutes
                connections.append((n, w, dist))
                
    return dest_node, connections

def nearest_phys(G, lat, lon, station_only=False, spatial_index=None):
    best, bestd = None, 1e30
    candidates = []
    if spatial_index:
        raw_candidates = spatial_index.nearby_candidates(lat, lon, 1000)
        candidates = [(nid, G.nodes[nid]) for nid,_,_ in raw_candidates]
        if not candidates:
             candidates = G.nodes(data=True)
    else:
        candidates = G.nodes(data=True)

    for n, d in candidates:
        if n[0] != "phys": continue
        if station_only and not is_station_id(n[1]): continue
        dist = haversine(lat, lon, d["lat"], d["lon"])
        if dist < bestd: best, bestd = n, dist
    return best, bestd

# -------------------- 共通ロジック: 時間計算ヘルパー --------------------
def advance_time(G, tm, u, v, curr_time, day_type="weekday", delays_snapshot=None, **kwargs):
    if G.has_edge(u, v):
        edge = G.edges[u, v]
        etype = edge.get("etype")
        meters = edge.get("meters", 0)
    else:
        return curr_time 

    if etype == "walk":
        mm = meters if meters and meters > 0 else 1.0
        return curr_time + (mm / WALK_SPEED_M_PER_MIN)

    if etype == "board":
        node = v if v[0] == "line" else u
        mode = G.nodes[node].get("mode")

        if mode == "bus":
            route_id = G.nodes[node].get("route_id")
            stop_name = G.nodes[u].get("name")
            target_pid = kwargs.get("target_pole_id")

            dep, _ = tm.get_next_bus_departure(
                u[1], route_id, curr_time,
                pole_name=stop_name,
                day_type=day_type,
                target_pole_id=target_pid
            )
            if dep is None:
                return None
            return dep
        elif mode == "rail":
            return curr_time + 2.0
        return curr_time

    if etype == "ride":
        mode = edge.get("mode")
        if mode == "rail":
            arr = tm.get_next_train_arrival(u[1], v[1], curr_time, day_type=day_type, delays_snapshot=delays_snapshot)
            return arr
        elif mode == "bus":
            if meters > 0:
                return curr_time + (meters / 250.0) + 0.8
            else:
                return curr_time + 2.5
        return curr_time

    if etype in ("alight", "xfer"):
        return curr_time + 1.0

    return curr_time

# -------------------- 共通ロジック: セグメント詳細化 --------------------
def path_to_coords(G, path):
    points = []
    for u in path:
        if u[0] == "phys" and str(u[1]).startswith("dest:"):
            try:
                parts = str(u[1]).split(":")[1].split(",")
                lat, lon = float(parts[0]), float(parts[1])
                points.append([lat, lon])
            except: pass
        elif u in G.nodes:
            d = G.nodes[u]
            points.append([d["lat"], d["lon"]])
    return points

def search_best_routes_once(G, tm, a_phys, mode="cost", start_time="10:00", limit=5, target_date_str=None, target_node=None, day_type=None, virtual_dest_connections=None, target_coords=None):
    d = datetime.date.today()
    if target_date_str:
        try:
            d = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
        except:
            d = datetime.date.today()
    
    # Check if 'now' is defined globally (it seems used in original code). 
    # Original code: base_date = d.replace(hour=now.hour, minute=now.minute, second=0, microsecond=0)
    # 'now' is not passed in. Assuming 'datetime.datetime.now()' was meant or 'now' global exists?
    # Checking file content again, I don't see 'now' defined in this scope.
    # But line 958 used 'now.hour'. It might be a bug or 'now' is a global variable (unlikely good practice).
    # I will replace 'now' with 'datetime.datetime.now()' to be safe.
    
    now_dt = datetime.datetime.now()
    base_date = datetime.datetime.combine(d if isinstance(d, datetime.date) else d.date(), datetime.time(now_dt.hour, now_dt.minute))

    h, m = map(int, start_time.split(":"))
    start_dt = base_date.replace(hour=h, minute=m, second=0, microsecond=0)
    
    # メインの探索ロジック(search_best_routes)を呼び出し
    # ここで graph探索(Dijkstra/A*) が走る
    candidates = search_best_routes(G, tm, a_phys, mode, start_time, limit, start_dt, target_node=target_node, day_type=day_type, virtual_dest_connections=virtual_dest_connections, target_coords=target_coords)
    
    # 探索結果があれば、メタデータ（出発日時、提案タイプなど）を付与して返す
    if candidates:
        for cand in candidates:
            cand["departure_date"] = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
            cand["is_future_suggestion"] = False
        return candidates
    
    # 候補が見つからなかった場合は空リストを返す
    return []

def search_best_routes(G, tm, a_phys, mode="cost", start_time="10:00", limit=5, target_date=None, target_node=None, day_type=None, virtual_dest_connections=None, target_coords=None):
    """
    指定された出発地(a_phys)から目的地(b_phys)までの経路を探索し、候補リストを返す関数。
    
    Parameters:
    -----------
    G : networkx.DiGraph
        交通ネットワークグラフ (物理ノードと論理ノード、エッジを含む)
    tm : TimetableManager
        時刻表データの管理クラス。バス・電車の時刻取得に使用。
    a_phys : tuple ("phys", str)
        出発地の物理ノードID
    b_phys : tuple ("phys", str)
        目的地の物理ノードID (デフォルトのターゲット)
    mode : str
        探索モード。"cost" (運賃・楽さ重視) または "time"/"fast" (所要時間重視)
    start_time : str
        出発時刻の文字列表現 ("HH:MM")
    limit : int
        返す経路候補の最大数
    target_date : datetime, optional
        探索基準日。曜日判定に使用される。指定がない場合は現在日時。
    target_node : tuple, optional
        探索上の正確なターゲットノード。b_physと同じことが多いが、特定バス停など詳細指定がある場合に利用。
    day_type : str, optional
        "weekday", "saturday", "holiday" のいずれか。指定がない場合は target_date から自動判定。
    virtual_dest_connections : list, optional
        任意の座標地点を目的地とする場合の、最寄りバス停/駅からの仮想接続エッジリスト。
    target_coords : tuple (lat, lon), optional
        目的地の緯度経度。ヒューリスティック計算などで使用。

    Returns:
    --------
    list of dict
        経路候補のリスト。各辞書は以下のキーを持つ:
        - "id": 候補のID (Fastest, Comfort-1 など)
        - "lines": 利用する路線名のリスト
        - "total_time": 所要時間(分)
        - "arrival_time": 到着時刻文字列
        - "steps": 詳細な移動行程セグメントのリスト
        - "path": 探索されたノードのリスト
        - "points": 地図描画用の座標点リスト
        ...など
    """
    # 1. 日付・曜日の設定
    if target_date is None:
        target_date = datetime.datetime.now()
    if day_type is None:
        day_type = determine_day_type(target_date)
    
    candidates = []
    # 遅延情報のスナップショットを取得 (探索中盤で遅延情報が変わると整合性が取れなくなるため固定化)
    delays_snapshot = tm.get_delays_snapshot()

    # 2. 探索モードによる分岐
    if mode == "time" or mode == "fast":
        # 時間優先モード (Fastest Path)
        # ダイクストラ法ベースで最短時間の経路を1つだけ探索
        arr_min, path = find_fastest_path(G, tm, a_phys, target_node, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections, target_coords=target_coords)
        if path:
            # 時刻表に基づいて到着時刻を再計算・検証
            real_arr = calculate_real_arrival_time(G, tm, path, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
            if real_arr is None:
                path = None 

        if path:
            # 経路が見つかった場合、詳細セグメント(UI用データ)を生成
            segs = segments_detailed(G, path, tm, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
            lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
            start_min = time_str_to_min(start_time)
            duration = int(arr_min - start_min)
            num_rides = sum(1 for s in segs if s["kind"] in ("bus", "rail"))
            walk_dist = sum(s["meters"] for s in segs if s["kind"] == "walk")

            candidates.append({
                "id": "Fastest",
                "lines": lines,
                "total_time": duration,
                "arrival_time": min_to_time_str(arr_min),
                "steps": segs,
                "score_label": f"{duration}分",
                "cost_score": 0.0,
                "walk_m": walk_dist,
                "path": path,
                "points": path_to_coords(G, path),
                "total": duration,
                "transfers": max(0, num_rides - 1),
                "rides": num_rides,
                "walks": int(walk_dist),
                "boards": num_rides,
            })
    else:
        # コスト/楽さ優先モード (Comfort Path)
        # A*探索などで複数の経路候補をジェネレータとして取得
        path_gen = find_paths_generator(G, tm, a_phys, target_node, start_time, day_type=day_type, max_search=30000, max_visited=100000, max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections, target_coords=target_coords)
        valid_count = 0
        for cand in path_gen:
            path = cand["path"]
            # 各候補について到着時刻を計算
            real_arr = calculate_real_arrival_time(G, tm, path, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
            if real_arr is not None:
                # 詳細情報の構築
                segs = segments_detailed(G, path, tm, start_time, day_type=day_type, delays_snapshot=delays_snapshot, virtual_dest_connections=virtual_dest_connections)
                lines = list(dict.fromkeys([s["title"] for s in segs if s["kind"] in ("bus", "rail")]))
                start_min = time_str_to_min(start_time)
                duration = int(real_arr - start_min)
                num_rides = sum(1 for s in segs if s["kind"] in ("bus", "rail"))
                
                candidates.append({
                    "id": f"Comfort-{valid_count+1}",
                    "lines": lines,
                    "total_time": duration,
                    "arrival_time": min_to_time_str(real_arr),
                    "steps": segs,
                    "score_label": f"楽さ {cand['cost']:.1f} (所要{duration}分)",
                    "cost_score": cand['cost'],
                    "walk_m": cand['walk_m'],
                    "path": path,
                    "points": path_to_coords(G, path),
                    "total": int(cand['cost']),
                    "transfers": max(0, num_rides - 1),
                    "rides": num_rides,
                    "walks": int(cand['walk_m']),
                    "boards": num_rides,
                })
                valid_count += 1
                if valid_count >= limit: break
    return candidates

def find_paths_generator(G, tm, start_node, target_node, start_time_str="10:00", day_type="weekday", max_search=30000, max_visited=15000, max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=None, time_limit_sec=15.0, virtual_dest_connections=None, target_coords=None):
    import time
    _mem_log("find_paths_generator start")
    start_clock = time.monotonic()
    start_min = time_str_to_min(start_time_str)

    t_lat, t_lon = None, None
    if target_coords: t_lat, t_lon = target_coords
    else:
        try:
            t_lat = G.nodes[target_node]["lat"]
            t_lon = G.nodes[target_node]["lon"]
        except: pass

    def heuristic(n):
        if n == target_node: return 0.0
        if t_lat is None: return 0.0
        if n not in G: return 0.0
        d = G.nodes[n]
        dist = haversine(d.get("lat",0), d.get("lon",0), t_lat, t_lon)
        return dist / 400.0

    start_h = heuristic(start_node)
    
    g_score = {}
    chain_store = []
    start_idx = _chain_new(chain_store, start_node, None)
    pq = [(start_h, 0.0, start_node, 0.0, 0.0, start_min, start_idx)]
    
    g_score[(start_node, 0)] = 0.0

    target_goal_nodes = {target_node}

    best_cost = {}
    seen_logical_routes = set()
    yielded_count = 0
    visited_count = 0
    
    MAX_PQ = 250000
    MAX_GSCORE = 500000
    MAX_BEST = 500000

    while pq:
        if visited_count > 0 and visited_count % 100 == 0:
            if time.monotonic() - start_clock > time_limit_sec:
                print(f"[WARN] Search timeout {yielded_count} paths found. Visited {visited_count} nodes.", flush=True)
                _mem_log("search_timeout")
                return
            if len(pq) > MAX_PQ or len(g_score) > MAX_GSCORE or len(best_cost) > MAX_BEST:
                print(f"[WARN] Search structure too large. abort pq={len(pq)} g={len(g_score)} best={len(best_cost)}", flush=True)
                _mem_log("search_abort_size")
                return
                
            if visited_count % 500 == 0:
                 _mem_log("search tick", f"visited={visited_count} pq={len(pq)} g={len(g_score)} best={len(best_cost)} seen={len(seen_logical_routes)}")

        _, cost, u, total_walk_m, seg_walk_m, curr_time, chain_idx = heapq.heappop(pq)
        visited_count += 1
        if visited_count > max_visited: 
            _mem_log("search_max_visited")
            return

        if curr_time - start_min > max_travel_min: continue

        walk_bucket = int(seg_walk_m // 25)
        state_key = (u, walk_bucket)
        
        prev_best = best_cost.get(state_key)
        if prev_best is not None and cost >= prev_best: continue
        best_cost[state_key] = cost

        if u in target_goal_nodes:
            full_path = reconstruct_path_idx(chain_store, chain_idx)
            yield {"cost": cost, "path": full_path, "walk_m": total_walk_m}
            yielded_count += 1
            if yielded_count >= max_search:
                _mem_log("search_max_yield")
                return
            continue

        if virtual_dest_connections and target_node and target_node[0] == "phys" and str(target_node[1]).startswith("dest:"):
            for nid, vw, vmeters in virtual_dest_connections:
                if nid == u:
                    next_time_v = curr_time + (vmeters / WALK_SPEED_M_PER_MIN)
                    if next_time_v - start_min <= max_travel_min:
                        new_total_v = total_walk_m + vmeters
                        new_seg_v = seg_walk_m + vmeters
                        if new_total_v <= MAX_TOTAL_WALK_M and new_seg_v <= MAX_WALK_SEG_M:
                            new_cost_v = cost + vw
                            bucket_v = int(new_seg_v // 25)
                            key_v = (target_node, bucket_v)
                            if new_cost_v < g_score.get(key_v, float('inf')):
                                g_score[key_v] = new_cost_v
                                new_chain_idx = _chain_new(chain_store, target_node, chain_idx)
                                heapq.heappush(pq, (new_cost_v + heuristic(target_node), new_cost_v, target_node, new_total_v, new_seg_v, next_time_v, new_chain_idx))
                    break

        for v in G[u]:
            edge = G[u][v]
            w = edge.get("w", 0.0)
            meters = edge.get("meters", 0.0)
            next_time = advance_time(G, tm, u, v, curr_time, day_type, delays_snapshot)
            if next_time is None or next_time - start_min > max_travel_min: continue

            new_total_walk_m = total_walk_m
            new_seg_walk_m = seg_walk_m
            if edge.get("etype") == "walk":
                step_m = meters if meters > 0 else 1.0
                new_seg_walk_m += step_m
                if new_seg_walk_m > MAX_WALK_SEG_M: continue
                new_total_walk_m += step_m
                if new_total_walk_m > MAX_TOTAL_WALK_M: continue
            else:
                new_seg_walk_m = 0.0

            new_cost = cost + w
            new_bucket = int(new_seg_walk_m // 25)
            new_key = (v, new_bucket)
            if new_cost < g_score.get(new_key, float('inf')):
                g_score[new_key] = new_cost
                new_h = heuristic(v)
                new_chain_idx = _chain_new(chain_store, v, chain_idx)
                heapq.heappush(pq, (new_cost + new_h, new_cost, v, new_total_walk_m, new_seg_walk_m, next_time, new_chain_idx))
    _mem_log("find_paths_generator end")

def find_fastest_path(G, tm, start_node, target_node, start_time_str="10:00", day_type="weekday", max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=None, virtual_dest_connections=None, target_coords=None):
    import time
    start_clock = time.monotonic()
    
    start_min = time_str_to_min(start_time_str)
    
    chain_store = []
    start_idx = _chain_new(chain_store, start_node, None)
    
    pq = [(start_min, start_node, start_idx, 0.0, 0.0)]
    visited_time = {} 
    min_time = {}
    
    min_time[(start_node, 0)] = start_min
    
    target_pole_ids = set()
    def add_poles(pid):
        target_pole_ids.add(pid)

    if virtual_dest_connections:
        for nid,_,_ in virtual_dest_connections:
            if nid[0] == "phys": add_poles(nid[1])
    elif target_node and target_node[0] == "phys":
        add_poles(target_node[1])

    visited_count = 0
    MAX_VISITED = 100000 
    TIME_LIMIT_SEC = 15.0

    while pq:
        if visited_count > 0 and visited_count % 100 == 0:
            if time.monotonic() - start_clock > TIME_LIMIT_SEC:
                print(f"[WARN] Fastest path search timeout. Visited {visited_count}.", flush=True)
                return None, None
            if len(pq) > 250000 or len(visited_time) > 500000 or len(min_time) > 500000:
                print(f"[WARN] Search exploded. pq={len(pq)} visited={len(visited_time)} min={len(min_time)}", flush=True)
                return None, None
                
        curr_time, u, chain_idx, total_walk, seg_walk = heapq.heappop(pq)
        visited_count += 1
        if visited_count > MAX_VISITED: return None, None
        
        if curr_time - start_min > max_travel_min: continue
        
        if u == target_node:
            return curr_time, reconstruct_path_idx(chain_store, chain_idx)

        state = (u, int(seg_walk // 25))
        if state in visited_time and visited_time[state] <= curr_time: continue
        visited_time[state] = curr_time

        if virtual_dest_connections and u[0] == "phys" and target_node and str(target_node[1]).startswith("dest:"):
            for nid, vw, vmeters in virtual_dest_connections:
                if nid == u:
                    v_time = curr_time + (vmeters / WALK_SPEED_M_PER_MIN)
                    new_seg = seg_walk + vmeters
                    new_tot = total_walk + vmeters
                    if v_time - start_min <= max_travel_min and new_seg <= MAX_WALK_SEG_M and new_tot <= MAX_TOTAL_WALK_M:
                        n_bucket = int(new_seg // 25)
                        n_key = (target_node, n_bucket)
                        if v_time < min_time.get(n_key, float('inf')):
                            min_time[n_key] = v_time
                            new_chain_idx = _chain_new(chain_store, target_node, chain_idx)
                            heapq.heappush(pq, (v_time, target_node, new_chain_idx, new_tot, new_seg))
                    break

        for v in G[u]:
            edge = G[u][v]
            etype = edge.get("etype")
            meters = edge.get("meters", 0)
            next_time = advance_time(G, tm, u, v, curr_time, day_type, delays_snapshot, target_pole_id=None) 
            if next_time is None: continue

            if edge.get("etype") == "walk":
                step_m = meters if meters > 0 else 1.0
                new_seg = seg_walk + step_m
                if new_seg > MAX_WALK_SEG_M: continue
                new_tot = total_walk + step_m
                if new_tot > MAX_TOTAL_WALK_M: continue
            else:
                new_seg = 0.0
                new_tot = total_walk
            
            n_bucket = int(new_seg // 25)
            n_key = (v, n_bucket)
            if next_time < min_time.get(n_key, float('inf')):
                 min_time[n_key] = next_time
                 new_chain_idx = _chain_new(chain_store, v, chain_idx)
                 heapq.heappush(pq, (next_time, v, new_chain_idx, new_tot, new_seg))
    return None, None

def calculate_real_arrival_time(G, tm, path, start_time_str="10:00", day_type="weekday", max_search=30000, max_travel_min=MAX_TRAVEL_MIN, delays_snapshot=None, virtual_dest_connections=None):
    start_min = time_str_to_min(start_time_str)
    curr_time = start_min
    for i in range(len(path) - 1):
        u, v = path[i], path[i+1]
        edge = G.get_edge_data(u, v)
        if not edge and virtual_dest_connections:
             for nid, w, dist in virtual_dest_connections:
                 if nid == u and v[0] == "phys" and str(v[1]).startswith("dest:"):
                      edge = {"etype": "walk", "meters": dist}
        if not edge: return None
        
        target_pid = None
        if edge.get("etype") == "board" and G.nodes[v].get("mode") == "bus":
            if v[0] == "line":
                for j in range(i+1, len(path)-1):
                    u2, v2 = path[j], path[j+1]
                    if G.has_edge(u2, v2):
                         e2 = G.get_edge_data(u2, v2)
                         if e2.get("etype") == "alight":
                            target_pid = v2[1]
                            break

        if not G.has_edge(u, v) and edge.get("etype") == "walk":
             next_time = curr_time + (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
        else:
            next_time = advance_time(G, tm, u, v, curr_time, day_type, delays_snapshot, target_pole_id=target_pid)
            
        if next_time is None or next_time - start_min > max_travel_min: return None
        curr_time = next_time
    return curr_time

def segments_detailed(G, path, tm, start_time_str="10:00", day_type="weekday", delays_snapshot=None, virtual_dest_connections=None):
    """
    探索されたパス(ノード列)を解析し、UI表示用のセグメント(移動行程)のリストを生成する。
    
    処理の流れ:
    1. path (探索結果のノード列) を順に読み込む
    2. エッジの種類(etype)に応じて処理を分岐:
       - walk: 連続する徒歩区間を1つのセグメントにまとめる
       - board (乗車): 新しい乗車セグメントを開始する。
          - バスの場合はここで時刻表を検索し、具体的な出発時刻とTrip IDを確定させる。
          - 降車予定のバス停を先読みし、その便が本当に目的地に行くか(Directional Check)も行う。
       - ride (移動中): 乗車中のセグメントに通過停留所(stops)を追加していく。
       - alight (降車): 乗車セグメントを終了(flush)する。
    3. curr_time (現在時刻) をシミュレーションしながら進める
       - 徒歩: 距離 / 速度 で加算
       - バス/電車: 時刻表データがあればそれに合わせる、なければ概算で進める
    
    Note:
    - ここでの `trip_id` 取得は、あくまで「その時刻に乗れるはずの便」の推定である。
    - リアルタイム運行情報との紐付けキーとなるため、可能な限り正確なIDを取得しようとするが、
      遅延や運休などで実際の運行とズレる可能性がある。
    """
    segs = []
    print(
        f"[segments_detailed] start path_len={len(path)} start_time={start_time_str} day_type={day_type}",
        flush=True,
    )
    cur = None
    last_phys = None
    curr_time = time_str_to_min(start_time_str)

    def flush():
        """
        現在構築中のセグメント(cur)を確定させ、結果リスト(segs)に追加する処理
        """
        nonlocal cur
        if cur:
            if cur["kind"] == "walk":
                # 距離0や移動なしの徒歩セグメントは除外
                if cur.get("meters", 0) <= 0 or cur.get("from_") == cur.get("to"):
                    cur = None
                    return
                # 徒歩所要時間の計算 (距離 / 速度)
                cur["minutes"] = max(1, math.ceil(cur.get("meters", 0) / WALK_SPEED_M_PER_MIN))
            elif cur["kind"] in ("bus", "rail"):
                # 公共交通機関の所要時間計算
                if cur.get("arrival_time"):
                    # 時刻表時刻に基づく正確な時間
                    d = time_str_to_min(cur.get("departure_time"))
                    a = time_str_to_min(cur.get("arrival_time"))
                    cur["minutes"] = max(1, int(a - d))
                else:
                    # 時刻不明時は駅数x2分で概算
                    cur["minutes"] = max(1, int(cur.get("edges", 0) * 2.0))
            segs.append(cur)
            print(
                f"[segments_detailed] flush kind={cur.get('kind')} title={cur.get('title')} "
                f"from={cur.get('from_')} to={cur.get('to')} "
                f"dep={cur.get('departure_time')} arr={cur.get('arrival_time')} "
                f"minutes={cur.get('minutes')} stops={len(cur.get('stops', []))} "
                f"route_id={cur.get('route_id')} trip_id={cur.get('trip_id')}",
                flush=True,
            )
            cur = None

    # 「現在地」と「次の目的地」のペア
    for i, (u, v) in enumerate(zip(path, path[1:])):
        edge = G.get_edge_data(u, v)
        if not edge and virtual_dest_connections:
            for nid, w, dist in virtual_dest_connections:
                 if nid == u and v[0] == "phys" and str(v[1]).startswith("dest:"):
                      edge = {"etype": "walk", "meters": dist}
                      break
        if not edge: continue
        
        etype = edge.get("etype")
        if u[0] == "phys": last_phys = u

        if etype == "walk":
            print(f"[segments_detailed] edge[{i}] walk u={u} v={v}", flush=True)
            # 連続する徒歩エッジを一つのセグメントにまとめる
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
            # 徒歩速度で時間を加算(分)
            curr_time += (edge.get("meters", 0) / WALK_SPEED_M_PER_MIN)
            continue

        node = v if v[0] == "line" else (u if u[0] == "line" else None)
        if not node: continue
        line_disp = G.nodes[node].get("disp") or "???"
        mode = G.nodes[node].get("mode")

        if etype == "board":
            print(f"[segments_detailed] edge[{i}] board mode={mode} node={node}", flush=True)
            # 乗車開始: 待ち時間があればWaitセグメントを挟み、Rideセグメントを作る
            flush()
            from_name = G.nodes[last_phys]["name"] if last_phys else "???"
            origin_lat = G.nodes[last_phys].get("lat") if last_phys else None
            origin_lon = G.nodes[last_phys].get("lon") if last_phys else None
            
            curr_stops = [{"name": from_name, "is_origin": True, "lat": origin_lat, "lon": origin_lon, "id": last_phys[1] if last_phys else None}]
            
            phys_id = u[1]
            if mode == "bus":
                route_id = G.nodes[v].get("route_id")
                target_pid = None
                
                # パスを先読みして、降りるバス停(alight)を探す
                # これにより、乗車便がその降車バス停に停まるかどうかを判定(isValidTrip)できる
                if v[0] == "line":
                     for j in range(i + 1, len(path) - 1):
                        u2, v2 = path[j], path[j+1]
                        if G.has_edge(u2, v2):
                             e2 = G.get_edge_data(u2, v2)
                             if e2.get("etype") == "alight":
                                target_pid = v2[1]
                                break
                
                # 直近の出発便とTrip IDを取得する (Tuple return: dep, pattern_id)
                # Note: pattern_id is stored in "trip" field of timetable index
                search_time = int(curr_time)
                
                # print(f"[DEBUG] get_next_bus_departure START: route={route_id}, pole={phys_id}, target={target_pid}, time={search_time}")
                dep, pattern_id_found = tm.get_next_bus_departure(phys_id, route_id, search_time, pole_name=from_name, day_type=day_type, target_pole_id=target_pid)
                # print(f"[DEBUG] get_next_bus_departure RESULT: dep={dep}, pattern={pattern_id_found}")
                print(
                    f"[segments_detailed] board bus route_id={route_id} phys_id={phys_id} "
                    f"target_pid={target_pid} dep={dep} pattern_id={pattern_id_found}",
                    flush=True,
                )

                # Using robust logging instead of fallback
                if dep is None and target_pid is not None:
                     pass # Strict check failed, likely due to valid filtering. We accept missing real-time link in this case.
                
                # 出発時刻(dep)が現在時刻(curr_time)より未来の場合、待ち時間が発生する
                if dep and dep > curr_time:
                    wait_min = int(dep - curr_time)
                    if wait_min > 0:
                        # 待ち時間を独立したセグメントとして追加し、UIで表示可能にする
                        flush()
                        segs.append({
                            "kind": "wait", "title": "待ち時間", "minutes": wait_min,
                            "edges": 0, "from_": from_name, "to": from_name, "meters": 0,
                            "departure_time": min_to_time_str(curr_time),
                            "arrival_time": min_to_time_str(dep),
                            "startLabel": "待ち時間", "place": from_name
                        })
                
                # シミュレーション上の現在時刻を、バスの出発時刻に合わせて進める
                if dep and dep >= curr_time: curr_time = dep

                trip_id_found = pattern_id_found # Map pattern_id to trip_id_found for downstream use
            else:
                curr_time += 2.0
                trip_id_found = None # Reset for non-bus



            # 1. Route ID の特定
            final_route_id = G.nodes[v].get("route_id")
            if mode == "bus" and line_disp:
                parts = line_disp.split()
                if parts:
                    norm = _line_norm(parts[0])
                    gtfs_id = gtfs_repo.find_route_id_by_name(norm)
                    if gtfs_id:
                        final_route_id = gtfs_id

            # 2. Trip ID の特定
            final_trip_id = trip_id_found 
            
            # 出発バス停IDを GTFS形式に変換 (例: ...1301.1 -> 1301-01)
            gtfs_origin_id = None
            
            # u might be a tuple ('phys', 'odpt.Bus...')
            # Extract the actual ID string
            u_id = u[1] if isinstance(u, tuple) and len(u) > 1 else u
            
            if isinstance(u_id, str) and "BusstopPole" in u_id:
                 # Relaxed regex to catch ID even if there are suffixes
                 m = re.search(r'\.(\d{1,5})\.(\d{1,2})', u_id)
                 if m:
                    gtfs_origin_id = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
            
            if not gtfs_origin_id and mode == "bus":
                 print(f"[WARN] Failed to extract GTFS ID from: {u} (extracted: {u_id})", flush=True)

            if final_route_id and gtfs_origin_id and dep:
                # 時刻を "HH:MM:00" に変換
                h = int(dep // 60)
                m_part = int(dep % 60)
                time_str = f"{h:02d}:{m_part:02d}:00"
                
                # 検索
                found = gtfs_repo.find_trip_id(final_route_id, gtfs_origin_id, time_str)
                if found:
                    final_trip_id = found
                    print(f"[INFO] Fixed Trip: Route={final_route_id}, Stop={gtfs_origin_id}, Time={time_str} -> {final_trip_id}", flush=True)
                else:
                    print(f"[WARN] Trip Not Found: Route={final_route_id}, Stop={gtfs_origin_id}, Time={time_str}", flush=True)
            else:
                 if mode == "bus":
                     print(f"[WARN] Skip Trip Search: Route={final_route_id}, Stop={gtfs_origin_id}, Dep={dep}", flush=True)

            # 3. バス停リストのID書き換え
            for stop in curr_stops:
                old_id = stop.get("id")
                if old_id:
                    m = re.search(r'\.(\d{1,5})\.(\d{1,2})', old_id)
                    if m:
                        stop["id"] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

            cur = {
                "kind": mode, "title": line_disp, "edges": 0, 
                "from_": from_name, "to": None, "stops": curr_stops, 
                "departure_time": min_to_time_str(curr_time),
                
                "route_id": final_route_id, 
                "trip_id": final_trip_id, 
            }

        elif etype == "ride":
            print(f"[segments_detailed] edge[{i}] ride mode={mode} node={node}", flush=True)
            # 移動中: 通過する停留所をリストに追加していく
            if cur and cur["kind"] in ("bus", "rail"):
                cur["edges"] += 1
                stop_name = "???"
                phys_key = ("phys", v[1]) if v[0] == "line" else ("phys", u[1])
                
                # ID変換
                node_id = phys_key[1]
                new_id = node_id
                if "BusstopPole" in node_id:
                    m = re.search(r'\.(\d{1,5})\.(\d{1,2})', node_id)
                    if m:
                        new_id = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

                if phys_key in G: stop_name = G.nodes[phys_key]["name"]
                
                if not cur["stops"] or cur["stops"][-1]["name"] != stop_name:
                    cur["stops"].append({
                        "name": stop_name,
                        "lat": G.nodes[phys_key].get("lat"),
                        "lon": G.nodes[phys_key].get("lon"),
                        "id": new_id # ★新しいIDで保存
                    })
            
            # 時間を経過させる (電車は時刻表、その他は距離ベース)
            if mode == "rail":
                arr = tm.get_next_train_arrival(u[1], v[1], curr_time, day_type, delays_snapshot)
                if arr: curr_time = arr
                else: curr_time += edge.get("w", 2.0)
            else:
                dist = edge.get("meters", 0)
                curr_time += (dist/250.0 if dist>0 else 2.5) + 0.8

        elif etype in ("alight", "xfer"):
            print(f"[segments_detailed] edge[{i}] {etype} mode={mode} node={node}", flush=True)
            # 降車: 現在のRideセグメントを終了し、到着時刻などを記録・Flushする
            if cur and cur["kind"] in ("bus", "rail"):
                to_phys = v if v[0] == "phys" else last_phys
                if to_phys:
                    # ID変換
                    node_id = to_phys[1]
                    new_dest_id = node_id
                    if "BusstopPole" in node_id:
                        m = re.search(r'\.(\d{1,5})\.(\d{1,2})', node_id)
                        if m:
                            new_dest_id = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

                    to_name = G.nodes[to_phys]["name"]
                    cur["to"] = to_name
                    stop_lat = G.nodes[to_phys].get("lat")
                    stop_lon = G.nodes[to_phys].get("lon")
                    
                    if not cur["stops"] or cur["stops"][-1]["name"] != to_name:
                        cur["stops"].append({
                            "name": to_name,
                            "is_destination": True,
                            "lat": stop_lat,
                            "lon": stop_lon,
                            "id": new_dest_id # ★新しいIDで保存
                        })
                    else:
                        cur["stops"][-1]["is_destination"] = True
                        cur["stops"][-1]["id"] = new_dest_id # 上書き
                        cur["stops"][-1]["lat"] = stop_lat
                        cur["stops"][-1]["lon"] = stop_lon
                cur["arrival_time"] = min_to_time_str(curr_time)
                flush()
            curr_time += 1.0
            
    if cur: flush()
    print(
        f"[segments_detailed] done segments={len(segs)} summary="
        f"{[{'kind': s.get('kind'), 'from': s.get('from_'), 'to': s.get('to')} for s in segs]}",
        flush=True,
    )
    return segs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--busstop-poles", required=True)
    ap.add_argument("--busroute-patterns", required=True)
    ap.add_argument("--stations", required=True)
    ap.add_argument("--railways", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--walk", type=int, default=300)
    ap.add_argument("--mode", choices=["cost", "time"], default="cost")
    ap.add_argument("--start-time", default="10:00")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD")
    ap.add_argument("--bus-timetables", default="data/odpt_BusstopPoleTimetable.json")
    ap.add_argument("--train-timetables", default="data/odpt_TrainTimetable.json")
    args = ap.parse_args()

    print("[INFO] Building Graph...", flush=True)
    G = build_graph(args.busstop_poles, args.busroute_patterns, args.stations, args.railways, walk_radius=args.walk)
    
    alat, alon = map(float, args.a.split(","))
    blat, blon = map(float, args.b.split(","))
    a_phys, _ = nearest_phys(G, alat, alon)
    b_phys, bd = nearest_phys(G, blat, blon, station_only=True)
    if not b_phys or bd > 500: b_phys, bd = nearest_phys(G, blat, blon)

    if not a_phys or not b_phys:
        print("[FAIL] Start/End not found")
        sys.exit(1)

    dest_node, connections = get_virtual_connections(G, blat, blon, name="目的地", walk_radius=args.walk)

    tm = TimetableManager()
    tm.load_bus_timetables(args.bus_timetables)
    tm.load_bus_route_patterns(args.busroute_patterns)
    tm.load_train_timetables(args.train_timetables)
    
    results = search_best_routes_once(
        G, tm, a_phys, 
        mode=args.mode, 
        start_time=args.start_time, 
        limit=5, 
        target_node=dest_node, 
        virtual_dest_connections=connections,
        target_date_str=args.date
    )

    if not results:
        results = search_best_routes_once(
            G, tm, a_phys, 
            mode=args.mode, 
            start_time=args.start_time, 
            limit=5,
            target_node=b_phys,
            target_date_str=args.date
        )

    if not results:
        print("No valid route found.")
        return

    print(f"\n[INFO] Found {len(results)} Routes")
    for i, res in enumerate(results, 1):
        print(f"#{i} {res['score_label']}")
        for step in res["steps"]:
            kind = step.get("kind")
            title = step.get("title")
            dep = step.get("departure_time")
            arr = step.get("arrival_time")
            fro = step.get("from_")
            to = step.get("to")
            print(f"    [{kind}] {title} {fro} ({dep}) -> {to} ({arr})")

def get_reachable_stops(G, tm, lat, lon, limit_dist=1000, spatial_index=None):
    """
    指定された位置(lat, lon)から、乗り換えなしで到達可能なバス停・駅を検索して返す。
    「このバス停からどこに行けるか？」を可視化する機能などに使用される。

    Parameters:
    -----------
    G : networkx.DiGraph
        交通ネットワークグラフ
    tm : TimetableManager
        路線パターン(route_patterns_map)を持つデータ管理クラス
    lat, lon : float
        検索中心となる緯度・経度
    limit_dist : float
        最寄りバス停までの最大許容距離(メートル)。これを超えるとNot foundとなる。
    spatial_index : SpatialIndex, optional
        高速な近傍探索のための空間インデックス

    Returns:
    --------
    dict
        - "found": bool
        - "nearest_stop": 最寄りの出発地情報 {"id", "name"}
        - "reachable_stops": 到達可能なバス停情報のリスト
            [{"id", "name", "lat", "lon", "via_route"}, ...]
        - "count": 到達可能な総数
    """
    # 1. まず最寄りの物理ノード(バス停/駅)を探す
    nearest_node, nearest_dist = nearest_phys(G, lat, lon, spatial_index=spatial_index)
    if not nearest_node or nearest_dist > limit_dist:
        return {"found": False, "message": "Not found"}

    # 2. 検索半径(500m)以内にある出発候補バス停をすべて列挙する
    #    (最寄り1つだと、交差点の反対側のバス停などを逃す可能性があるため)
    start_candidates = []
    SEARCH_RADIUS_M = 500.0
    
    if spatial_index:
        raw_candidates = spatial_index.nearby_candidates(lat, lon, SEARCH_RADIUS_M)
        for nid, _, _ in raw_candidates:
             dist = haversine(lat, lon, G.nodes[nid]["lat"], G.nodes[nid]["lon"])
             if dist <= SEARCH_RADIUS_M: start_candidates.append(nid[1])
    else:
        for n, d in G.nodes(data=True):
             if n[0] == "phys":
                 if haversine(lat, lon, d["lat"], d["lon"]) <= SEARCH_RADIUS_M:
                     start_candidates.append(n[1])

    # 候補が見つからない場合は最寄りノードをフォールバックとして使う
    if not start_candidates: start_candidates.append(nearest_node[1])
    
    reachable_map = {}
    # 3. 出発バス停を通るすべての路線パターンを調べ、
    #    そのバス停より「後」にある停留所を到達可能リストに追加する
    for start_id in start_candidates:
        for route_id, patterns in tm.route_patterns_map.items():
            for seq in patterns:
                if start_id in seq:
                    idx = seq.index(start_id)
                    # 終点の場合は次がないのでスキップ
                    if idx == len(seq) - 1: continue
                    
                    # 出発地より後ろにあるバス停をすべて収集
                    future_stops = seq[idx+1:]
                    for next_stop_id in future_stops:
                        # 重複登録を防ぐ
                        if next_stop_id in reachable_map: continue
                        if next_stop_id in start_candidates: continue # 出発地周辺(自分自身や近隣)は除外
                        
                        node_key = ("phys", next_stop_id)
                        if node_key in G:
                            node_data = G.nodes[node_key]
                            reachable_map[next_stop_id] = {
                                "id": next_stop_id, "name": node_data.get("name"),
                                "lat": node_data.get("lat"), "lon": node_data.get("lon"),
                                "via_route": route_id 
                            }
    reachable_list = list(reachable_map.values())
    return {"found": True, "nearest_stop": {"id": nearest_node[1], "name": G.nodes[nearest_node]["name"]}, "reachable_stops": reachable_list, "count": len(reachable_list)}


# -------------------- GTFS-Realtime Parsing Logic (Merged from v2) --------------------

def parse_realtime_gtfs(content: bytes):
    """
    Parse GTFS-Realtime binary content and return a list of bus dictionaries
    compatible with the application's existing internal format.
    """
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(content)
    except Exception as e:
        print(f"[WARN] Failed to parse GTFS-RT protobuf: {e}", flush=True)
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
            current_stop_name = details.get('next_stop_name', '不明')
            route_id_raw = details.get('route_id') 
            route_short_name = details.get('route_short_name')
            
            bus_data = {
                "vehicle_id": v.vehicle.id,
                "lat": v.position.latitude,
                "lon": v.position.longitude,
                "trip_id": trip_id,
                
                "route_id": route_id_raw,
                "route_short_name": route_short_name,
                "destination": details.get('headsign'),
                "next_stop": current_stop_name,
                "next_stop_id": details.get('next_stop_id'),
                
                # Use native IDs
                "odpt:busroute": route_id_raw, 
                "odpt:fromBusstopPole": details.get('next_stop_id'),
            }
            result_list.append(bus_data)
        else:
            pass
            
    return result_list

if __name__ == "__main__":
    main()

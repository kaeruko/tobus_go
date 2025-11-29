import json
import bisect

def time_str_to_min(t_str):
    """ "06:30" -> 390 (分) に変換。 "25:00" などの深夜表記にも対応 """
    if not t_str: return 99999
    try:
        h, m = map(int, t_str.split(":"))
        return h * 60 + m
    except ValueError:
        return 99999

class TimetableManager:
    def __init__(self):
        # key: pole_id, value: { route_id: [minutes, ...] }
        # バスは「どの系統のバスか」で時間を絞る必要があるため
        self.bus_departures = {}
        
        # key: station_id, value: [ {dep, arr, next_sta, train_id} ]
        self.train_patterns = {}

    def load_bus_timetables(self, json_path, target_date_type="Weekday"):
        data = self._load_json(json_path)
        count = 0
        print(f"[DEBUG] Loading Bus JSON: {len(data)} entries found.")
        
        for entry in data:
            # ★修正: カレンダー判定を一時的に無効化（すべての時刻表を読み込む）
            # if target_date_type not in entry.get("odpt:calendar", ""): continue

            pole_id = entry.get("odpt:busstopPole")
            route_id = entry.get("odpt:busroute")  # 例: odpt.Busroute:Toei.Higashi22
            
            if not pole_id: continue

            times = []
            for obj in entry.get("odpt:busstopPoleTimetableObject", []):
                dep = obj.get("odpt:departureTime")
                if dep:
                    times.append(time_str_to_min(dep))
            times.sort()
            
            if not times: continue

            if pole_id not in self.bus_departures:
                self.bus_departures[pole_id] = {}
            
            # 系統IDそのままだとマッチしにくい場合があるので、リストで保持するか
            # ここではシンプルに route_id をキーにする
            if route_id not in self.bus_departures[pole_id]:
                self.bus_departures[pole_id][route_id] = []
            
            self.bus_departures[pole_id][route_id].extend(times)
            count += 1
            
        print(f"[DEBUG] Loaded Bus Timetables for {len(self.bus_departures)} poles. (Entries used: {count})")
        # マージ後のソート
        for pid in self.bus_departures:
            for rid in self.bus_departures[pid]:
                self.bus_departures[pid][rid].sort()

    def load_train_timetables(self, json_path, target_date_type="Weekday"):
        data = self._load_json(json_path)
        count = 0
        print(f"[DEBUG] Loading Train JSON: {len(data)} entries found.")

        for entry in data:
            # ★修正: ここもカレンダー判定を緩める
            # if target_date_type not in entry.get("odpt:calendar", ""): continue
            
            # 列車の全停車駅リスト
            objs = entry.get("odpt:trainTimetableObject", [])
            
            # A駅 -> B駅 のリンクを作る
            for i in range(len(objs) - 1):
                curr = objs[i]
                next_stop = objs[i+1]
                
                dep_sta = curr.get("odpt:departureStation")
                arr_sta = next_stop.get("odpt:arrivalStation") # 次の駅
                
                dep_time = time_str_to_min(curr.get("odpt:departureTime"))
                arr_time = time_str_to_min(next_stop.get("odpt:arrivalTime"))
                
                if dep_sta and arr_sta:
                    if dep_sta not in self.train_patterns:
                        self.train_patterns[dep_sta] = []
                    
                    self.train_patterns[dep_sta].append({
                        "dep": dep_time,
                        "arr": arr_time,
                        "next_sta": arr_sta,
                        "train": entry.get("odpt:trainNumber")
                    })
            count += 1
        print(f"[DEBUG] Loaded Train Timetables for {len(self.train_patterns)} stations. (Entries used: {count})")

        # ソートしておく（二分探索用）
        for sid in self.train_patterns:
            self.train_patterns[sid].sort(key=lambda x: x["dep"])

    def _load_json(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
            return d if isinstance(d, list) else [d]

    # --- 検索メソッド ---

    def get_next_bus_departure(self, pole_id, route_id, current_time_min):
        """ 指定時刻以降の最短の出発時刻を返す """
        routes_at_pole = self.bus_departures.get(pole_id)
        if not routes_at_pole:
            return None
        
        # 該当路線の時刻表を取得
        times = routes_at_pole.get(route_id)
        
        # もし完全一致で見つからなければ、それっぽいものを探す（救済措置）
        if not times:
            for r_key, t_list in routes_at_pole.items():
                if route_id and (route_id in r_key or r_key in route_id):
                    times = t_list
                    break
        
        if not times:
            return None
        
        # 二分探索で current_time_min 以上の位置を探す
        idx = bisect.bisect_left(times, current_time_min)
        if idx < len(times):
            return times[idx]
        return None # もう終バス終わってる

    def get_next_train_arrival(self, current_sta, next_sta, current_time_min):
        """ 
        現在駅と次駅を指定して、乗れる列車の「次駅到着時刻」を返す 
        （グラフのエッジが隣接駅を結んでいる前提）
        """
        trains = self.train_patterns.get(current_sta)
        if not trains:
            return None
        
        # 単純な二分探索は辞書リストだと難しいので、ここでは簡易的に線形探索
        # (本気でやるなら dep だけのリストを別途持つ)
        for t in trains:
            if t["dep"] >= current_time_min and t["next_sta"] == next_sta:
                return t["arr"] # 次の駅に着く時間
        return None

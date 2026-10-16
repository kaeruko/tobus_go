"""Synthetic raw GTFS for shared bus/rail contract tests; no city policy or IO."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from transit_adapters.gtfs import GtfsTransitAdapter
from transit_dataset import FeedMetadata, TransitDataset

JST = ZoneInfo("Asia/Tokyo")


def load_fixture_feed(root: Path, *, rail: bool) -> TransitDataset:
    feed = "fixture_subway" if rail else "fixture_bus"
    if rail:
        inputs = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "S,乗換地点,35.4651,139.6251\nD,到着駅,35.4500,139.6300\n"
            ),
            "routes.txt": "route_id,route_short_name,route_long_name,route_type\nBLUE,ブルーライン,市営地下鉄,1\n",
            "trips.txt": "route_id,service_id,trip_id\nBLUE,ALL,TRAIN1\nBLUE,ALL,TRAIN2\n",
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "TRAIN1,09:25:00,09:25:00,S,1\n"
                "TRAIN1,09:40:00,09:40:00,D,2\n"
                "TRAIN2,10:00:00,10:00:00,D,1\n"
                "TRAIN2,10:20:00,10:20:00,S,2\n"
            ),
        }
    else:
        inputs = {
            "stops.txt": (
                "stop_id,stop_name,stop_lat,stop_lon\n"
                "O,出発駅前,35.4700,139.6200\nB,乗換地点,35.4650,139.6250\n"
            ),
            "routes.txt": (
                "route_id,route_short_name,route_long_name,route_type\n"
                "BUS,008系統,市営バス,3\nX,特別便,観光,3\n"
            ),
            "trips.txt": (
                "route_id,service_id,trip_id\n"
                "BUS,ALL,BUS1\nBUS,ALL,BUS2\nX,ALL,EXPRESS\n"
            ),
            "stop_times.txt": (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                "BUS1,09:05:00,09:05:00,O,1\n"
                "BUS1,09:20:00,09:20:00,B,2\n"
                "BUS2,10:26:00,10:26:00,B,1\n"
                "BUS2,10:41:00,10:41:00,O,2\n"
                "EXPRESS,09:01:00,09:01:00,O,1\n"
                "EXPRESS,09:10:00,09:10:00,B,2\n"
            ),
        }
    inputs["calendar.txt"] = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "ALL,1,1,1,1,1,1,1,20260101,20261231\n"
    )
    for name, contents in inputs.items():
        (root / name).write_text(contents, encoding="utf-8")
    metadata = FeedMetadata(
        feed_id=feed,
        source_type="gtfs",
        source_uri="https://example.invalid/synthetic-feed",
        version="synthetic-v1",
        fetched_at=datetime(2026, 10, 14, tzinfo=JST),
    )
    dataset = GtfsTransitAdapter.load(root, metadata=metadata)
    return dataset

import asyncio
import unittest

import httpx
from google.transit import gtfs_realtime_pb2

from realtime_provider import GtfsRealtimeEndpoints, GtfsRealtimeHttpProvider


VEHICLE_URL = "https://example.test/vehicle"
TRIP_URL = "https://example.test/trip"
ALERT_URL = "https://example.test/alert"


class _FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return self.responses[url]


def _response(url: str, content: bytes, status: int = 200):
    return httpx.Response(
        status,
        content=content,
        request=httpx.Request("GET", url),
    )


def _vehicle_bytes():
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 1000
    entity = message.entity.add()
    entity.id = "vehicle-entity"
    vehicle = entity.vehicle
    vehicle.trip.trip_id = "T1"
    vehicle.trip.route_id = "R1"
    vehicle.trip.direction_id = 1
    vehicle.vehicle.id = "BUS-7"
    vehicle.vehicle.label = "7"
    vehicle.position.latitude = 38.2682
    vehicle.position.longitude = 140.8694
    vehicle.position.bearing = 90.0
    vehicle.position.speed = 8.5
    vehicle.stop_id = "S2"
    vehicle.current_stop_sequence = 2
    vehicle.current_status = gtfs_realtime_pb2.VehiclePosition.IN_TRANSIT_TO
    vehicle.timestamp = 995
    return message.SerializeToString()


def _trip_bytes():
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 2000
    entity = message.entity.add()
    entity.id = "trip-entity"
    update = entity.trip_update
    update.trip.trip_id = "T1"
    update.trip.route_id = "R1"
    update.trip.direction_id = 1
    update.vehicle.id = "BUS-7"
    update.timestamp = 1990
    stop = update.stop_time_update.add()
    stop.stop_sequence = 3
    stop.stop_id = "S3"
    stop.arrival.delay = 120
    stop.arrival.time = 2010
    stop.departure.delay = 150
    stop.departure.time = 2040
    return message.SerializeToString()


def _alert_bytes():
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = 3000
    entity = message.entity.add()
    entity.id = "alert-entity"
    alert = entity.alert
    ja = alert.header_text.translation.add()
    ja.language = "ja"
    ja.text = "運休"
    en = alert.description_text.translation.add()
    en.language = "en"
    en.text = "Service suspended"
    period = alert.active_period.add()
    period.start = 2900
    period.end = 3100
    informed = alert.informed_entity.add()
    informed.route_id = "R1"
    informed.stop_id = "S3"
    return message.SerializeToString()


class GtfsRealtimeHttpProviderTest(unittest.TestCase):
    def _provider(self, responses):
        client = _FakeClient(responses)
        provider = GtfsRealtimeHttpProvider(
            GtfsRealtimeEndpoints(
                vehicle_positions=VEHICLE_URL,
                trip_updates=TRIP_URL,
                alerts=ALERT_URL,
            ),
            client=client,
        )
        return provider, client

    def test_vehicle_positions_are_normalized(self):
        provider, client = self._provider(
            {VEHICLE_URL: _response(VEHICLE_URL, _vehicle_bytes())}
        )
        rows = asyncio.run(provider.vehicle_positions())

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["trip_id"], "T1")
        self.assertEqual(row["route_id"], "R1")
        self.assertEqual(row["direction_id"], 1)
        self.assertEqual(row["vehicle_id"], "BUS-7")
        self.assertAlmostEqual(row["lat"], 38.2682, places=3)
        self.assertAlmostEqual(row["lon"], 140.8694, places=3)
        self.assertEqual(row["stop_id"], "S2")
        self.assertEqual(row["feed_timestamp"], 1000)
        self.assertEqual(client.calls, [(VEHICLE_URL, None)])

    def test_trip_updates_are_normalized(self):
        provider, client = self._provider(
            {TRIP_URL: _response(TRIP_URL, _trip_bytes())}
        )
        rows = asyncio.run(provider.trip_updates())

        self.assertEqual(rows[0]["trip_id"], "T1")
        self.assertEqual(rows[0]["route_id"], "R1")
        self.assertEqual(rows[0]["vehicle_id"], "BUS-7")
        self.assertEqual(rows[0]["stop_time_updates"][0]["stop_id"], "S3")
        self.assertEqual(rows[0]["stop_time_updates"][0]["arrival_delay"], 120)
        self.assertEqual(client.calls, [(TRIP_URL, None)])

    def test_alerts_are_normalized(self):
        provider, client = self._provider(
            {ALERT_URL: _response(ALERT_URL, _alert_bytes())}
        )
        rows = asyncio.run(provider.alerts())

        self.assertEqual(rows[0]["header_text"], "運休")
        self.assertEqual(rows[0]["description_text"], "Service suspended")
        self.assertEqual(rows[0]["active_periods"][0], {"start": 2900, "end": 3100})
        self.assertEqual(rows[0]["informed_entities"][0]["route_id"], "R1")
        self.assertEqual(client.calls, [(ALERT_URL, None)])

    def test_http_failure_does_not_try_another_endpoint(self):
        provider, client = self._provider(
            {VEHICLE_URL: _response(VEHICLE_URL, b"upstream error", status=503)}
        )
        with self.assertRaises(httpx.HTTPStatusError):
            asyncio.run(provider.vehicle_positions())

        self.assertEqual(client.calls, [(VEHICLE_URL, None)])

    def test_invalid_protobuf_fails_instead_of_returning_empty_data(self):
        provider, client = self._provider(
            {VEHICLE_URL: _response(VEHICLE_URL, b"not-protobuf")}
        )
        with self.assertRaisesRegex(RuntimeError, "protobuf decode failed"):
            asyncio.run(provider.vehicle_positions())

        self.assertEqual(client.calls, [(VEHICLE_URL, None)])


if __name__ == "__main__":
    unittest.main()

import 'package:flutter_test/flutter_test.dart';
import 'package:toei_go/services/bus_location_source.dart';

void main() {
  Map<String, dynamic> basePayload() => {
    'vehicle_id': '1772',
    'vehicle_lat': 35.466,
    'vehicle_lon': 139.622,
    'trip_id': 'yokohama_bus:T1',
    'trip_stop_ids': ['yokohama_bus:A', 'yokohama_bus:B'],
    'raw_stop_id': 'A',
    'raw_stop_name': '横浜駅前',
    'observed_stop_sequence': 1,
    'current_status': 2,
    'feed_ts': 1700000000,
    'vehicle_ts': 1700000001,
  };

  test('parses explicit before-first-stop state without fabricating stop', () {
    final payload = basePayload()
      ..['before_first_stop'] = true
      ..['odpt:fromBusstopPole'] = null
      ..['from_stop_sequence'] = null;

    final location = BusLocation.fromJson(
      payload,
      routeId: 'yokohama_bus:R1',
      tripId: 'yokohama_bus:T1',
    );

    expect(location.beforeFirstStop, isTrue);
    expect(location.fromStopId, isNull);
    expect(location.fromStopSequence, isNull);
    expect(location.vehicleLat, 35.466);
    expect(location.vehicleLon, 139.622);
  });

  test('recognizes legacy Tokyo first-stop response only for exact GTFS-RT state', () {
    final payload = basePayload()
      ..['trip_id'] = 'tokyo-trip'
      ..['current_status'] = 'IN_TRANSIT_TO'
      ..['odpt:fromBusstopPole'] = null
      ..['from_stop_sequence'] = null;

    final location = BusLocation.fromJson(
      payload,
      routeId: 'odpt.Busroute:Toei.T01',
      tripId: 'tokyo-trip',
    );

    expect(location.beforeFirstStop, isTrue);
    expect(location.fromStopId, isNull);
  });

  test('normal location requires and preserves previous stop', () {
    final payload = basePayload()
      ..['before_first_stop'] = false
      ..['odpt:fromBusstopPole'] = 'yokohama_bus:A'
      ..['from_stop_sequence'] = 1
      ..['observed_stop_sequence'] = 2;

    final location = BusLocation.fromJson(
      payload,
      routeId: 'yokohama_bus:R1',
      tripId: 'yokohama_bus:T1',
    );

    expect(location.beforeFirstStop, isFalse);
    expect(location.fromStopId, 'yokohama_bus:A');
    expect(location.fromStopSequence, 1);
  });

  test('missing previous stop outside first-stop state fails', () {
    final payload = basePayload()
      ..['observed_stop_sequence'] = 3
      ..['current_status'] = 'IN_TRANSIT_TO'
      ..['odpt:fromBusstopPole'] = null
      ..['from_stop_sequence'] = null;

    expect(
      () => BusLocation.fromJson(
        payload,
        routeId: 'yokohama_bus:R1',
        tripId: 'yokohama_bus:T1',
      ),
      throwsFormatException,
    );
  });

  test('explicit before-first-stop cannot coexist with previous stop', () {
    final payload = basePayload()
      ..['before_first_stop'] = true
      ..['odpt:fromBusstopPole'] = 'yokohama_bus:A'
      ..['from_stop_sequence'] = 1;

    expect(
      () => BusLocation.fromJson(
        payload,
        routeId: 'yokohama_bus:R1',
        tripId: 'yokohama_bus:T1',
      ),
      throwsFormatException,
    );
  });

  test('invalid coordinates fail instead of hiding the vehicle marker', () {
    final payload = basePayload()
      ..['before_first_stop'] = true
      ..['odpt:fromBusstopPole'] = null
      ..['from_stop_sequence'] = null
      ..['vehicle_lat'] = 999;

    expect(
      () => BusLocation.fromJson(
        payload,
        routeId: 'yokohama_bus:R1',
        tripId: 'yokohama_bus:T1',
      ),
      throwsFormatException,
    );
  });
}

import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/services/bus_location_source.dart';
import 'package:toeigo/widgets/active_route_content.dart';

void main() {
  BusLocation location({
    required String status,
    bool beforeFirstStop = false,
  }) => BusLocation(
    vehicleId: '3438',
    fromStopId: beforeFirstStop ? null : 'stop-1',
    routeId: 'yokohama_bus:008',
    tripId: 'yokohama_bus:T1',
    vehicleLat: 35.465,
    vehicleLon: 139.625,
    beforeFirstStop: beforeFirstStop,
    rawStopName: '横浜駅前',
    currentStatus: status,
  );

  test('IN_TRANSIT_TO says the bus is heading to the stop', () {
    expect(
      busRealtimeStatusText(location(status: 'IN_TRANSIT_TO')),
      '横浜駅前へ向かっています',
    );
  });

  test('STOPPED_AT says the bus is stopped at the stop', () {
    expect(busRealtimeStatusText(location(status: 'STOPPED_AT')), '横浜駅前に停車中');
  });

  test('before-first-stop takes precedence over vehicle status', () {
    expect(
      busRealtimeStatusText(
        location(status: 'IN_TRANSIT_TO', beforeFirstStop: true),
      ),
      '横浜駅前（始発停留所）へ向かっています',
    );
  });

  test('unknown realtime status fails fast', () {
    expect(
      () => busRealtimeStatusText(location(status: 'UNKNOWN')),
      throwsStateError,
    );
  });
}

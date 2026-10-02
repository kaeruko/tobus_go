import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/alighting_alert.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/services/bus_location_source.dart';

void main() {
  group('AlightingAlertTracker', () {
    test('alerts once at two stops before and once at the next stop', () {
      final tracker = AlightingAlertTracker();
      final step = _step(
        const [
          ('A', 'A'),
          ('B', 'B'),
          ('C', 'C'),
          ('D', 'D'),
        ],
      );
      final schedule = _schedule(
        const [
          (1, 'A'),
          (2, 'B'),
          (3, 'C'),
          (4, 'D'),
        ],
      );

      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 2),
        ),
        AlightingAlert.twoStopsBefore,
      );
      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 2),
        ),
        isNull,
      );
      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 3),
        ),
        AlightingAlert.nextStop,
      );
      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 3),
        ),
        isNull,
      );
    });

    test('does not backfill two-stops alert after realtime jumps to next stop', () {
      final tracker = AlightingAlertTracker();
      final step = _step(
        const [
          ('A', 'A'),
          ('B', 'B'),
          ('C', 'C'),
          ('D', 'D'),
        ],
      );
      final schedule = _schedule(
        const [
          (1, 'A'),
          (2, 'B'),
          (3, 'C'),
          (4, 'D'),
        ],
      );

      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 1),
        ),
        isNull,
      );
      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 3),
        ),
        AlightingAlert.nextStop,
      );
      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 2),
        ),
        isNull,
      );
    });

    test('uses ordered occurrences when the same stop ID appears twice', () {
      final tracker = AlightingAlertTracker();
      final step = _step(
        const [
          ('C', 'C'),
          ('B', 'B second pass'),
          ('D', 'D'),
        ],
      );
      final schedule = _schedule(
        const [
          (1, 'A'),
          (2, 'B'),
          (3, 'C'),
          (4, 'B'),
          (5, 'D'),
        ],
      );

      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 3),
        ),
        AlightingAlert.twoStopsBefore,
      );
      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 4),
        ),
        AlightingAlert.nextStop,
      );
    });

    test('does not alert while the vehicle is still before boarding', () {
      final tracker = AlightingAlertTracker();
      final step = _step(
        const [
          ('C', 'C'),
          ('D', 'D'),
        ],
      );
      final schedule = _schedule(
        const [
          (1, 'A'),
          (2, 'B'),
          (3, 'C'),
          (4, 'D'),
        ],
      );

      expect(
        tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 1),
        ),
        isNull,
      );
    });

    test('fails fast when the route stop cannot be mapped to the GTFS trip', () {
      final tracker = AlightingAlertTracker();
      final step = _step(
        const [
          ('A', 'A'),
          ('MISSING', 'missing'),
        ],
      );
      final schedule = _schedule(
        const [
          (1, 'A'),
          (2, 'B'),
        ],
      );

      expect(
        () => tracker.evaluate(
          step: step,
          location: _location(schedule: schedule, fromSequence: 1),
        ),
        throwsStateError,
      );
    });
  });
}

StepSeg _step(List<(String, String)> stops) {
  return StepSeg(
    stepId: 'bus-step',
    kind: 'bus',
    title: 'テスト系統',
    fromName: stops.first.$2,
    toName: stops.last.$2,
    routeId: 'route-1',
    tripId: 'trip-1',
    stops: [
      for (var index = 0; index < stops.length; index++)
        StopPoint(
          name: stops[index].$2,
          point: LatLng(35.0 + index / 1000, 139.0),
          isOrigin: index == 0,
          isDestination: index == stops.length - 1,
          stopId: stops[index].$1,
        ),
    ],
  );
}

List<BusStopSchedule> _schedule(List<(int, String)> stops) {
  return [
    for (final stop in stops)
      BusStopSchedule(
        sequence: stop.$1,
        stopId: stop.$2,
        stopName: stop.$2,
        arrivalMinute: 600 + stop.$1,
        departureMinute: 600 + stop.$1,
        arrivalTime: '10:${stop.$1.toString().padLeft(2, '0')}',
        departureTime: '10:${stop.$1.toString().padLeft(2, '0')}',
      ),
  ];
}

BusLocation _location({
  required List<BusStopSchedule> schedule,
  required int fromSequence,
}) {
  final current = schedule.singleWhere((stop) => stop.sequence == fromSequence);
  return BusLocation(
    vehicleId: 'vehicle-1',
    fromStopId: current.stopId,
    routeId: 'route-1',
    tripId: 'trip-1',
    vehicleLat: 35.0,
    vehicleLon: 139.0,
    beforeFirstStop: false,
    tripStopIds: schedule.map((stop) => stop.stopId).toList(growable: false),
    fromStopSequence: fromSequence,
    observedStopSequence: fromSequence,
    currentStatus: 'STOPPED_AT',
    tripStopSchedule: schedule,
  );
}

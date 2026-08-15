import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/delay_impact_analyzer.dart';
import 'package:toeigo/logic/next_ride_delay_adjuster.dart';
import 'package:toeigo/logic/next_ride_realtime.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/services/bus_location_source.dart';
import 'package:toeigo/services/train_location_source.dart';

void main() {
  int epochSeconds(DateTime value) => value.millisecondsSinceEpoch ~/ 1000;

  group('next bus realtime departure', () {
    final step = StepSeg(
      stepId: 'next-bus',
      kind: 'bus',
      title: '上23 上野松坂屋前行',
      routeId: '070',
      tripId: 'trip-next-bus',
      fromName: '乗換停留所',
      toName: '目的地',
      stops: [
        StopPoint(
          name: '乗換停留所',
          point: const LatLng(35.700, 139.800),
          stopId: 'stop-board',
        ),
        StopPoint(
          name: '目的地',
          point: const LatLng(35.710, 139.810),
          stopId: 'stop-destination',
        ),
      ],
    );

    const schedule = <BusStopSchedule>[
      BusStopSchedule(
        sequence: 1,
        stopId: 'stop-before',
        stopName: '手前停留所',
        arrivalMinute: 18 * 60,
        departureMinute: 18 * 60,
        arrivalTime: '18:00',
        departureTime: '18:00',
      ),
      BusStopSchedule(
        sequence: 2,
        stopId: 'stop-board',
        stopName: '乗換停留所',
        arrivalMinute: 18 * 60 + 5,
        departureMinute: 18 * 60 + 5,
        arrivalTime: '18:05',
        departureTime: '18:05',
      ),
      BusStopSchedule(
        sequence: 3,
        stopId: 'stop-destination',
        stopName: '目的地',
        arrivalMinute: 18 * 60 + 12,
        departureMinute: 18 * 60 + 12,
        arrivalTime: '18:12',
        departureTime: '18:12',
      ),
    ];

    test('vehicle before boarding stop produces conservative delayed departure', () {
      final vehicleAt = DateTime.utc(2026, 8, 15, 18, 3);
      final location = BusLocation(
        vehicleId: 'bus-v2',
        fromStopId: 'stop-before',
        routeId: '070',
        tripId: 'trip-next-bus',
        rawStopId: 'stop-board',
        rawStopName: '乗換停留所',
        fromStopSequence: 1,
        observedStopSequence: 2,
        currentStatus: 'IN_TRANSIT_TO',
        vehicleTimestamp: epochSeconds(vehicleAt),
        vehicleAgeSeconds: 10,
        tripStopSchedule: schedule,
      );

      final estimate = NextRideRealtimeAdapter.fromBus(
        step: step,
        location: location,
        now: DateTime.utc(2026, 8, 15, 18, 3, 10),
      );

      expect(estimate.status, NextRideRealtimeDepartureStatus.predicted);
      expect(
        estimate.predictedDepartureAt,
        DateTime.utc(2026, 8, 15, 18, 8),
      );
    });

    test('vehicle already left boarding stop is marked passed', () {
      final vehicleAt = DateTime.utc(2026, 8, 15, 18, 7);
      final location = BusLocation(
        vehicleId: 'bus-v2',
        fromStopId: 'stop-board',
        routeId: '070',
        tripId: 'trip-next-bus',
        rawStopId: 'stop-destination',
        rawStopName: '目的地',
        fromStopSequence: 2,
        observedStopSequence: 3,
        currentStatus: 'IN_TRANSIT_TO',
        vehicleTimestamp: epochSeconds(vehicleAt),
        vehicleAgeSeconds: 5,
        tripStopSchedule: schedule,
      );

      final estimate = NextRideRealtimeAdapter.fromBus(
        step: step,
        location: location,
        now: DateTime.utc(2026, 8, 15, 18, 7, 5),
      );

      expect(
        estimate.status,
        NextRideRealtimeDepartureStatus.passedBoardingPlace,
      );
      expect(estimate.effectiveDepartureAt, isNull);
    });

    test('stale next-bus sample fails instead of using schedule as realtime', () {
      final vehicleAt = DateTime.utc(2026, 8, 15, 18, 0);
      final location = BusLocation(
        vehicleId: 'bus-v2',
        fromStopId: 'stop-before',
        routeId: '070',
        tripId: 'trip-next-bus',
        rawStopId: 'stop-board',
        rawStopName: '乗換停留所',
        fromStopSequence: 1,
        observedStopSequence: 2,
        currentStatus: 'IN_TRANSIT_TO',
        vehicleTimestamp: epochSeconds(vehicleAt),
        vehicleAgeSeconds: 120,
        tripStopSchedule: schedule,
      );

      expect(
        () => NextRideRealtimeAdapter.fromBus(
          step: step,
          location: location,
          now: DateTime.utc(2026, 8, 15, 18, 2),
        ),
        throwsStateError,
      );
    });
  });

  test('next train before boarding station produces predicted departure', () {
    final step = StepSeg(
      stepId: 'next-rail',
      kind: 'rail',
      title: '新宿線 本八幡行',
      fromName: '馬喰横山',
      toName: '森下',
      stops: [
        StopPoint(
          name: '馬喰横山',
          point: const LatLng(35.692, 139.782),
        ),
        StopPoint(
          name: '森下',
          point: const LatLng(35.688, 139.798),
        ),
      ],
    );
    final vehicleAt = DateTime.utc(2026, 8, 15, 18, 3);
    final location = TrainLocation(
      tripId: 'train-next',
      routeId: 'S',
      tripHeadsign: '本八幡',
      vehicleId: 'train-v2',
      currentStopSequence: 10,
      currentStatus: 'IN_TRANSIT_TO',
      currentStopId: 'board',
      currentStopName: '馬喰横山',
      boardingSequence: 10,
      destinationSequence: 11,
      vehicleTimestamp: epochSeconds(vehicleAt),
      vehicleAgeSeconds: 10,
      tripStops: const [
        TrainTripStop(
          sequence: 9,
          stopId: 'before',
          stopName: '浜町',
          arrivalTime: '18:00:00',
          departureTime: '18:00:00',
        ),
        TrainTripStop(
          sequence: 10,
          stopId: 'board',
          stopName: '馬喰横山',
          arrivalTime: '18:05:00',
          departureTime: '18:05:00',
        ),
        TrainTripStop(
          sequence: 11,
          stopId: 'destination',
          stopName: '森下',
          arrivalTime: '18:09:00',
          departureTime: '18:09:00',
        ),
      ],
    );

    final estimate = NextRideRealtimeAdapter.fromRail(
      step: step,
      location: location,
      now: DateTime.utc(2026, 8, 15, 18, 3, 10),
    );

    expect(estimate.status, NextRideRealtimeDepartureStatus.predicted);
    expect(
      estimate.predictedDepartureAt,
      DateTime.utc(2026, 8, 15, 18, 8),
    );
  });

  group('next ride delay adjustment', () {
    DelayImpact baseImpact() => DelayImpact(
      legIndex: 0,
      currentStepId: 'rail-1',
      currentRideTitle: '浅草線 青砥行',
      currentAlightingPlaceName: '東日本橋',
      plannedArrivalAt: DateTime.utc(2026, 8, 15, 18, 10),
      predictedArrivalAt: DateTime.utc(2026, 8, 15, 18, 13),
      delay: const Duration(minutes: 3),
      nextRideStepId: 'rail-2',
      nextRideTitle: '新宿線 本八幡行',
      nextDepartureAt: DateTime.utc(2026, 8, 15, 18, 16),
      transferWalkMinutes: 4,
      earliestTransferReadyAt: DateTime.utc(2026, 8, 15, 18, 17),
      nextTransferFeasible: false,
      missedBy: const Duration(minutes: 1),
    );

    test('delayed next service can make the transfer feasible again', () {
      final adjusted = NextRideDelayAdjuster.apply(
        base: baseImpact(),
        realtime: NextRideRealtimeDeparture(
          stepId: 'rail-2',
          boardingPlaceName: '馬喰横山',
          status: NextRideRealtimeDepartureStatus.predicted,
          observedAt: DateTime.utc(2026, 8, 15, 18, 12),
          predictedDepartureAt: DateTime.utc(2026, 8, 15, 18, 21),
        ),
      );

      expect(adjusted.scheduledNextDepartureAt, DateTime.utc(2026, 8, 15, 18, 16));
      expect(adjusted.impact.nextDepartureAt, DateTime.utc(2026, 8, 15, 18, 21));
      expect(adjusted.impact.nextTransferFeasible, isTrue);
      expect(adjusted.impact.missedBy, Duration.zero);
    });

    test('service already past boarding place remains a missed transfer', () {
      final adjusted = NextRideDelayAdjuster.apply(
        base: baseImpact(),
        realtime: NextRideRealtimeDeparture(
          stepId: 'rail-2',
          boardingPlaceName: '馬喰横山',
          status: NextRideRealtimeDepartureStatus.passedBoardingPlace,
          observedAt: DateTime.utc(2026, 8, 15, 18, 16, 30),
        ),
      );

      expect(adjusted.impact.nextTransferFeasible, isFalse);
      expect(adjusted.realtime.status,
          NextRideRealtimeDepartureStatus.passedBoardingPlace);
    });
  });
}

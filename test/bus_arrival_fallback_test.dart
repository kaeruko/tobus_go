import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/bus_arrival_fallback.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  const staleAfterSeconds = 90.0;
  final plannedArrivalAt = DateTime(2026, 10, 3, 13, 6);

  BusProgress riding({double? vehicleAgeSeconds}) {
    return BusProgress(
      stepId: 'bus-1',
      fromStopId: 's1',
      fromStopIndex: 1,
      nextStopId: 's2',
      nextStopIndex: 2,
      phase: BusProgressPhase.riding,
      observedStopId: 's2',
      observedStopName: '渋谷三丁目',
      currentStatus: 'IN_TRANSIT_TO',
      vehicleAgeSeconds: vehicleAgeSeconds,
    );
  }

  test('planned arrival plus stale realtime is treated as arrived', () {
    expect(
      shouldAssumeBusArrivedFromStaleRealtime(
        now: DateTime(2026, 10, 3, 13, 6, 1),
        plannedArrivalAt: plannedArrivalAt,
        progress: riding(vehicleAgeSeconds: 147.6),
        staleAfterSeconds: staleAfterSeconds,
      ),
      isTrue,
    );
  });

  test('fresh realtime stays authoritative after planned arrival', () {
    expect(
      shouldAssumeBusArrivedFromStaleRealtime(
        now: DateTime(2026, 10, 3, 13, 7),
        plannedArrivalAt: plannedArrivalAt,
        progress: riding(vehicleAgeSeconds: 45),
        staleAfterSeconds: staleAfterSeconds,
      ),
      isFalse,
    );
  });

  test('stale realtime does not complete the ride before planned arrival', () {
    expect(
      shouldAssumeBusArrivedFromStaleRealtime(
        now: DateTime(2026, 10, 3, 13, 5, 59),
        plannedArrivalAt: plannedArrivalAt,
        progress: riding(vehicleAgeSeconds: 180),
        staleAfterSeconds: staleAfterSeconds,
      ),
      isFalse,
    );
  });

  test('approaching bus is never treated as alighted by this fallback', () {
    const approaching = BusProgress(
      stepId: 'bus-1',
      fromStopId: null,
      fromStopIndex: null,
      nextStopId: 's0',
      nextStopIndex: 0,
      stopsUntilBoarding: 1,
      phase: BusProgressPhase.approaching,
      vehicleAgeSeconds: 180,
    );

    expect(
      shouldAssumeBusArrivedFromStaleRealtime(
        now: DateTime(2026, 10, 3, 13, 7),
        plannedArrivalAt: plannedArrivalAt,
        progress: approaching,
        staleAfterSeconds: staleAfterSeconds,
      ),
      isFalse,
    );
  });

  test('assumed arrival moves progress to the destination stop', () {
    final step = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '都01',
      fromName: '新橋駅前',
      toName: '渋谷三丁目',
      stops: [
        StopPoint(
          name: '新橋駅前',
          point: const LatLng(35, 139),
          stopId: 's0',
        ),
        StopPoint(
          name: '青山学院中等部前',
          point: const LatLng(35.01, 139.01),
          stopId: 's1',
        ),
        StopPoint(
          name: '渋谷三丁目',
          point: const LatLng(35.02, 139.02),
          stopId: 's2',
        ),
      ],
    );

    final arrived = assumeBusArrivedAtDestination(
      step: step,
      realtimeProgress: riding(vehicleAgeSeconds: 147.6),
    );

    expect(arrived.phase, BusProgressPhase.arrived);
    expect(arrived.fromStopId, 's2');
    expect(arrived.fromStopIndex, 2);
    expect(arrived.nextStopId, isNull);
    expect(arrived.nextStopIndex, isNull);
    expect(arrived.observedStopName, '渋谷三丁目');
    expect(arrived.vehicleAgeSeconds, 147.6);
  });
}

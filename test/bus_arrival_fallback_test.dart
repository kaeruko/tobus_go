import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/bus_arrival_fallback.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  final arrival = DateTime(2026, 10, 5, 17);
  final step = StepSeg(
    stepId: 'bus-1',
    kind: 'bus',
    title: '都01',
    fromName: '新橋駅前',
    toName: '渋谷駅前',
    stops: [
      StopPoint(name: '新橋駅前', point: const LatLng(35, 139), stopId: 's0'),
      StopPoint(name: '渋谷駅前', point: const LatLng(35.02, 139.02), stopId: 's2'),
    ],
  );
  test('the schedule ends a bus ride exactly at planned arrival', () {
    expect(
      shouldCompleteBusFromSchedule(now: arrival, plannedArrivalAt: arrival),
      isTrue,
    );
    expect(
      shouldCompleteBusFromSchedule(
        now: arrival.subtract(const Duration(seconds: 1)),
        plannedArrivalAt: arrival,
      ),
      isFalse,
    );
    expect(
      shouldCompleteBusFromSchedule(
        now: arrival.add(const Duration(minutes: 5)),
        plannedArrivalAt: arrival,
      ),
      isTrue,
    );
  });
  test('missing realtime is retried only during the scheduled ride', () {
    final departure = arrival.subtract(const Duration(minutes: 44));
    expect(
      shouldRetryMissingBusRealtime(
        now: departure,
        plannedDepartureAt: departure,
        plannedArrivalAt: arrival,
      ),
      isTrue,
    );
    expect(
      shouldRetryMissingBusRealtime(
        now: arrival.subtract(const Duration(seconds: 1)),
        plannedDepartureAt: departure,
        plannedArrivalAt: arrival,
      ),
      isTrue,
    );
    expect(
      shouldRetryMissingBusRealtime(
        now: departure.subtract(const Duration(seconds: 1)),
        plannedDepartureAt: departure,
        plannedArrivalAt: arrival,
      ),
      isFalse,
    );
    expect(
      shouldRetryMissingBusRealtime(
        now: arrival,
        plannedDepartureAt: departure,
        plannedArrivalAt: arrival,
      ),
      isFalse,
    );
  });
  test('retry policy rejects an invalid schedule interval', () {
    expect(
      () => shouldRetryMissingBusRealtime(
        now: arrival,
        plannedDepartureAt: arrival,
        plannedArrivalAt: arrival,
      ),
      throwsArgumentError,
    );
  });
  test(
    'schedule completion invents neither boarding nor a raw vehicle position',
    () {
      final arrived = completeBusAtDestination(step: step);
      expect(arrived.phase, BusProgressPhase.arrived);
      expect(arrived.fromStopId, 's2');
      expect(arrived.fromStopIndex, 1);
      expect(arrived.nextStopId, isNull);
      expect(arrived.observedStopId, isNull);
      expect(arrived.currentStatus, isNull);
      expect(arrived.vehicleAgeSeconds, isNull);
    },
  );
  for (final phase in BusProgressPhase.values) {
    test(
      'completion cannot be blocked by an older ${phase.name} observation',
      () {
        final previous = BusProgress(
          stepId: 'bus-1',
          phase: phase,
          fromStopId: 's0',
          fromStopIndex: 0,
          nextStopId: 's2',
          nextStopIndex: 1,
          observedStopName: '新橋駅前',
          vehicleAgeSeconds: 5,
        );
        final arrived = completeBusAtDestination(
          step: step,
          lastProgress: previous,
        );
        expect(arrived.phase, BusProgressPhase.arrived);
        expect(arrived.fromStopId, 's2');
        expect(arrived.observedStopName, '新橋駅前');
        expect(arrived.vehicleAgeSeconds, 5);
      },
    );
  }
  test('completion rejects observations from another route step', () {
    const different = BusProgress(
      stepId: 'other',
      phase: BusProgressPhase.riding,
      fromStopId: 's0',
      fromStopIndex: 0,
      nextStopId: 's2',
      nextStopIndex: 1,
    );
    expect(
      () => completeBusAtDestination(step: step, lastProgress: different),
      throwsStateError,
    );
  });
  test('completion requires a bus and its destination stop', () {
    expect(
      () => completeBusAtDestination(
        step: StepSeg(stepId: 'walk', kind: 'walk', title: '歩く'),
      ),
      throwsStateError,
    );
    expect(
      () => completeBusAtDestination(
        step: StepSeg(stepId: 'bus', kind: 'bus', title: '都01'),
      ),
      throwsStateError,
    );
  });
}

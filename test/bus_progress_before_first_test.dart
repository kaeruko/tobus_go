import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  StepSeg busStep() => StepSeg(
    stepId: 'bus-1',
    kind: 'bus',
    title: '008系統',
    routeId: 'fixture_bus:008',
    tripId: 'fixture_bus:T1',
    stops: [
      StopPoint(
        name: '出発駅前',
        point: const LatLng(35.466, 139.622),
        stopId: 'fixture_bus:A',
      ),
      StopPoint(
        name: '山下公園前',
        point: const LatLng(35.444, 139.649),
        stopId: 'fixture_bus:B',
      ),
    ],
  );

  test('before first stop is approaching and has no departed stop', () {
    final progress = BusProgress.forStep(
      step: busStep(),
      fromStopId: null,
      beforeFirstStop: true,
      tripStopIds: const ['fixture_bus:A', 'fixture_bus:B'],
      observedStopId: 'A',
      observedStopName: '出発駅前',
      currentStatus: 'IN_TRANSIT_TO',
    );

    expect(progress.phase, BusProgressPhase.approaching);
    expect(progress.fromStopId, isNull);
    expect(progress.fromStopIndex, isNull);
    expect(progress.nextStopId, 'fixture_bus:A');
    expect(progress.nextStopIndex, 0);
    expect(progress.stopsUntilBoarding, 1);
  });

  test('before first stop counts trip stops until a later boarding stop', () {
    final step = StepSeg(
      stepId: 'bus-later',
      kind: 'bus',
      title: '008系統',
      routeId: 'fixture_bus:008',
      tripId: 'fixture_bus:T1',
      stops: [
        StopPoint(
          name: 'C停留所',
          point: const LatLng(35.450, 139.640),
          stopId: 'fixture_bus:C',
        ),
        StopPoint(
          name: 'D停留所',
          point: const LatLng(35.440, 139.650),
          stopId: 'fixture_bus:D',
        ),
      ],
    );

    final progress = BusProgress.forStep(
      step: step,
      fromStopId: null,
      beforeFirstStop: true,
      tripStopIds: const [
        'fixture_bus:A',
        'fixture_bus:B',
        'fixture_bus:C',
        'fixture_bus:D',
      ],
      observedStopId: 'fixture_bus:A',
      observedStopName: 'A停留所',
      currentStatus: 'IN_TRANSIT_TO',
    );

    expect(progress.phase, BusProgressPhase.approaching);
    expect(progress.stopsUntilBoarding, 3);
  });

  test(
    'null previous stop without the validated first-stop flag is an error',
    () {
      expect(
        () => BusProgress.forStep(
          step: busStep(),
          fromStopId: null,
          currentStatus: 'IN_TRANSIT_TO',
        ),
        throwsStateError,
      );
    },
  );

  test('before-first flag cannot coexist with a previous stop', () {
    expect(
      () => BusProgress.forStep(
        step: busStep(),
        fromStopId: 'fixture_bus:A',
        beforeFirstStop: true,
        currentStatus: 'IN_TRANSIT_TO',
      ),
      throwsStateError,
    );
  });
}

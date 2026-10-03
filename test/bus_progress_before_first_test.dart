import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  StepSeg busStep() => StepSeg(
    stepId: 'bus-1',
    kind: 'bus',
    title: '008系統',
    routeId: 'yokohama_bus:008',
    tripId: 'yokohama_bus:T1',
    stops: [
      StopPoint(
        name: '横浜駅前',
        point: const LatLng(35.466, 139.622),
        stopId: 'yokohama_bus:A',
      ),
      StopPoint(
        name: '山下公園前',
        point: const LatLng(35.444, 139.649),
        stopId: 'yokohama_bus:B',
      ),
    ],
  );

  test('before first stop is approaching and has no departed stop', () {
    final progress = BusProgress.forStep(
      step: busStep(),
      fromStopId: null,
      beforeFirstStop: true,
      tripStopIds: const ['yokohama_bus:A', 'yokohama_bus:B'],
      observedStopId: 'A',
      observedStopName: '横浜駅前',
      currentStatus: 'IN_TRANSIT_TO',
    );

    expect(progress.phase, BusProgressPhase.approaching);
    expect(progress.fromStopId, isNull);
    expect(progress.fromStopIndex, isNull);
    expect(progress.nextStopId, 'yokohama_bus:A');
    expect(progress.nextStopIndex, 0);
    expect(progress.stopsUntilBoarding, 1);
  });

  test('before first stop counts trip stops until a later boarding stop', () {
    final step = StepSeg(
      stepId: 'bus-later',
      kind: 'bus',
      title: '008系統',
      routeId: 'yokohama_bus:008',
      tripId: 'yokohama_bus:T1',
      stops: [
        StopPoint(
          name: 'C停留所',
          point: const LatLng(35.450, 139.640),
          stopId: 'yokohama_bus:C',
        ),
        StopPoint(
          name: 'D停留所',
          point: const LatLng(35.440, 139.650),
          stopId: 'yokohama_bus:D',
        ),
      ],
    );

    final progress = BusProgress.forStep(
      step: step,
      fromStopId: null,
      beforeFirstStop: true,
      tripStopIds: const [
        'yokohama_bus:A',
        'yokohama_bus:B',
        'yokohama_bus:C',
        'yokohama_bus:D',
      ],
      observedStopId: 'yokohama_bus:A',
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
        fromStopId: 'yokohama_bus:A',
        beforeFirstStop: true,
        currentStatus: 'IN_TRANSIT_TO',
      ),
      throwsStateError,
    );
  });
}

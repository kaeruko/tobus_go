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
      observedStopId: 'A',
      observedStopName: '横浜駅前',
      currentStatus: 'IN_TRANSIT_TO',
    );

    expect(progress.phase, BusProgressPhase.approaching);
    expect(progress.fromStopId, isNull);
    expect(progress.fromStopIndex, isNull);
    expect(progress.nextStopId, 'yokohama_bus:A');
    expect(progress.nextStopIndex, 0);
  });

  test('validated legacy null previous stop infers the same approaching state', () {
    final progress = BusProgress.forStep(
      step: busStep(),
      fromStopId: null,
      currentStatus: 'IN_TRANSIT_TO',
    );

    expect(progress.phase, BusProgressPhase.approaching);
    expect(progress.fromStopId, isNull);
  });

  test('null previous stop without first-stop status remains an error', () {
    expect(
      () => BusProgress.forStep(
        step: busStep(),
        fromStopId: null,
        currentStatus: 'STOPPED_AT',
      ),
      throwsStateError,
    );
  });

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

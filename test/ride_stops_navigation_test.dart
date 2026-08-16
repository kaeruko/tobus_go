import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/pages/ride_stops_navigation.dart';

void main() {
  test('現在の乗車stepを共通解決する', () {
    final ride = StepSeg(
      stepId: 'ride-1',
      kind: 'bus',
      title: '都02',
      stops: [
        StopPoint(name: 'A', point: const LatLng(35.0, 139.0)),
        StopPoint(name: 'B', point: const LatLng(35.1, 139.1)),
      ],
    );
    final trip = _tripWithSteps([ride]);

    final resolved = resolveCurrentRideStep(
      trip: trip,
      currentStepId: 'ride-1',
    );

    expect(resolved, same(ride));
  });

  test('徒歩中またはcurrentStep未確定なら開く対象なし', () {
    final walk = StepSeg(
      stepId: 'walk-1',
      kind: 'walk',
      title: '徒歩',
    );
    final trip = _tripWithSteps([walk]);

    expect(
      resolveCurrentRideStep(trip: trip, currentStepId: null),
      isNull,
    );
    expect(
      resolveCurrentRideStep(trip: trip, currentStepId: 'walk-1'),
      isNull,
    );
  });

  test('存在しないcurrentStepIdはfail-fastする', () {
    final trip = _tripWithSteps(const []);

    expect(
      () => resolveCurrentRideStep(
        trip: trip,
        currentStepId: 'missing-step',
      ),
      throwsStateError,
    );
  });
}

Trip _tripWithSteps(List<StepSeg> steps) {
  final candidate = Candidate(
    id: 'candidate-1',
    lines: const [],
    rides: 0,
    walks: 0,
    boards: 0,
    transfers: 0,
    total: 0,
    totalTime: 0,
    steps: steps,
    points: const [],
  );

  return Trip(
    tripType: TripType.solo,
    id: 'trip-1',
    joinCode: '',
    leaderId: 'user-1',
    title: 'test',
    travelPhase: TravelPhase.active,
    date: DateTime(2026, 8, 16),
    plannedDepartureAt: null,
    actualDepartureAt: null,
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: candidate,
      ),
    ],
    schedule: const [],
    participants: const [],
    memberIds: const [],
  );
}

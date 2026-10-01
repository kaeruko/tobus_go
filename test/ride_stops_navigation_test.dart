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

  test('待機中は次の乗車予定を経路案内対象にする', () {
    final ride = StepSeg(
      stepId: 'ride-1',
      kind: 'bus',
      title: '上23 上野松坂屋前行',
      stops: [
        StopPoint(name: 'A', point: const LatLng(35.0, 139.0)),
        StopPoint(name: 'B', point: const LatLng(35.1, 139.1)),
      ],
    );
    final candidate = Candidate(
      id: 'candidate-1',
      lines: const [],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 0,
      totalTime: 0,
      steps: [ride],
      points: const [],
    );
    final wait = ScheduleEntry(
      id: 'wait-1',
      plannedAt: DateTime(2026, 8, 16, 10, 30),
      label: '待ち時間',
      itemKind: ScheduleEntryKind.event,
      legIndex: 0,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'ride-1',
      routeRole: 'wait_start',
    );
    final rideEntry = ScheduleEntry(
      id: 'ride-entry-1',
      plannedAt: DateTime(2026, 8, 16, 10, 40),
      label: '上23に乗る',
      itemKind: ScheduleEntryKind.ride,
      legIndex: 0,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'ride-1',
      routeRole: 'ride',
    );
    final trip = Trip(
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
      schedule: [wait, rideEntry],
      participants: const [],
      memberIds: const [],
    );

    final rides = trip.schedule
        .where(
          (entry) =>
              entry.legIndex == wait.legIndex &&
              entry.itemKind == ScheduleEntryKind.ride &&
              !entry.plannedAt.isBefore(wait.plannedAt),
        )
        .toList()
      ..sort((a, b) => a.plannedAt.compareTo(b.plannedAt));

    expect(rides.single.id, 'ride-entry-1');
    expect(trip.stepsById[rides.single.routeStepId], same(ride));
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

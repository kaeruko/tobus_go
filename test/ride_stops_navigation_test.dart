import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/models/group_models.dart';
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

  for (final tripType in TripType.values) {
    test(
      '${tripType.name} 待機中の次便はplannedAtではなくCandidate順序で解決する',
      () {
        final waitStep = StepSeg(
          stepId: 'wait-1',
          kind: 'wait',
          title: '待ち時間',
        );
        final firstRide = StepSeg(
          stepId: 'ride-1',
          kind: 'bus',
          title: '上23 上野松坂屋前行',
          stops: [
            StopPoint(name: 'A', point: const LatLng(35.0, 139.0)),
            StopPoint(name: 'B', point: const LatLng(35.1, 139.1)),
          ],
        );
        final secondRide = StepSeg(
          stepId: 'ride-2',
          kind: 'rail',
          title: '浅草線',
          stops: [
            StopPoint(name: 'C', point: const LatLng(35.2, 139.2)),
            StopPoint(name: 'D', point: const LatLng(35.3, 139.3)),
          ],
        );
        final candidate = Candidate(
          id: 'candidate-${tripType.name}',
          lines: const [],
          rides: 2,
          boards: 2,
          transfers: 1,
          total: 0,
          totalTime: 0,
          steps: [waitStep, firstRide, secondRide],
          points: const [],
        );
        final wait = ScheduleEntry(
          id: 'wait-1-entry',
          plannedAt: DateTime(2026, 8, 16, 10, 30),
          label: '待ち時間',
          itemKind: ScheduleEntryKind.event,
          legIndex: 0,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'wait-1',
          routeRole: 'wait_start',
        );
        final firstRideEntry = ScheduleEntry(
          id: 'ride-entry-1',
          // Deliberately later than ride-2. Time ordering is corrupt, while
          // Candidate step order still identifies the actual next ride.
          plannedAt: DateTime(2026, 8, 16, 10, 50),
          label: '上23に乗る',
          itemKind: ScheduleEntryKind.ride,
          legIndex: 0,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'ride-1',
          routeRole: 'ride',
        );
        final secondRideEntry = ScheduleEntry(
          id: 'ride-entry-2',
          plannedAt: DateTime(2026, 8, 16, 10, 40),
          label: '浅草線に乗る',
          itemKind: ScheduleEntryKind.ride,
          legIndex: 0,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'ride-2',
          routeRole: 'ride',
        );
        final trip = _tripWithCandidate(
          tripType: tripType,
          candidate: candidate,
          schedule: [wait, firstRideEntry, secondRideEntry],
        );

        final resolved = resolveNavigationRideStep(
          trip: trip,
          resolvedEntry: wait,
          currentStepId: null,
        );

        expect(resolved, same(firstRide));
      },
    );

    test(
      '${tripType.name} 徒歩中の次便もCandidate順序で解決する',
      () {
        final walk = StepSeg(
          stepId: 'walk-1',
          kind: 'walk',
          title: '徒歩',
        );
        final ride = StepSeg(
          stepId: 'ride-after-walk',
          kind: 'bus',
          title: '都01',
          stops: [
            StopPoint(name: 'A', point: const LatLng(35.0, 139.0)),
            StopPoint(name: 'B', point: const LatLng(35.1, 139.1)),
          ],
        );
        final candidate = Candidate(
          id: 'walk-candidate-${tripType.name}',
          lines: const [],
          rides: 1,
          boards: 1,
          transfers: 0,
          total: 0,
          totalTime: 0,
          steps: [walk, ride],
          points: const [],
        );
        final walkEntry = ScheduleEntry(
          id: 'walk-entry',
          plannedAt: DateTime(2026, 8, 16, 10, 30),
          label: '停留所まで歩く',
          itemKind: ScheduleEntryKind.walk,
          legIndex: 0,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'walk-1',
          routeRole: 'walk',
        );
        final trip = _tripWithCandidate(
          tripType: tripType,
          candidate: candidate,
          schedule: [walkEntry],
        );

        expect(
          resolveNavigationRideStep(
            trip: trip,
            resolvedEntry: walkEntry,
            currentStepId: null,
          ),
          same(ride),
        );
      },
    );
  }

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

  test('予定行は全体経路と同じ停留所一覧・乗換案内だけを開ける', () {
    StopPoint stop(String name, double lat, double lon) => StopPoint(
          name: name,
          point: LatLng(lat, lon),
          stopId: 'stop-$name',
        );

    final originWalk = StepSeg(
      stepId: 'origin-walk',
      kind: 'walk',
      title: '徒歩',
      minutes: 5,
    );
    final arrivingBus = StepSeg(
      stepId: 'arriving-bus',
      kind: 'bus',
      title: '上23',
      routeId: 'route-ueno-23',
      tripId: 'trip-ueno-23',
      departureTime: '12:00',
      arrivalTime: '12:10',
      stops: [
        stop('中居堀', 35.710, 139.810),
        stop('上野松坂屋前', 35.711, 139.795),
      ],
    );
    final transferWalk = StepSeg(
      stepId: 'transfer-walk',
      kind: 'walk',
      title: '徒歩',
      minutes: 3,
    );
    final transferWait = StepSeg(
      stepId: 'transfer-wait',
      kind: 'wait',
      title: '待ち時間',
      minutes: 4,
    );
    final departingRail = StepSeg(
      stepId: 'departing-rail',
      kind: 'rail',
      title: '大江戸線',
      departureTime: '12:17',
      arrivalTime: '12:30',
      stops: [
        stop('上野御徒町', 35.712, 139.794),
        stop('東新宿', 35.698, 139.707),
      ],
    );
    final destinationWalk = StepSeg(
      stepId: 'destination-walk',
      kind: 'walk',
      title: '徒歩',
      minutes: 5,
    );
    final candidate = Candidate(
      id: 'schedule-details',
      lines: const ['上23', '大江戸線'],
      rides: 2,
      boards: 2,
      transfers: 1,
      total: 0,
      totalTime: 35,
      departureDate: DateTime(2026, 11, 1, 12),
      steps: [
        originWalk,
        arrivingBus,
        transferWalk,
        transferWait,
        departingRail,
        destinationWalk,
      ],
      points: const [],
    );
    final trip = _tripWithCandidate(
      tripType: TripType.solo,
      candidate: candidate,
    );

    ScheduleEntry entry(
      String id,
      StepSeg step,
      ScheduleEntryKind kind,
      String role,
    ) {
      return ScheduleEntry(
        id: id,
        plannedAt: DateTime(2026, 11, 1, 12),
        label: id,
        itemKind: kind,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
        routeRole: role,
      );
    }

    expect(
      canOpenScheduleEntryDetails(
        trip: trip,
        entry: entry(
          'bus-board',
          arrivingBus,
          ScheduleEntryKind.ride,
          'ride',
        ),
      ),
      isTrue,
    );
    expect(
      canOpenScheduleEntryDetails(
        trip: trip,
        entry: entry(
          'bus-arrive',
          arrivingBus,
          ScheduleEntryKind.arrival,
          'arrival',
        ),
      ),
      isTrue,
    );
    expect(
      canOpenScheduleEntryDetails(
        trip: trip,
        entry: entry(
          'transfer-walk',
          transferWalk,
          ScheduleEntryKind.walk,
          'walk',
        ),
      ),
      isTrue,
    );
    expect(
      canOpenScheduleEntryDetails(
        trip: trip,
        entry: entry(
          'transfer-wait',
          transferWait,
          ScheduleEntryKind.event,
          'wait_start',
        ),
      ),
      isTrue,
    );
    expect(
      canOpenScheduleEntryDetails(
        trip: trip,
        entry: entry(
          'origin-walk',
          originWalk,
          ScheduleEntryKind.walk,
          'walk',
        ),
      ),
      isFalse,
    );
    expect(
      canOpenScheduleEntryDetails(
        trip: trip,
        entry: entry(
          'destination-walk',
          destinationWalk,
          ScheduleEntryKind.walk,
          'walk',
        ),
      ),
      isFalse,
    );
  });
}

Trip _tripWithCandidate({
  required TripType tripType,
  required Candidate candidate,
  List<ScheduleEntry> schedule = const [],
}) {
  return Trip(
    tripType: tripType,
    id: 'trip-${tripType.name}',
    joinCode: tripType == TripType.group ? '123456' : '',
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
    schedule: schedule,
    participants: const [],
    memberIds: const [],
  );
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

  return _tripWithCandidate(
    tripType: TripType.solo,
    candidate: candidate,
  );
}

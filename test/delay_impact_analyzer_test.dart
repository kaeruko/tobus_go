import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/delay_impact_analyzer.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  StepSeg currentRide() => StepSeg(
    stepId: 'rail-1',
    kind: 'rail',
    title: '浅草線 青砥行',
    fromName: '浅草橋',
    toName: '東日本橋',
    departureTime: '18:00',
    arrivalTime: '18:10',
    minutes: 10,
    stops: [
      StopPoint(
        name: '浅草橋',
        point: const LatLng(35.697, 139.785),
      ),
      StopPoint(
        name: '東日本橋',
        point: const LatLng(35.692, 139.785),
      ),
    ],
  );

  StepSeg transferWalk({int minutes = 4}) => StepSeg(
    stepId: 'walk-transfer',
    kind: 'walk',
    title: '徒歩',
    fromName: '東日本橋',
    toName: '馬喰横山',
    departureTime: '18:10',
    arrivalTime: '18:14',
    minutes: minutes,
  );

  StepSeg nextRide() => StepSeg(
    stepId: 'rail-2',
    kind: 'rail',
    title: '新宿線 本八幡行',
    fromName: '馬喰横山',
    toName: '目的地最寄り',
    departureTime: '18:16',
    arrivalTime: '18:25',
    minutes: 9,
    stops: [
      StopPoint(
        name: '馬喰横山',
        point: const LatLng(35.692, 139.782),
      ),
      StopPoint(
        name: '目的地最寄り',
        point: const LatLng(35.691, 139.781),
      ),
    ],
  );

  Trip buildTrip({
    int walkMinutes = 4,
    DateTime? nextDeparture,
    bool includeNextRide = true,
  }) {
    final steps = <StepSeg>[
      currentRide(),
      if (includeNextRide) transferWalk(minutes: walkMinutes),
      if (includeNextRide) nextRide(),
    ];
    final candidate = Candidate(
      id: 'candidate',
      lines: const ['浅草線', '新宿線'],
      rides: includeNextRide ? 2 : 1,
      walks: includeNextRide ? 1 : 0,
      boards: includeNextRide ? 2 : 1,
      transfers: includeNextRide ? 1 : 0,
      total: 25,
      totalTime: 25,
      steps: steps,
      points: const [],
      originName: '出発地',
      destinationName: '目的地',
      originCoords: const LatLng(35.697, 139.785),
      destinationCoords: const LatLng(35.691, 139.781),
    );

    final schedule = <ScheduleEntry>[
      ScheduleEntry(
        id: 'ride-1',
        plannedAt: DateTime(2026, 8, 15, 18, 0),
        label: '浅草線に乗る',
        itemKind: ScheduleEntryKind.ride,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'rail-1',
        routeRole: 'ride',
      ),
      ScheduleEntry(
        id: 'arrival-1',
        plannedAt: DateTime(2026, 8, 15, 18, 10),
        label: '東日本橋に着く',
        itemKind: ScheduleEntryKind.arrival,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'rail-1',
        routeRole: 'arrival',
      ),
      if (includeNextRide)
        ScheduleEntry(
          id: 'walk-transfer',
          plannedAt: DateTime(2026, 8, 15, 18, 10),
          label: '馬喰横山まで歩く',
          itemKind: ScheduleEntryKind.walk,
          legIndex: 0,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'walk-transfer',
          routeRole: 'walk',
        ),
      if (includeNextRide)
        ScheduleEntry(
          id: 'ride-2',
          plannedAt: nextDeparture ?? DateTime(2026, 8, 15, 18, 16),
          label: '新宿線に乗る',
          itemKind: ScheduleEntryKind.ride,
          legIndex: 0,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'rail-2',
          routeRole: 'ride',
        ),
    ];

    return Trip(
      tripType: TripType.solo,
      id: 'trip-delay',
      joinCode: '',
      leaderId: 'user',
      title: 'test',
      travelPhase: TravelPhase.active,
      date: DateTime(2026, 8, 15),
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
      memberIds: const ['user'],
    );
  }

  RidingTransitObservation observation(DateTime? predictedArrival) {
    return RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.inTransit,
      nextPlace: ReplanTransitPlace(
        name: '蔵前',
        point: const LatLng(35.703, 139.790),
      ),
      predictedNextAvailableAt: DateTime(2026, 8, 15, 18, 6),
      predictedDestinationAvailableAt: predictedArrival,
    );
  }

  test('predicted arrival plus explicit walk still catches next ride', () {
    final impact = DelayImpactAnalyzer.analyze(
      trip: buildTrip(),
      observation: observation(DateTime(2026, 8, 15, 18, 11)),
    );

    expect(impact, isNotNull);
    expect(impact!.nextTransferFeasible, isTrue);
    expect(impact.transferWalkMinutes, 4);
    expect(impact.earliestTransferReadyAt, DateTime(2026, 8, 15, 18, 15));
    expect(impact.missedBy, Duration.zero);
  });

  test('warns when predicted arrival plus walk is after next departure', () {
    final impact = DelayImpactAnalyzer.analyze(
      trip: buildTrip(),
      observation: observation(DateTime(2026, 8, 15, 18, 13)),
    );

    expect(impact, isNotNull);
    expect(impact!.requiresReplan, isTrue);
    expect(impact.earliestTransferReadyAt, DateTime(2026, 8, 15, 18, 17));
    expect(impact.nextDepartureAt, DateTime(2026, 8, 15, 18, 16));
    expect(impact.missedBy, const Duration(minutes: 1));
  });

  test('no later ride means there is no transfer impact', () {
    final impact = DelayImpactAnalyzer.analyze(
      trip: buildTrip(includeNextRide: false),
      observation: observation(DateTime(2026, 8, 15, 18, 13)),
    );

    expect(impact, isNull);
  });

  test('missing realtime destination estimate fails instead of guessing', () {
    expect(
      () => DelayImpactAnalyzer.analyze(
        trip: buildTrip(),
        observation: observation(null),
      ),
      throwsStateError,
    );
  });

  test('invalid baseline transfer fails instead of blaming realtime delay', () {
    expect(
      () => DelayImpactAnalyzer.analyze(
        trip: buildTrip(
          walkMinutes: 4,
          nextDeparture: DateTime(2026, 8, 15, 18, 13),
        ),
        observation: observation(DateTime(2026, 8, 15, 18, 11)),
      ),
      throwsStateError,
    );
  });
}

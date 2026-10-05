import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/group_schedule_impact.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  StepSeg finalRide({String stepId = 'rail-final'}) => StepSeg(
    stepId: stepId,
    kind: 'rail',
    title: '浅草線 青砥行',
    fromName: '浅草橋',
    toName: '東日本橋',
    departureTime: '18:20',
    arrivalTime: '18:35',
    minutes: 15,
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

  StepSeg finalWalk({
    String arrivalTime = '18:40',
    int minutes = 5,
  }) => StepSeg(
    stepId: 'walk-final',
    kind: 'walk',
    title: '徒歩',
    fromName: '東日本橋',
    toName: '目的地',
    departureTime: '18:35',
    arrivalTime: arrivalTime,
    minutes: minutes,
  );

  Trip buildTrip({
    DateTime? canonicalGoalAt,
    DateTime? storedGoalAt,
    DateTime? manualAt,
    Duration storedRideArrivalShift = Duration.zero,
    bool includeLaterRide = false,
  }) {
    final serviceDay = DateTime(2026, 8, 15);
    final canonicalGoal =
        canonicalGoalAt ?? DateTime(2026, 8, 15, 18, 40);
    final finalRideArrival = DateTime(2026, 8, 15, 18, 35);
    final walkMinutes = canonicalGoal.difference(finalRideArrival).inMinutes;
    if (walkMinutes < 0) {
      throw StateError('test route goal must not precede final ride arrival');
    }
    String clock(DateTime value) =>
        '${value.hour.toString().padLeft(2, '0')}:'
        '${value.minute.toString().padLeft(2, '0')}';

    final firstRide = finalRide(stepId: 'rail-1');
    final steps = <StepSeg>[
      firstRide,
      finalWalk(arrivalTime: clock(canonicalGoal), minutes: walkMinutes),
    ];
    if (includeLaterRide) {
      steps.add(
        StepSeg(
          stepId: 'rail-2',
          kind: 'rail',
          title: '新宿線 本八幡行',
          fromName: '目的地',
          toName: 'さらに先',
          departureTime: '18:45',
          arrivalTime: '18:55',
          minutes: 10,
          stops: [
            StopPoint(
              name: '目的地',
              point: const LatLng(35.691, 139.781),
            ),
            StopPoint(
              name: 'さらに先',
              point: const LatLng(35.690, 139.780),
            ),
          ],
        ),
      );
    }

    final candidate = Candidate(
      id: 'candidate',
      lines: const ['浅草線'],
      rides: includeLaterRide ? 2 : 1,
      boards: includeLaterRide ? 2 : 1,
      transfers: includeLaterRide ? 1 : 0,
      total: 20,
      totalTime: 20,
      steps: steps,
      points: const [],
      originName: '浅草橋',
      destinationName: includeLaterRide ? 'さらに先' : '目的地',
      originCoords: const LatLng(35.697, 139.785),
      destinationCoords: const LatLng(35.691, 139.781),
      departureDate: DateTime(2026, 8, 15, 18, 20),
    );

    final schedule = <ScheduleEntry>[
      ScheduleEntry(
        id: 'ride-1',
        plannedAt: DateTime(2026, 8, 15, 18, 20),
        label: '浅草線に乗る',
        itemKind: ScheduleEntryKind.ride,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'rail-1',
        routeRole: 'ride',
      ),
      ScheduleEntry(
        id: 'arrival-1',
        plannedAt: finalRideArrival.add(storedRideArrivalShift),
        label: '東日本橋に着く',
        itemKind: ScheduleEntryKind.arrival,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'rail-1',
        routeRole: 'arrival',
      ),
      ScheduleEntry(
        id: 'walk-final',
        plannedAt: finalRideArrival.add(storedRideArrivalShift),
        label: '目的地まで歩く',
        itemKind: ScheduleEntryKind.walk,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'walk-final',
        routeRole: 'walk',
      ),
      ScheduleEntry(
        id: 'goal',
        plannedAt: storedGoalAt ?? canonicalGoal,
        label: '目的地 到着',
        itemKind: ScheduleEntryKind.goal,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
      ),
      ScheduleEntry(
        id: 'manual-rest',
        plannedAt: manualAt ?? DateTime(2026, 8, 15, 18, 40),
        label: '休憩開始',
        itemKind: ScheduleEntryKind.event,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.manual,
      ),
    ];

    return Trip(
      tripType: TripType.group,
      id: 'group-trip',
      joinCode: '123456',
      leaderId: 'leader',
      title: 'test',
      travelPhase: TravelPhase.active,
      date: serviceDay,
      plannedDepartureAt: null,
      actualDepartureAt: DateTime(2026, 8, 15, 18, 0),
      legs: [
        Leg(
          direction: LegDirection.outbound,
          status: LegStatus.confirmed,
          candidate: candidate,
        ),
      ],
      schedule: schedule,
      participants: const [],
      memberIds: const ['leader'],
    );
  }

  RidingTransitObservation finalRideObservation(DateTime predictedArrival) {
    return RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.inTransit,
      nextPlace: ReplanTransitPlace(
        name: '東日本橋',
        point: const LatLng(35.692, 139.785),
      ),
      predictedNextAvailableAt: predictedArrival,
      predictedDestinationAvailableAt: predictedArrival,
    );
  }

  test('final ride realtime projects through remaining walk to group goal', () {
    final trip = buildTrip();
    final arrival = GroupScheduleImpactAnalyzer.estimateFromFinalRideRealtime(
      trip: trip,
      observation: finalRideObservation(
        DateTime(2026, 8, 15, 18, 50),
      ),
    );

    expect(arrival, isNotNull);
    expect(arrival!.basis, GroupArrivalEstimateBasis.finalRideRealtime);
    expect(arrival.expectedArrivalAt, DateTime(2026, 8, 15, 18, 55));

    final impact = GroupScheduleImpactAnalyzer.findFirstManualConflict(
      trip: trip,
      arrival: arrival,
    );
    expect(impact, isNotNull);
    expect(impact!.affectedEntry.label, '休憩開始');
    expect(impact.overrun, const Duration(minutes: 15));
  });

  test('replanned route goal later than manual event warns without shifting it', () {
    final trip = buildTrip(
      canonicalGoalAt: DateTime(2026, 8, 15, 18, 55),
      manualAt: DateTime(2026, 8, 15, 18, 40),
    );
    final arrival = GroupScheduleImpactAnalyzer.estimateFromRouteSchedule(
      trip: trip,
      legIndex: 0,
    );
    final impact = GroupScheduleImpactAnalyzer.findFirstManualConflict(
      trip: trip,
      arrival: arrival,
    );

    expect(arrival.basis, GroupArrivalEstimateBasis.routeSchedule);
    expect(impact, isNotNull);
    expect(impact!.overrun, const Duration(minutes: 15));
    expect(impact.affectedEntry.plannedAt, DateTime(2026, 8, 15, 18, 40));
  });

  test('missed manual event remains visible while the same leg is late', () {
    final trip = buildTrip(
      canonicalGoalAt: DateTime(2026, 8, 15, 18, 55),
      manualAt: DateTime(2026, 8, 15, 18, 40),
    );
    final arrival = GroupScheduleImpactAnalyzer.estimateFromRouteSchedule(
      trip: trip,
      legIndex: 0,
    );
    final impact = GroupScheduleImpactAnalyzer.findFirstManualConflict(
      trip: trip,
      arrival: arrival,
    );

    expect(impact, isNotNull);
    expect(impact!.affectedEntry.label, '休憩開始');
  });

  test('route schedule estimate ignores a shifted saved goal clock', () {
    final trip = buildTrip(
      storedGoalAt: DateTime(2026, 8, 15, 18, 43),
      manualAt: DateTime(2026, 8, 15, 18, 41),
    );

    final arrival = GroupScheduleImpactAnalyzer.estimateFromRouteSchedule(
      trip: trip,
      legIndex: 0,
    );

    expect(arrival.plannedArrivalAt, DateTime(2026, 8, 15, 18, 40));
    expect(arrival.expectedArrivalAt, DateTime(2026, 8, 15, 18, 40));
    expect(
      GroupScheduleImpactAnalyzer.findFirstManualConflict(
        trip: trip,
        arrival: arrival,
      ),
      isNull,
    );
  });

  test('final ride realtime ignores a shifted saved ride arrival clock', () {
    final trip = buildTrip(
      storedRideArrivalShift: const Duration(minutes: 3),
    );

    final arrival = GroupScheduleImpactAnalyzer.estimateFromFinalRideRealtime(
      trip: trip,
      observation: finalRideObservation(
        DateTime(2026, 8, 15, 18, 50),
      ),
    );

    expect(arrival, isNotNull);
    expect(arrival!.plannedArrivalAt, DateTime(2026, 8, 15, 18, 40));
    expect(arrival.expectedArrivalAt, DateTime(2026, 8, 15, 18, 55));
  });

  test('current ride delay is not projected through a later transit service', () {
    final trip = buildTrip(includeLaterRide: true);
    final arrival = GroupScheduleImpactAnalyzer.estimateFromFinalRideRealtime(
      trip: trip,
      observation: finalRideObservation(
        DateTime(2026, 8, 15, 18, 50),
      ),
    );

    expect(arrival, isNull);
  });
}

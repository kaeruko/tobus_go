import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/group_schedule_impact.dart';
import 'package:toeigo/logic/group_schedule_shift.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  Candidate candidate(String id) => Candidate(
        id: id,
        lines: const [],
        rides: 0,
        boards: 0,
        transfers: 0,
        total: 0,
        totalTime: 0,
        steps: const [],
        points: const [],
      );

  Trip buildTrip() {
    final schedule = <ScheduleEntry>[
      ScheduleEntry(
        id: 'route-goal',
        plannedAt: DateTime(2026, 8, 15, 18, 55),
        label: '目的地 到着',
        itemKind: ScheduleEntryKind.goal,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
      ),
      ScheduleEntry(
        id: 'manual-before',
        plannedAt: DateTime(2026, 8, 15, 18, 20),
        label: '集合確認',
        legIndex: 0,
        generatedBy: ScheduleEntrySource.manual,
      ),
      ScheduleEntry(
        id: 'manual-rest',
        plannedAt: DateTime(2026, 8, 15, 18, 40),
        label: '休憩開始',
        legIndex: 0,
        generatedBy: ScheduleEntrySource.manual,
      ),
      ScheduleEntry(
        id: 'manual-event',
        plannedAt: DateTime(2026, 8, 15, 19, 10),
        label: '見学開始',
        legIndex: 0,
        generatedBy: ScheduleEntrySource.manual,
      ),
      ScheduleEntry(
        id: 'inbound-meeting',
        plannedAt: DateTime(2026, 8, 15, 20, 0),
        label: '帰りの集合',
        itemKind: ScheduleEntryKind.meeting,
        legIndex: 1,
        generatedBy: ScheduleEntrySource.manual,
      ),
      ScheduleEntry(
        id: 'inbound-route',
        plannedAt: DateTime(2026, 8, 15, 20, 10),
        label: '帰りの電車',
        itemKind: ScheduleEntryKind.ride,
        legIndex: 1,
        generatedBy: ScheduleEntrySource.route,
      ),
    ];

    return Trip(
      tripType: TripType.group,
      id: 'trip',
      joinCode: '123456',
      leaderId: 'leader',
      title: 'test',
      travelPhase: TravelPhase.active,
      date: DateTime(2026, 8, 15),
      plannedDepartureAt: null,
      actualDepartureAt: DateTime(2026, 8, 15, 18, 0),
      legs: [
        Leg(
          direction: LegDirection.outbound,
          status: LegStatus.confirmed,
          candidate: candidate('outbound'),
        ),
        Leg(
          direction: LegDirection.inbound,
          status: LegStatus.confirmed,
          candidate: candidate('inbound'),
        ),
      ],
      schedule: schedule,
      participants: const [],
      memberIds: const ['leader'],
    );
  }

  GroupScheduleImpact impactFor(Trip trip, Duration overrun) {
    final affected = trip.schedule.singleWhere((e) => e.id == 'manual-rest');
    return GroupScheduleImpact(
      arrival: GroupArrivalEstimate(
        legIndex: 0,
        plannedArrivalAt: DateTime(2026, 8, 15, 18, 40),
        expectedArrivalAt: DateTime(2026, 8, 15, 18, 40).add(overrun),
        basis: GroupArrivalEstimateBasis.finalRideRealtime,
      ),
      affectedEntry: affected,
      overrun: overrun,
    );
  }

  test('shifts only manual entries at and after affected entry in same leg', () {
    final trip = buildTrip();
    final plan = GroupScheduleShiftPlanner.build(
      trip: trip,
      impact: impactFor(trip, const Duration(minutes: 15)),
    );

    expect(plan.shift, const Duration(minutes: 15));
    expect(plan.targets.map((target) => target.entryId).toList(), [
      'manual-rest',
      'manual-event',
    ]);
    expect(
      plan.targets[0].shiftedPlannedAt,
      DateTime(2026, 8, 15, 18, 55),
    );
    expect(
      plan.targets[1].shiftedPlannedAt,
      DateTime(2026, 8, 15, 19, 25),
    );
  });

  test('rounds a positive sub-minute overrun upward to a whole minute', () {
    final trip = buildTrip();
    final plan = GroupScheduleShiftPlanner.build(
      trip: trip,
      impact: impactFor(trip, const Duration(minutes: 15, seconds: 1)),
    );

    expect(plan.shift, const Duration(minutes: 16));
  });

  test('does not include route entries or another leg return schedule', () {
    final trip = buildTrip();
    final plan = GroupScheduleShiftPlanner.build(
      trip: trip,
      impact: impactFor(trip, const Duration(minutes: 15)),
    );
    final ids = plan.targets.map((target) => target.entryId).toSet();

    expect(ids.contains('route-goal'), isFalse);
    expect(ids.contains('manual-before'), isFalse);
    expect(ids.contains('inbound-meeting'), isFalse);
    expect(ids.contains('inbound-route'), isFalse);
  });

  test('fails fast if affected entry is not manual', () {
    final trip = buildTrip();
    final routeEntry = trip.schedule.singleWhere((e) => e.id == 'route-goal');
    final impact = GroupScheduleImpact(
      arrival: GroupArrivalEstimate(
        legIndex: 0,
        plannedArrivalAt: routeEntry.plannedAt,
        expectedArrivalAt: routeEntry.plannedAt.add(const Duration(minutes: 5)),
        basis: GroupArrivalEstimateBasis.routeSchedule,
      ),
      affectedEntry: routeEntry,
      overrun: const Duration(minutes: 5),
    );

    expect(
      () => GroupScheduleShiftPlanner.build(trip: trip, impact: impact),
      throwsStateError,
    );
  });
}

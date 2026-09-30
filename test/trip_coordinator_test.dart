import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  group('TripCoordinator', () {
    test('shows the first departure time before the schedule starts', () {
      final trip = navigationV2Trip();
      final firstEntry = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 8, 29),
        label: '平井七丁目まで歩く',
        itemKind: ScheduleEntryKind.walk,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'walk-A',
      );
      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: [firstEntry],
        now: DateTime(2025, 1, 1, 8, 24),
      );

      final navigation = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        routeState: RouteState(stepsById: trip.stepsById),
        now: DateTime(2025, 1, 1, 8, 24),
        resolvedState: resolved,
      );

      expect(resolved.resolvedEntry, isNull);
      expect(navigation.mainText, '出発前');
      expect(navigation.subText, '8:29 出発予定');
      expect(navigation.statusLabel, '開始前');
    });

    test('wait before walk shows departure countdown and boarding time', () {
      final schedule = [
        ScheduleEntry(
          id: 'wait-start',
          plannedAt: DateTime(2025, 1, 1, 9, 51),
          label: '待ち時間 現在地 (9分)',
          itemKind: ScheduleEntryKind.event,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'wait-B',
          routeRole: 'wait_start',
        ),
        ScheduleEntry(
          id: 'walk-start',
          plannedAt: DateTime(2025, 1, 1, 10, 0),
          label: '平井七丁目まで歩く (4分)',
          itemKind: ScheduleEntryKind.walk,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'walk-A',
          routeRole: 'walk',
        ),
        ScheduleEntry(
          id: 'ride-start',
          plannedAt: DateTime(2025, 1, 1, 10, 4),
          label: '🚌上23 平井七丁目に乗る',
          itemKind: ScheduleEntryKind.ride,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'bus-C',
          routeRole: 'ride',
        ),
      ];
      final baseTrip = navigationV2Trip();
      final trip = Trip(
        schemaVersion: baseTrip.schemaVersion,
        tripType: baseTrip.tripType,
        id: baseTrip.id,
        joinCode: baseTrip.joinCode,
        leaderId: baseTrip.leaderId,
        title: baseTrip.title,
        travelPhase: baseTrip.travelPhase,
        date: baseTrip.date,
        plannedDepartureAt: baseTrip.plannedDepartureAt,
        actualDepartureAt: baseTrip.actualDepartureAt,
        legs: baseTrip.legs,
        schedule: schedule,
        participants: baseTrip.participants,
        memberIds: baseTrip.memberIds,
        completedLegIndex: baseTrip.completedLegIndex,
        staffNotes: baseTrip.staffNotes,
      );
      final now = DateTime(2025, 1, 1, 9, 52);
      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: trip.schedule,
        now: now,
      );

      final navigation = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        routeState: RouteState(stepsById: trip.stepsById),
        now: now,
        resolvedState: resolved,
      );

      expect(resolved.resolvedEntry?.id, 'wait-start');
      expect(navigation.mainText, '10:00 出発　あと8分');
      expect(navigation.subText, '10:04 上23 乗車');
      expect(navigation.statusLabel, '待機');
    });

    test('walk before ride shows boarding countdown and boarding time', () {
      final schedule = [
        ScheduleEntry(
          id: 'walk-start',
          plannedAt: DateTime(2025, 1, 1, 10, 0),
          label: '平井七丁目まで歩く (4分)',
          itemKind: ScheduleEntryKind.walk,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'walk-A',
          routeRole: 'walk',
        ),
        ScheduleEntry(
          id: 'ride-start',
          plannedAt: DateTime(2025, 1, 1, 10, 4),
          label: '🚌上23 平井七丁目に乗る',
          itemKind: ScheduleEntryKind.ride,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: 'bus-C',
          routeRole: 'ride',
        ),
      ];
      final baseTrip = navigationV2Trip();
      final trip = Trip(
        schemaVersion: baseTrip.schemaVersion,
        tripType: baseTrip.tripType,
        id: baseTrip.id,
        joinCode: baseTrip.joinCode,
        leaderId: baseTrip.leaderId,
        title: baseTrip.title,
        travelPhase: baseTrip.travelPhase,
        date: baseTrip.date,
        plannedDepartureAt: baseTrip.plannedDepartureAt,
        actualDepartureAt: baseTrip.actualDepartureAt,
        legs: baseTrip.legs,
        schedule: schedule,
        participants: baseTrip.participants,
        memberIds: baseTrip.memberIds,
        completedLegIndex: baseTrip.completedLegIndex,
        staffNotes: baseTrip.staffNotes,
      );
      final now = DateTime(2025, 1, 1, 10, 2);
      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: trip.schedule,
        now: now,
      );

      final navigation = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        routeState: RouteState(stepsById: trip.stepsById),
        now: now,
        resolvedState: resolved,
      );

      expect(resolved.resolvedEntry?.id, 'walk-start');
      expect(navigation.mainText, '10:04 平井七丁目にむかう　あと2分');
      expect(navigation.subText, '10:04 上23 乗車');
      expect(navigation.statusLabel, '移動中');
    });

    test('goal navigation carries bilingual destination and localized completion text', () {
      final base = navigationV2Trip();
      final baseCandidate = base.legs.first.candidate;
      final candidate = Candidate(
        id: baseCandidate.id,
        lines: baseCandidate.lines,
        linesEn: baseCandidate.linesEn,
        rides: baseCandidate.rides,
        boards: baseCandidate.boards,
        transfers: baseCandidate.transfers,
        total: baseCandidate.total,
        totalTime: baseCandidate.totalTime,
        steps: baseCandidate.steps,
        points: baseCandidate.points,
        originName: '押上',
        originNameEn: 'Oshiage',
        destinationName: '上野駅',
        destinationNameEn: 'Ueno Station',
      );
      final goal = ScheduleEntry(
        id: 'goal-en',
        plannedAt: DateTime(2025, 1, 1, 10, 51),
        label: '上野駅 到着',
        description: 'お疲れ様でした!',
        itemKind: ScheduleEntryKind.goal,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
      );
      final trip = Trip(
        schemaVersion: base.schemaVersion,
        tripType: base.tripType,
        id: base.id,
        joinCode: base.joinCode,
        leaderId: base.leaderId,
        title: base.title,
        travelPhase: base.travelPhase,
        date: base.date,
        plannedDepartureAt: base.plannedDepartureAt,
        actualDepartureAt: base.actualDepartureAt,
        legs: [
          Leg(
            direction: LegDirection.outbound,
            status: LegStatus.confirmed,
            candidate: candidate,
          ),
        ],
        schedule: [goal],
        participants: base.participants,
        memberIds: base.memberIds,
      );
      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: trip.schedule,
        now: goal.plannedAt,
      );

      final navigation = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        routeState: RouteState(stepsById: trip.stepsById),
        now: goal.plannedAt,
        resolvedState: resolved,
      );

      expect(navigation.mainText, '上野駅');
      expect(navigation.mainTextToken?.key, NavigationTextKey.goalArrivedMain);
      expect(
        navigation.mainTextToken?.args,
        containsPair('destination', '上野駅'),
      );
      expect(
        navigation.mainTextToken?.args,
        containsPair('destinationEn', 'Ueno Station'),
      );
      expect(navigation.subTextToken?.key, NavigationTextKey.tripEndedSub);
      expect(navigation.statusLabelToken?.key, NavigationTextKey.arrivedStatus);
    });

    test('meeting entries do not need a route step', () {
      final trip = navigationV2Trip();
      final entry = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 9, 50),
        label: '集合',
        itemKind: ScheduleEntryKind.meeting,
        generatedBy: ScheduleEntrySource.route,
      );
      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: [entry],
        now: DateTime(2025, 1, 1, 9, 50),
      );

      final navigation = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        routeState: RouteState(stepsById: trip.stepsById),
        now: DateTime(2025, 1, 1, 9, 50),
        resolvedState: resolved,
      );

      expect(navigation.statusLabel, '集合');
      expect(navigation.currentStepId, isNull);
    });

    test('route movement entries fail fast without routeStepId', () {
      final entry = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10),
        label: '徒歩',
        itemKind: ScheduleEntryKind.walk,
        generatedBy: ScheduleEntrySource.route,
      );

      expect(
        () => TripCoordinator.resolveScheduleState(
          scheduleEntries: [entry],
          now: DateTime(2025, 1, 1, 10),
        ),
        throwsStateError,
      );
    });
  });
}

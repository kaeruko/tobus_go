import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/schedule_resolver.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  group('ScheduleResolver Ride Logic', () {
    test('should NOT select Ride step 14 minutes before departure', () {
      final now = DateTime(2025, 1, 1, 7, 46);
      final waitTime = DateTime(2025, 1, 1, 7, 51); // 5 mins later
      final rideTime = DateTime(2025, 1, 1, 8, 01); // 15 mins later (14 mins from 08:00)

      final schedule = [
        ScheduleEntry(
          plannedAt: waitTime,
          label: 'Wait',
          itemKind: ScheduleEntryKind.departure,
        ),
        ScheduleEntry(
          plannedAt: rideTime,
          label: 'Bus Ride',
          itemKind: ScheduleEntryKind.ride,
        ),
      ];

      final result = ScheduleResolver.resolve(
        scheduleSorted: schedule,
        now: now,
      );

      // Should pick Wait (diff +5) over Ride (diff +15, not allowed > 5)
      expect(result.activeEntry?.label, 'Wait');
      expect(result.activeIndex, 0);
    });

    test('should select Ride step 3 minutes before departure', () {
      final now = DateTime(2025, 1, 1, 7, 58);
      final waitTime = DateTime(2025, 1, 1, 7, 51); // -7 mins
      final rideTime = DateTime(2025, 1, 1, 8, 01); // +3 mins

      final schedule = [
        ScheduleEntry(
          plannedAt: waitTime,
          label: 'Wait',
          itemKind: ScheduleEntryKind.departure,
        ),
        ScheduleEntry(
          plannedAt: rideTime,
          label: 'Bus Ride',
          itemKind: ScheduleEntryKind.ride,
        ),
      ];

      final result = ScheduleResolver.resolve(
        scheduleSorted: schedule,
        now: now,
      );

      // Ride: diff +3 (score 3). Allowed.
      // Wait: diff -7 (score 7.5). Allowed.
      // Ride wins.
      expect(result.activeEntry?.label, 'Bus Ride');
      expect(result.activeIndex, 1);
    });
    
    test('should select Ride during the ride (past)', () {
      final now = DateTime(2025, 1, 1, 8, 10);
      final rideTime = DateTime(2025, 1, 1, 8, 01); // -9 mins

      final schedule = [
        ScheduleEntry(
          plannedAt: rideTime,
          label: 'Bus Ride',
          itemKind: ScheduleEntryKind.ride,
        ),
      ];

      final result = ScheduleResolver.resolve(
        scheduleSorted: schedule,
        now: now,
      );
      
      // Ride: diff -9. Allowed (-60 < -9). Score 9.5.
      expect(result.activeEntry?.label, 'Bus Ride');
      expect(result.activeIndex, 0);
    });

    test('should select active even if all are future but within threshold', () {
       // Only Wait step, 5 mins away.
      final now = DateTime(2025, 1, 1, 7, 46);
      final waitTime = DateTime(2025, 1, 1, 7, 51); // +5 mins
      
      final schedule = [
        ScheduleEntry(
          plannedAt: waitTime,
          label: 'Wait',
          itemKind: ScheduleEntryKind.departure,
        ),
      ];
      
      final result = ScheduleResolver.resolve(
        scheduleSorted: schedule,
        now: now,
      );

      // Wait: diff +5. Kind=Departure. Threshold +10. Allowed.
      expect(result.activeEntry?.label, 'Wait');
    });

    test('TripCoordinator keeps ride active when departure time has arrived', () {
      final now = DateTime(2025, 1, 1, 8, 5);
      final rideTime = DateTime(2025, 1, 1, 8, 0);
      final waitTime = DateTime(2025, 1, 1, 7, 55);

      final waitEntry = ScheduleEntry(
        plannedAt: waitTime,
        label: 'Wait',
        itemKind: ScheduleEntryKind.event,
        generatedBy: ScheduleEntrySource.route,
        routeRole: 'wait_start',
      );

      final rideEntry = ScheduleEntry(
        plannedAt: rideTime,
        label: 'Bus Ride',
        itemKind: ScheduleEntryKind.ride,
        routeStepIndex: 0,
      );

      final routeState = RouteState(
        steps: [
          StepSeg(
            kind: 'bus',
            title: 'Bus',
          )
        ],
        currentStepIndex: 0,
        nextStopIndex: 0,
      );

      final trip = Trip(
        id: 't1',
        joinCode: '123456',
        leaderId: 'leader',
        title: 'Test Trip',
        travelPhase: TravelPhase.active,
        date: DateTime(2025, 1, 1),
        plannedDepartureAt: rideTime,
        actualDepartureAt: null,
        legs: const [],
        schedule: const [],
        participants: const [],
        memberIds: const [],
      );

      final scheduleState = ScheduleResolveResult(
        activeIndex: 1,
        activeLabel: 'Ride',
        completedCount: 1,
        window: [waitEntry, rideEntry],
        activeEntry: rideEntry,
      );

      final navState = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        scheduleState: scheduleState,
        routeState: routeState,
        now: now,
        realtimeBusLocationId: null,
      );

      expect(navState.statusLabel, '乗車中');
      expect(navState.step?.kind, 'bus');
    });
  });
}

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/logic/trip_navigator.dart'; 
import 'package:toeigo/models/route_models.dart'; // StepSeg
import 'package:toeigo/logic/schedule_resolver.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/models/group_models.dart';

void main() {
  group('TripCoordinator', () {
    Trip createDummyTrip({
      required TripStatus status,
      List<ScheduleEntry> schedule = const [],
    }) {
      return Trip(
        id: 't1',
        joinCode: '123456',
        leaderId: 'user1',
        title: 'Test Trip',
        travelPhase: TravelPhase.active,
        date: DateTime(2025, 12, 15),
        plannedDepartureAt: DateTime(2025, 12, 15, 10, 0),
        actualDepartureAt: null,
        legs: [],
        schedule: schedule,
        participants: [],
        memberIds: ['user1'],
      );
    }

    // Use RouteState (mutable) for testing input
    final dummyStep = StepSeg(kind: 'walk', title: 'Walk', fromName: 'A', toName: 'B');
    
    final dummyRouteStateMoving = RouteState(
      steps: [dummyStep],
      currentStepIndex: 0,
      nextStopIndex: 0,
    )..isMoving = true;

    final dummyRouteStateNotMoving = RouteState(
      steps: [dummyStep],
      currentStepIndex: 0,
      nextStopIndex: 0,
    )..isMoving = false;

    test('buildMemberNavigationState prioritizes Route if Moving', () {
      final trip = createDummyTrip(status: TripStatus.active);
      final entry = ScheduleEntry(
        plannedAt: DateTime.now().add(const Duration(minutes: 30)), 
        label: 'Event', 
        itemKind: ScheduleEntryKind.event,
        routeStepIndex: 0,
      );
      
      final scheduleState = ScheduleResolveResult(
        activeIndex: 0,
        activeLabel: 'Now',
        completedCount: 0,
        window: [entry],
        activeEntry: entry,
      );

      final navState = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        scheduleState: scheduleState, // Has active event
        routeState: dummyRouteStateMoving, // But moving
        now: DateTime.now(),
      );

      expect(navState.isMoving, true);
      expect(navState.statusLabel, '移動中'); // Default for moving route logic
    });

    test('buildMemberNavigationState prioritizes Schedule if Not Moving', () {
      final trip = createDummyTrip(status: TripStatus.active);
      final entry = ScheduleEntry(
        plannedAt: DateTime.now().add(const Duration(minutes: 10)), // < 20 mins for Meeting
        label: 'Event', 
        itemKind: ScheduleEntryKind.meeting,
        routeStepIndex: 0,
      );
      
      final scheduleState = ScheduleResolveResult(
        activeIndex: 0,
        activeLabel: 'Now',
        completedCount: 0,
        window: [entry],
        activeEntry: entry,
      );

      final navState = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        scheduleState: scheduleState,
        routeState: dummyRouteStateNotMoving, // Not moving
        now: DateTime.now(),
      );

      expect(navState.isMoving, false);
      expect(navState.statusLabel, '集合'); // Meeting label
    });
  });
}

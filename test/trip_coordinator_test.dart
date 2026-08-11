import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/group_models.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  group('TripCoordinator', () {
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

import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/group_models.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  test(
    'realtime arrival advances the current schedule row before its time',
    () {
      final trip = navigationV2Trip();
      final step = trip.stepsById['bus-C']!;
      final ride = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 4),
        label: '上23に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
      );
      final arrival = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 46),
        label: '押上に着く',
        itemKind: ScheduleEntryKind.arrival,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
      );
      final routeState = RouteState(
        stepsById: trip.stepsById,
        currentStepId: step.stepId,
        busProgress: BusProgress.forStep(
          step: step,
          fromStopId: step.stops.last.stopId!,
        ),
      );

      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: [ride, arrival],
        routeState: routeState,
        now: DateTime(2025, 1, 1, 10, 41),
      );

      expect(resolved.activeEntry?.id, ride.id);
      expect(resolved.resolvedEntry?.id, arrival.id);
      expect(resolved.activeLabel, 'いま');
      expect(resolved.completedCount, 1);
      expect(
        resolved.resolutionReason,
        contains('realtime_arrival_advance_step_id'),
      );
    },
  );

  test(
    'planned arrival advances even while realtime still shows the bus before destination',
    () {
      final trip = navigationV2Trip();
      final step = trip.stepsById['bus-C']!;
      final ride = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 4),
        label: '上23に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
      );
      final arrival = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 46),
        label: '押上に着く',
        itemKind: ScheduleEntryKind.arrival,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
      );
      final routeState = RouteState(
        stepsById: trip.stepsById,
        currentStepId: step.stepId,
        busProgress: BusProgress.forStep(step: step, fromStopId: 'stop-2'),
      );

      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: [ride, arrival],
        routeState: routeState,
        now: DateTime(2025, 1, 1, 10, 47),
      );

      expect(resolved.activeEntry?.id, arrival.id);
      expect(resolved.resolvedEntry?.id, arrival.id);
      expect(resolved.resolvedEntry?.routeStepId, 'bus-C');
      expect(
        resolved.resolutionReason,
        isNot(contains('premature_arrival_revert_step_id')),
      );
    },
  );

  test(
    'planned schedule stays authoritative after bus arrival time despite late realtime',
    () {
      final trip = navigationV2Trip();
      final step = trip.stepsById['bus-C']!;
      final ride = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 4),
        label: '上23に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
      );
      final arrival = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 46),
        label: '押上に着く',
        itemKind: ScheduleEntryKind.arrival,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
      );
      final walk = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 46),
        label: '目的地まで歩く',
        itemKind: ScheduleEntryKind.walk,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'walk-D',
      );
      final goal = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 51),
        label: '目的地 到着',
        itemKind: ScheduleEntryKind.goal,
        generatedBy: ScheduleEntrySource.route,
      );
      final routeState = RouteState(
        stepsById: trip.stepsById,
        currentStepId: step.stepId,
        busProgress: BusProgress.forStep(step: step, fromStopId: 'stop-2'),
      );

      final resolved = TripCoordinator.resolveScheduleState(
        scheduleEntries: [ride, arrival, walk, goal],
        routeState: routeState,
        now: DateTime(2025, 1, 1, 10, 55),
      );

      expect(resolved.activeEntry?.id, goal.id);
      expect(resolved.resolvedEntry?.id, goal.id);
      expect(resolved.completedCount, 3);
      expect(resolved.windowEntries, contains(goal));
      expect(resolved.windowEntries, isNot(contains(ride)));
      expect(
        resolved.resolutionReason,
        isNot(contains('realtime_incomplete_ride_revert_step_id')),
      );
    },
  );
}

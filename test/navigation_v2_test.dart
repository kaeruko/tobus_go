import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/providers/member_nav_progress_provider.dart';
import 'package:toeigo/services/bus_location_source.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  group('navigation v2 schedule fixture', () {
    test('keeps route identity when a zero-minute wait is hidden', () {
      final candidate = navigationV2Candidate();
      final schedule = createScheduleFromRoute(
        candidate,
        includeMeeting: true,
        startDateTime: DateTime(2025, 1, 1, 10),
      );

      expect(
        schedule
            .singleWhere((entry) => entry.itemKind == ScheduleEntryKind.meeting)
            .routeStepId,
        isNull,
      );
      expect(schedule.any((entry) => entry.routeStepId == 'wait-B'), isFalse);

      final rideEntries = schedule
          .where((entry) => entry.routeStepId == 'bus-C')
          .toList();
      expect(rideEntries.map((entry) => entry.itemKind), [
        ScheduleEntryKind.ride,
        ScheduleEntryKind.arrival,
      ]);
      expect(
        schedule
            .singleWhere((entry) => entry.itemKind == ScheduleEntryKind.goal)
            .routeStepId,
        isNull,
      );
    });

    test('coordinator resolves bus-C directly instead of wait-B', () {
      final trip = navigationV2Trip();
      final busEntry = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 4),
        label: '上23に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'bus-C',
      );
      final routeState = RouteState(
        stepsById: trip.stepsById,
        currentStepId: 'bus-C',
      );
      final resolved = ResolvedScheduleState(
        activeEntry: busEntry,
        resolvedEntry: busEntry,
        windowEntries: [busEntry],
        completedCount: 0,
        activeLabel: 'いま',
        resolutionReason: 'fixture',
      );

      final navigation = TripCoordinator.buildMemberNavigationState(
        trip: trip,
        routeState: routeState,
        now: DateTime(2025, 1, 1, 10, 4),
        resolvedState: resolved,
      );

      expect(navigation.step?.stepId, 'bus-C');
      expect(navigation.step?.kind, 'bus');
    });
  });

  group('FakeBusLocationSource', () {
    test('treats a stop before boarding as approaching', () {
      final step = navigationV2Candidate().steps.singleWhere(
        (candidateStep) => candidateStep.stepId == 'bus-C',
      );
      final progress = BusProgress.forStep(
        step: step,
        fromStopId: 'pre-boarding',
        tripStopIds: [
          'trip-origin',
          'pre-boarding',
          ...step.stops.map((stop) => stop.stopId!),
        ],
      );

      final navigation = NavigationState.navigating(
        step: step,
        busProgress: progress,
      );

      expect(progress.phase, BusProgressPhase.approaching);
      expect(progress.fromStopIndex, isNull);
      expect(progress.stopsUntilBoarding, 1);
      expect(navigation.mainText, 'バスはあと 1 停車前です');
      expect(navigation.statusLabel, '乗車待ち');
      expect(navigation.nextStopName, step.stops.first.name);
    });

    test('位置を取得するまで乗車停留所で待つ案内を出す', () {
      final step = navigationV2Candidate().steps.singleWhere(
        (candidateStep) => candidateStep.stepId == 'bus-C',
      );

      final navigation = NavigationState.navigating(
        step: step,
        busProgress: null,
      );

      expect(navigation.mainText, 'バスを待っています');
      expect(navigation.subText, contains(step.stops.first.name));
      expect(navigation.statusLabel, '乗車待ち');
      expect(navigation.isMoving, isFalse);
    });

    test('古い位置では停車数を隠して最終取得位置を表示する', () {
      final step = navigationV2Candidate().steps.singleWhere(
        (candidateStep) => candidateStep.stepId == 'bus-C',
      );
      final progress = BusProgress.forStep(
        step: step,
        fromStopId: 'pre-boarding',
        tripStopIds: [
          'trip-origin',
          'pre-boarding',
          ...step.stops.map((stop) => stop.stopId!),
        ],
        observedStopId: 'raw-stop',
        observedStopName: '平井六丁目',
        currentStatus: 'IN_TRANSIT_TO',
        vehicleAgeSeconds: 122,
      );

      final navigation = NavigationState.navigating(
        step: step,
        busProgress: progress,
      );

      expect(navigation.mainText, 'バスの位置情報を更新中です');
      expect(navigation.subText, '最終取得位置: 平井六丁目へ走行中（約2分前）');
      expect(navigation.statusLabel, '位置更新中');
      expect(navigation.remainingStops, isNull);
      expect(navigation.nextStopName, isNull);
    });

    test('advances remaining stops to next-stop and arrival states', () async {
      final step = navigationV2Candidate().steps.singleWhere(
        (candidateStep) => candidateStep.stepId == 'bus-C',
      );
      final source = FakeBusLocationSource([
        for (var i = 0; i < step.stops.length; i++)
          BusLocation(
            vehicleId: 'vehicle-1',
            fromStopId: step.stops[i].stopId!,
            routeId: step.routeId!,
            tripId: step.tripId!,
          ),
      ]);

      Future<NavigationState> currentNavigation() async {
        final location = await source.fetch(
          routeId: step.routeId!,
          tripId: step.tripId!,
          vehicleId: 'vehicle-1',
        );
        return NavigationState.navigating(
          step: step,
          busProgress: BusProgress.forStep(
            step: step,
            fromStopId: location.fromStopId,
          ),
        );
      }

      expect((await currentNavigation()).remainingStops, 3);
      source.advance();
      expect((await currentNavigation()).remainingStops, 2);
      source.advance();
      expect((await currentNavigation()).mainText, '次降ります');
      expect((await currentNavigation()).nextStopName, '押上');
      source.advance();
      expect((await currentNavigation()).mainText, '到着');
      expect((await currentNavigation()).remainingStops, 0);
    });
  });

  test('MemberNavProgress stores the step ID without flattening legs', () {
    final trip = navigationV2Trip();
    final step = trip.stepsById['bus-C']!;
    final progress = BusProgress.forStep(step: step, fromStopId: 'stop-1');
    final notifier = MemberNavProgressNotifier();
    addTearDown(notifier.dispose);

    notifier.updateFromSchedule(
      trip,
      ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 4),
        label: '上23に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'bus-C',
      ),
      busProgress: progress,
    );

    expect(notifier.state.currentStepId, 'bus-C');
    expect(notifier.state.busProgress?.fromStopIndex, 1);
  });
}

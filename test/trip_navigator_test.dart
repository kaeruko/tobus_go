import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/route_models.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  group('NavigationState riding display', () {
    test('bus riding shows bus emoji, route, current stop, and remaining stops', () {
      final step = navigationV2Candidate().steps.firstWhere(
        (step) => step.stepId == 'bus-C',
      );
      final entry = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10, 4),
        label: '🚌上23 平井七丁目に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
        routeRole: 'ride',
      );
      final progress = BusProgress(
        stepId: step.stepId,
        fromStopId: step.stops[1].stopId!,
        fromStopIndex: 1,
        nextStopId: step.stops[2].stopId,
        nextStopIndex: 2,
        phase: BusProgressPhase.riding,
      );

      final navigation = NavigationState.fromEntry(
        entry: entry,
        step: step,
        busProgress: progress,
      );

      expect(navigation.statusLabel, '🚌乗車中');
      expect(navigation.mainText, '上23 中間一');
      expect(navigation.subText, 'あと2回停車');
      expect(navigation.remainingStops, 2);
    });

    test('bus riding uses only the route name before the destination sign', () {
      final baseStep = navigationV2Candidate().steps.firstWhere(
        (step) => step.stepId == 'bus-C',
      );
      final step = StepSeg(
        stepId: baseStep.stepId,
        kind: baseStep.kind,
        title: '上23 上野松坂屋前行',
        fromName: baseStep.fromName,
        toName: baseStep.toName,
        stops: baseStep.stops,
      );
      final progress = BusProgress(
        stepId: step.stepId,
        fromStopId: step.stops[1].stopId!,
        fromStopIndex: 1,
        nextStopId: step.stops[2].stopId,
        nextStopIndex: 2,
        phase: BusProgressPhase.riding,
      );

      final navigation = NavigationState.navigating(
        step: step,
        busProgress: progress,
      );

      expect(navigation.mainText, '上23 中間一');
    });

    test('rail riding shows subway emoji', () {
      final step = StepSeg(
        stepId: 'rail-A',
        kind: 'rail',
        title: '浅草線',
        fromName: '浅草',
        toName: '東銀座',
      );
      final entry = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10),
        label: '浅草線に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: step.stepId,
        routeRole: 'ride',
      );

      final navigation = NavigationState.fromEntry(
        entry: entry,
        step: step,
        busProgress: null,
      );

      expect(navigation.statusLabel, '🚇乗車中');
    });

    test('bus riding fails fast when the route title is empty', () {
      final baseStep = navigationV2Candidate().steps.firstWhere(
        (step) => step.stepId == 'bus-C',
      );
      final step = StepSeg(
        stepId: baseStep.stepId,
        kind: baseStep.kind,
        title: '',
        fromName: baseStep.fromName,
        toName: baseStep.toName,
        stops: baseStep.stops,
      );
      final progress = BusProgress(
        stepId: step.stepId,
        fromStopId: step.stops[1].stopId!,
        fromStopIndex: 1,
        nextStopId: step.stops[2].stopId,
        nextStopIndex: 2,
        phase: BusProgressPhase.riding,
      );

      expect(
        () => NavigationState.navigating(
          step: step,
          busProgress: progress,
        ),
        throwsStateError,
      );
    });
  });
}

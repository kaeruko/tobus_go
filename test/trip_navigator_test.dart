import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/route_models.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  group('NavigationState riding display', () {
    test('bus riding shows route, current stop, and arrival summary', () {
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
      expect(navigation.subText, '10:46 上23 押上到着予定');
      expect(navigation.remainingStops, 2);
    });

    test('bus riding keeps the destination sign in the shared ride title', () {
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
        arrivalTime: baseStep.arrivalTime,
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

      expect(navigation.mainText, '上23 上野松坂屋前行 中間一');
      expect(
        navigation.subText,
        '10:46 上23 上野松坂屋前行 押上到着予定',
      );
    });

    test('last stop warning keeps the same route/place layout', () {
      final step = navigationV2Candidate().steps.firstWhere(
        (step) => step.stepId == 'bus-C',
      );
      final progress = BusProgress(
        stepId: step.stepId,
        fromStopId: step.stops[2].stopId!,
        fromStopIndex: 2,
        nextStopId: step.stops[3].stopId,
        nextStopIndex: 3,
        phase: BusProgressPhase.riding,
      );

      final navigation = NavigationState.navigating(
        step: step,
        busProgress: progress,
      );

      expect(navigation.mainText, '上23 中間二');
      expect(navigation.subText, '10:46 上23 押上到着予定');
      expect(navigation.remainingStops, 1);
    });

    test('rail riding without realtime keeps the shared arrival summary layout', () {
      final step = StepSeg(
        stepId: 'rail-A',
        kind: 'rail',
        title: '浅草線',
        fromName: '浅草',
        toName: '東銀座',
        arrivalTime: '10:05',
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
      expect(navigation.mainText, '浅草線 位置確認中');
      expect(navigation.subText, '10:05 浅草線 東銀座到着予定');
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
        arrivalTime: baseStep.arrivalTime,
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

    test('bus riding fails fast when arrival time is missing', () {
      final baseStep = navigationV2Candidate().steps.firstWhere(
        (step) => step.stepId == 'bus-C',
      );
      final step = StepSeg(
        stepId: baseStep.stepId,
        kind: baseStep.kind,
        title: baseStep.title,
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

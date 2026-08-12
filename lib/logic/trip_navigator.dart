import 'package:flutter/material.dart';

import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';

class RouteState {
  final Map<String, StepSeg> stepsById;
  final String? currentStepId;
  final BusProgress? busProgress;

  RouteState({required this.stepsById, this.currentStepId, this.busProgress});

  StepSeg? get currentStep =>
      currentStepId == null ? null : stepsById[currentStepId];

  StepSeg? stepForId(String? stepId) =>
      stepId == null ? null : stepsById[stepId];
}

class NavigationState {
  final String mainText;
  final String subText;
  final Color color;
  final bool isMoving;
  final String statusLabel;
  final String? nextStopName;
  final int? remainingStops;
  final String? currentStepId;
  final BusProgress? busProgress;
  final StepSeg? step;

  const NavigationState({
    required this.mainText,
    required this.subText,
    required this.color,
    required this.statusLabel,
    this.nextStopName,
    this.remainingStops,
    this.currentStepId,
    this.busProgress,
    this.isMoving = true,
    this.step,
  });

  static NavigationState idle() => const NavigationState(
    mainText: '',
    subText: '',
    color: Colors.grey,
    statusLabel: '待機中',
    isMoving: false,
  );

  static NavigationState waitingForDeparture({
    required DateTime plannedAt,
  }) => NavigationState(
    mainText: '出発前',
    subText:
        '${plannedAt.hour}:${plannedAt.minute.toString().padLeft(2, '0')} 出発予定',
    color: Colors.white,
    statusLabel: '開始前',
    isMoving: false,
  );

  static NavigationState waitingLong({
    required ScheduleEntry entry,
    required Duration diff,
  }) {
    final remainder = 'あと ${diff.inHours}時間${diff.inMinutes % 60}分';
    return NavigationState(
      mainText: entry.label,
      subText: '開始まで $remainder',
      color: Colors.white,
      statusLabel: '開始前',
      currentStepId: entry.routeStepId,
      isMoving: false,
    );
  }

  static NavigationState fromEntry({
    required ScheduleEntry entry,
    required StepSeg? step,
    required BusProgress? busProgress,
  }) {
    if (entry.itemKind == ScheduleEntryKind.walk && step != null) {
      return NavigationState.navigating(
        step: step,
        busProgress: null,
        statusLabel: '移動中',
      );
    }

    if (entry.itemKind == ScheduleEntryKind.ride && step != null) {
      return NavigationState.navigating(
        step: step,
        busProgress: busProgress,
        statusLabel: '乗車中',
      );
    }

    if (entry.itemKind == ScheduleEntryKind.meeting) {
      return NavigationState(
        mainText: entry.label,
        subText: entry.description.isNotEmpty
            ? entry.description
            : '集合場所へ向かいましょう',
        color: const Color(0xFFC8E6C9),
        statusLabel: '集合',
        isMoving: false,
      );
    }

    if (entry.itemKind == ScheduleEntryKind.arrival ||
        entry.itemKind == ScheduleEntryKind.goal) {
      return NavigationState(
        mainText: entry.label,
        subText: entry.description.isNotEmpty ? entry.description : '到着しました',
        color: const Color(0xFFFFCC80),
        statusLabel: '到着',
        currentStepId: entry.routeStepId,
        isMoving: false,
        step: step,
      );
    }

    return NavigationState(
      mainText: entry.label,
      subText: entry.description.isNotEmpty ? entry.description : '時間まで待機しましょう',
      color: const Color(0xFFE1F5FE),
      statusLabel: '待機',
      currentStepId: entry.routeStepId,
      isMoving: false,
      step: step,
    );
  }

  static NavigationState navigating({
    required StepSeg step,
    required BusProgress? busProgress,
    String? statusLabel,
  }) {
    if (step.kind == 'walk') {
      return NavigationState(
        mainText: '徒歩で移動中',
        subText: '目的地へ',
        color: const Color(0xFF81D4FA),
        statusLabel: statusLabel ?? '移動中',
        nextStopName: step.to,
        currentStepId: step.stepId,
        step: step,
      );
    }

    if (step.kind == 'bus' && (busProgress == null || step.stops.isEmpty)) {
      final boardingStopName = step.stops.isEmpty
          ? null
          : step.stops.first.name;
      return NavigationState(
        mainText: 'バスを待っています',
        subText: boardingStopName == null || boardingStopName.isEmpty
            ? 'バスの位置を確認中です'
            : '$boardingStopNameでお待ちください（バスの位置を確認中）',
        color: const Color(0xFFE1F5FE),
        statusLabel: '乗車待ち',
        currentStepId: step.stepId,
        isMoving: false,
        step: step,
      );
    }

    if (busProgress == null || step.stops.isEmpty) {
      return NavigationState(
        mainText: '乗車位置を確認中',
        subText: step.to ?? '',
        color: const Color(0xFF81D4FA),
        statusLabel: statusLabel ?? '乗車中',
        currentStepId: step.stepId,
        step: step,
      );
    }
    if (busProgress.stepId != step.stepId) {
      throw StateError(
        'BusProgressのstepIdが一致しません: '
        '${busProgress.stepId} != ${step.stepId}',
      );
    }
    if (busProgress.phase == BusProgressPhase.approaching) {
      final stopsUntilBoarding = busProgress.stopsUntilBoarding;
      return NavigationState(
        mainText: stopsUntilBoarding == null
            ? 'バスを待っています'
            : 'バスはあと $stopsUntilBoarding 停車前です',
        subText: '${step.stops.first.name}でお待ちください',
        color: const Color(0xFFE1F5FE),
        statusLabel: '乗車待ち',
        nextStopName: step.stops.first.name,
        currentStepId: step.stepId,
        busProgress: busProgress,
        isMoving: false,
        step: step,
      );
    }
    final fromIndex = busProgress.fromStopIndex;
    if (fromIndex == null || fromIndex < 0 || fromIndex >= step.stops.length) {
      throw StateError('BusProgressのfromStopIndexが範囲外です: $fromIndex');
    }

    final destinationIndex = step.stops.length - 1;
    final remaining = destinationIndex - fromIndex;
    final currentName = step.stops[fromIndex].name;
    final nextIndex = busProgress.nextStopIndex;
    final nextName = nextIndex != null && nextIndex < step.stops.length
        ? step.stops[nextIndex].name
        : null;

    if (remaining <= 0) {
      return NavigationState(
        mainText: '到着',
        subText: currentName,
        color: const Color(0xFFFFCC80),
        statusLabel: '到着',
        remainingStops: 0,
        currentStepId: step.stepId,
        busProgress: busProgress,
        isMoving: false,
        step: step,
      );
    }

    if (remaining == 1) {
      return NavigationState(
        mainText: '次降ります',
        subText: nextName == null ? '' : 'つぎは $nextName',
        color: const Color(0xFFFFAB91),
        statusLabel: statusLabel ?? '乗車中',
        nextStopName: nextName,
        remainingStops: remaining,
        currentStepId: step.stepId,
        busProgress: busProgress,
        step: step,
      );
    }

    return NavigationState(
      mainText: 'あと $remaining 回停車',
      subText: '現在: $currentName',
      color: const Color(0xFF81D4FA),
      statusLabel: statusLabel ?? '乗車中',
      nextStopName: nextName,
      remainingStops: remaining,
      currentStepId: step.stepId,
      busProgress: busProgress,
      step: step,
    );
  }
}

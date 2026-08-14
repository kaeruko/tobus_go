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
  static const double staleBusPositionAfterSeconds = 90;

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
  final String? noticeText;

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
    this.noticeText,
  });

  NavigationState withNotice({
    required String statusLabel,
    required String noticeText,
  }) => NavigationState(
    mainText: mainText,
    subText: subText,
    color: color,
    statusLabel: statusLabel,
    nextStopName: nextStopName,
    remainingStops: remainingStops,
    currentStepId: currentStepId,
    busProgress: busProgress,
    isMoving: isMoving,
    step: step,
    noticeText: noticeText,
  );

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
        mainText: '${step.from}にむかう',
        subText: '目的地へ',
        color: const Color(0xFF81D4FA),
        statusLabel: statusLabel ?? '移動中',
        nextStopName: step.to,
        currentStepId: step.stepId,
        step: step,
      );
    }

    if (step.kind == 'rail') {
      return NavigationState(
        mainText: '${step.title}に乗車中',
        subText: step.to == null || step.to!.isEmpty
            ? ''
            : '${step.to}で降ります',
        color: const Color(0xFF81D4FA),
        statusLabel: statusLabel ?? '乗車中',
        currentStepId: step.stepId,
        nextStopName: step.to,
        step: step,
      );
    }

    if (step.kind != 'bus') {
      throw StateError('未対応の乗車step kindです: ${step.kind}');
    }

    if (busProgress == null || step.stops.isEmpty) {
      final boardingStopName = step.stops.isEmpty
          ? null
          : step.stops.first.name;
      return NavigationState(
        mainText: '待機中',
        subText: boardingStopName == null || boardingStopName.isEmpty
            ? '現在の位置を確認中です'
            : '$boardingStopName（バスの位置を確認中）',
        color: const Color(0xFFE1F5FE),
        statusLabel: '乗車待ち',
        currentStepId: step.stepId,
        isMoving: false,
        step: step,
      );
    }

    final BusProgress progress = busProgress;

    if (progress.stepId != step.stepId) {
      throw StateError(
        'BusProgressのstepIdが一致しません: '
        '${progress.stepId} != ${step.stepId}',
      );
    }
    final isStale =
        (progress.vehicleAgeSeconds ?? 0) >= staleBusPositionAfterSeconds;

    NavigationState withFreshnessNotice(NavigationState navigation) => isStale
        ? navigation.withNotice(
            statusLabel: '検索中…',
            noticeText:
                'バスがどこかさがしています\n${_staleBusPositionText(progress)}',
          )
        : navigation;

    if (progress.phase == BusProgressPhase.approaching) {
      final stopsUntilBoarding = progress.stopsUntilBoarding;
      return withFreshnessNotice(
        NavigationState(
          mainText: stopsUntilBoarding == null
              ? '待機中'
              : 'あと $stopsUntilBoarding 停車前まできています',
          subText: 'いま:${step.stops.first.name}',
          color: const Color(0xFFE1F5FE),
          statusLabel: '乗車待ち',
          nextStopName: step.stops.first.name,
          currentStepId: step.stepId,
          busProgress: progress,
          isMoving: false,
          step: step,
        ),
      );
    }
    final fromIndex = progress.fromStopIndex;
    if (fromIndex == null || fromIndex < 0 || fromIndex >= step.stops.length) {
      throw StateError('BusProgressのfromStopIndexが範囲外です: $fromIndex');
    }

    final destinationIndex = step.stops.length - 1;
    final remaining = destinationIndex - fromIndex;
    final currentName = step.stops[fromIndex].name;
    final nextIndex = progress.nextStopIndex;
    final nextName = nextIndex != null && nextIndex < step.stops.length
        ? step.stops[nextIndex].name
        : null;

    if (remaining <= 0) {
      return withFreshnessNotice(
        NavigationState(
          mainText: '到着',
          subText: currentName,
          color: const Color(0xFFFFCC80),
          statusLabel: '到着',
          remainingStops: 0,
          currentStepId: step.stepId,
          busProgress: progress,
          isMoving: false,
          step: step,
        ),
      );
    }

    if (remaining == 1) {
      return withFreshnessNotice(
        NavigationState(
          mainText: '次降ります',
          subText: nextName == null ? '' : 'つぎは $nextName',
          color: const Color(0xFFFFAB91),
          statusLabel: statusLabel ?? '乗車中',
          nextStopName: nextName,
          remainingStops: remaining,
          currentStepId: step.stepId,
          busProgress: progress,
          step: step,
        ),
      );
    }

    return withFreshnessNotice(
      NavigationState(
        mainText: 'あと $remaining 回停車',
        subText: 'いま: $currentName',
        color: const Color(0xFF81D4FA),
        statusLabel: statusLabel ?? '乗車中',
        nextStopName: nextName,
        remainingStops: remaining,
        currentStepId: step.stepId,
        busProgress: progress,
        step: step,
      ),
    );
  }

  static String _staleBusPositionText(BusProgress progress) {
    final ageSeconds = progress.vehicleAgeSeconds ?? 0;
    final ageMinutes = (ageSeconds / 60).round().clamp(1, 999);
    final ageText = '約$ageMinutes分前';
    final stopName = progress.observedStopName;
    final stopText = stopName != null && stopName.isNotEmpty
        ? stopName
        : progress.observedStopId != null && progress.observedStopId!.isNotEmpty
        ? '停留所ID ${progress.observedStopId}'
        : '不明';
    final movementText = progress.currentStatus == 'IN_TRANSIT_TO'
        ? '$stopTextへ走行中'
        : stopText;
    return '$movementText（$ageText）';
  }
}

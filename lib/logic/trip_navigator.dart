import 'package:flutter/material.dart';

import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/rail_progress.dart';
import '../models/route_models.dart';
import 'ride_navigation_progress.dart';

class RouteState {
  final Map<String, StepSeg> stepsById;
  final String? currentStepId;
  final BusProgress? busProgress;
  final RailProgress? railProgress;

  RouteState({
    required this.stepsById,
    this.currentStepId,
    this.busProgress,
    this.railProgress,
  }) {
    if (busProgress != null && railProgress != null) {
      throw ArgumentError('RouteState cannot contain bus and rail progress together');
    }
  }

  StepSeg? get currentStep =>
      currentStepId == null ? null : stepsById[currentStepId];

  StepSeg? stepForId(String? stepId) =>
      stepId == null ? null : stepsById[stepId];
}

class NavigationState {
  static const double staleRidePositionAfterSeconds = 90;

  final String mainText;
  final String subText;
  final Color color;
  final bool isMoving;
  final String statusLabel;
  final String? nextStopName;
  final int? remainingStops;
  final String? currentStepId;
  final BusProgress? busProgress;
  final RailProgress? railProgress;
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
    this.railProgress,
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
    railProgress: railProgress,
    isMoving: isMoving,
    step: step,
    noticeText: noticeText,
  );

  static String _rideStatusLabel(StepSeg step) {
    switch (step.kind) {
      case 'bus':
        return '🚌乗車中';
      case 'rail':
        return '🚇乗車中';
      default:
        throw StateError(
          '乗車中ステータスの未対応step kindです: ${step.kind}',
        );
    }
  }

  static String _shortRideTitle(StepSeg step) {
    final title = step.title.trim();
    if (title.isEmpty) {
      throw StateError('乗車中表示に路線名がありません: stepId=${step.stepId}');
    }
    return title.split(RegExp(r'[\s　]+')).first;
  }

  static String _rideArrivalSummary(StepSeg step, String rideTitle) {
    final arrivalTime = step.arrivalTime?.trim();
    if (arrivalTime == null || arrivalTime.isEmpty) {
      throw StateError('乗車中表示に到着予定時刻がありません: stepId=${step.stepId}');
    }

    final destination = step.toName?.trim();
    if (destination == null || destination.isEmpty) {
      throw StateError('乗車中表示に降車地点がありません: stepId=${step.stepId}');
    }

    final normalizedRideTitle = rideTitle.trim();
    if (normalizedRideTitle.isEmpty) {
      throw StateError('乗車中表示に路線・行先表示がありません: stepId=${step.stepId}');
    }

    return '$arrivalTime $normalizedRideTitle $destination到着予定';
  }

  static String _approachUnit(StepSeg step) {
    switch (step.kind) {
      case 'bus':
        return '停留所';
      case 'rail':
        return '駅';
      default:
        throw StateError('接近表示の未対応step kindです: ${step.kind}');
    }
  }

  static String _boardingPlaceName(StepSeg step) {
    switch (step.kind) {
      case 'bus':
        if (step.stops.isEmpty || step.stops.first.name.trim().isEmpty) {
          throw StateError('バス乗車stepに乗車停留所がありません: ${step.stepId}');
        }
        return step.stops.first.name.trim();
      case 'rail':
        final name = step.fromName?.trim();
        if (name == null || name.isEmpty) {
          throw StateError('鉄道乗車stepに乗車駅がありません: ${step.stepId}');
        }
        return name;
      default:
        throw StateError('乗車地点表示の未対応step kindです: ${step.kind}');
    }
  }

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
    RailProgress? railProgress,
  }) {
    if (entry.itemKind == ScheduleEntryKind.walk && step != null) {
      return NavigationState.navigating(
        step: step,
        busProgress: null,
        railProgress: null,
        statusLabel: '移動中',
      );
    }

    if (entry.itemKind == ScheduleEntryKind.ride && step != null) {
      return NavigationState.navigating(
        step: step,
        busProgress: busProgress,
        railProgress: railProgress,
        statusLabel: _rideStatusLabel(step),
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
    RailProgress? railProgress,
    String? statusLabel,
  }) {
    if (step.kind == 'walk') {
      if (busProgress != null || railProgress != null) {
        throw StateError('徒歩stepに乗車進捗が渡されました: ${step.stepId}');
      }
      return NavigationState(
        mainText: '${step.to}にむかう',
        subText: '${step.meters}m 徒歩',
        color: const Color(0xFF81D4FA),
        statusLabel: statusLabel ?? '移動中',
        nextStopName: step.to,
        currentStepId: step.stepId,
        step: step,
      );
    }

    if (step.kind == 'rail') {
      if (busProgress != null) {
        throw StateError('rail stepにBusProgressが渡されました: ${step.stepId}');
      }
      if (railProgress == null) {
        final routeTitle = _shortRideTitle(step);
        return NavigationState(
          mainText: '$routeTitle 位置確認中',
          subText: _rideArrivalSummary(step, routeTitle),
          color: const Color(0xFF81D4FA),
          statusLabel: statusLabel ?? _rideStatusLabel(step),
          currentStepId: step.stepId,
          nextStopName: step.toName,
          step: step,
        );
      }
      final normalized = RideNavigationProgress.fromRail(
        step: step,
        progress: railProgress,
      );
      return _trackedRideNavigation(
        step: step,
        progress: normalized,
        railProgress: railProgress,
        statusLabel: statusLabel,
        staleNoticeText: _staleRailPositionText(railProgress),
      );
    }

    if (step.kind != 'bus') {
      throw StateError('未対応の乗車step kindです: ${step.kind}');
    }
    if (railProgress != null) {
      throw StateError('bus stepにRailProgressが渡されました: ${step.stepId}');
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

    final normalized = RideNavigationProgress.fromBus(
      step: step,
      progress: busProgress,
    );
    return _trackedRideNavigation(
      step: step,
      progress: normalized,
      busProgress: busProgress,
      statusLabel: statusLabel,
      staleNoticeText: _staleBusPositionText(busProgress),
    );
  }

  static NavigationState _trackedRideNavigation({
    required StepSeg step,
    required RideNavigationProgress progress,
    BusProgress? busProgress,
    RailProgress? railProgress,
    String? statusLabel,
    required String staleNoticeText,
  }) {
    if (busProgress != null && railProgress != null) {
      throw StateError('共通乗車表示へbus/rail両方の進捗が渡されました');
    }
    if (step.kind == 'bus' && busProgress == null) {
      throw StateError('bus stepの共通乗車表示にBusProgressがありません');
    }
    if (step.kind == 'rail' && railProgress == null) {
      throw StateError('rail stepの共通乗車表示にRailProgressがありません');
    }
    if (progress.stepId != step.stepId) {
      throw StateError(
        '共通乗車進捗のstepIdが一致しません: '
        '${progress.stepId} != ${step.stepId}',
      );
    }

    final isStale =
        (progress.vehicleAgeSeconds ?? 0) >= staleRidePositionAfterSeconds;
    NavigationState withFreshnessNotice(NavigationState navigation) => isStale
        ? navigation.withNotice(
            statusLabel: '検索中…',
            noticeText: staleNoticeText,
          )
        : navigation;

    switch (progress.phase) {
      case RideNavigationPhase.approaching:
        final stopsUntilBoarding = progress.stopsUntilBoarding;
        if (stopsUntilBoarding == null || stopsUntilBoarding <= 0) {
          throw StateError(
            '接近中の乗り物に乗車地点までの残り数がありません: '
            'stepId=${step.stepId}, stopsUntilBoarding=$stopsUntilBoarding',
          );
        }
        final boardingPlaceName = _boardingPlaceName(step);
        return withFreshnessNotice(
          NavigationState(
            mainText:
                '${_shortRideTitle(step)} $stopsUntilBoarding${_approachUnit(step)}前',
            subText: 'いま:$boardingPlaceName',
            color: const Color(0xFFE1F5FE),
            statusLabel: '乗車待ち',
            nextStopName: boardingPlaceName,
            currentStepId: step.stepId,
            busProgress: busProgress,
            railProgress: railProgress,
            isMoving: false,
            step: step,
          ),
        );

      case RideNavigationPhase.arrived:
        final arrivedPlace = step.toName?.trim().isNotEmpty == true
            ? step.toName!.trim()
            : progress.currentPlaceName?.trim();
        if (arrivedPlace == null || arrivedPlace.isEmpty) {
          throw StateError('到着表示に降車地点がありません: stepId=${step.stepId}');
        }
        return withFreshnessNotice(
          NavigationState(
            mainText: '到着',
            subText: arrivedPlace,
            color: const Color(0xFFFFCC80),
            statusLabel: '到着',
            remainingStops: 0,
            currentStepId: step.stepId,
            busProgress: busProgress,
            railProgress: railProgress,
            isMoving: false,
            step: step,
          ),
        );

      case RideNavigationPhase.riding:
        final currentPlace = progress.currentPlaceName?.trim();
        if (currentPlace == null || currentPlace.isEmpty) {
          throw StateError('乗車中表示に現在の停車地点がありません: stepId=${step.stepId}');
        }
        final remaining = progress.remainingStops;
        if (remaining == null || remaining <= 0) {
          throw StateError(
            '乗車中表示のremainingStopsが不正です: '
            'stepId=${step.stepId}, remainingStops=$remaining',
          );
        }

        return withFreshnessNotice(
          NavigationState(
            mainText: '${progress.rideTitle} $currentPlace',
            subText: _rideArrivalSummary(step, progress.rideTitle),
            color: remaining == 1
                ? const Color(0xFFFFAB91)
                : const Color(0xFF81D4FA),
            statusLabel: statusLabel ?? _rideStatusLabel(step),
            nextStopName: progress.nextPlaceName,
            remainingStops: remaining,
            currentStepId: step.stepId,
            busProgress: busProgress,
            railProgress: railProgress,
            step: step,
          ),
        );
    }
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
    return 'バスがどこかさがしています\n$movementText（$ageText）';
  }

  static String _staleRailPositionText(RailProgress progress) {
    final ageSeconds = progress.vehicleAgeSeconds ?? 0;
    final ageMinutes = (ageSeconds / 60).round().clamp(1, 999);
    final ageText = '約$ageMinutes分前';
    final place = progress.currentStatus == 'IN_TRANSIT_TO'
        ? progress.nextStopName
        : progress.currentStopName;
    return '列車の位置情報を確認しています\n${place ?? '駅不明'}（$ageText）';
  }
}

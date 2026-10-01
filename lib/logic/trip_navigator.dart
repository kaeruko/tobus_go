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

enum NavigationTextKey {
  idleStatus,
  busRideStatus,
  railRideStatus,
  rideArrivalSummary,
  preDepartureMain,
  plannedDepartureSub,
  preStartStatus,
  meetingCountdownMain,
  meetingScheduledSub,
  meetingActionMain,
  meetingNextSub,
  startsInSub,
  movingStatus,
  meetingDefaultSub,
  meetingStatus,
  arrivedDefaultSub,
  arrivedStatus,
  goalArrivedMain,
  waitingDefaultSub,
  waitingStatus,
  walkHeadingMain,
  walkDistanceSub,
  positionCheckingMain,
  busWaitingMain,
  positionCheckingSub,
  busPositionCheckingAtStopSub,
  waitingToBoardStatus,
  searchingStatus,
  approachingBusMain,
  approachingRailMain,
  nowAtSub,
  arrivedMain,
  getOffNextMain,
  rideCurrentPlaceMain,
  transitPlace,
  staleBusNotice,
  staleRailNotice,
  tripEndedMain,
  tripEndedSub,
  tripEndedStatus,
  tripCancelledMain,
  tripCancelledSub,
  tripCancelledStatus,
  departureCountdownMain,
  boardingSub,
  boardingPlannedSub,
  walkToRideCountdownMain,
  realtimeUnavailableNotice,
}

class NavigationTextToken {
  final NavigationTextKey key;
  final Map<String, Object> args;

  const NavigationTextToken(this.key, [this.args = const {}]);
}

class NavigationState {
  static const double staleRidePositionAfterSeconds = 90;

  final String mainText;
  final String subText;
  final Color color;
  final bool isMoving;
  final String statusLabel;
  final NavigationTextToken? mainTextToken;
  final NavigationTextToken? subTextToken;
  final NavigationTextToken? statusLabelToken;
  final NavigationTextToken? noticeTextToken;
  final String? nextStopName;
  final String? nextStopNameEn;
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
    this.mainTextToken,
    this.subTextToken,
    this.statusLabelToken,
    this.noticeTextToken,
    this.nextStopName,
    this.nextStopNameEn,
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
    NavigationTextToken? statusLabelToken,
    NavigationTextToken? noticeTextToken,
  }) => NavigationState(
    mainText: mainText,
    subText: subText,
    color: color,
    statusLabel: statusLabel,
    mainTextToken: mainTextToken,
    subTextToken: subTextToken,
    statusLabelToken: statusLabelToken,
    noticeTextToken: noticeTextToken,
    nextStopName: nextStopName,
    nextStopNameEn: nextStopNameEn,
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

  static NavigationTextToken _rideStatusToken(StepSeg step) {
    switch (step.kind) {
      case 'bus':
        return const NavigationTextToken(NavigationTextKey.busRideStatus);
      case 'rail':
        return const NavigationTextToken(NavigationTextKey.railRideStatus);
      default:
        throw StateError(
          '乗車中ステータスの未対応step kindです: ${step.kind}',
        );
    }
  }

  static NavigationTextToken _rideArrivalToken(
    StepSeg step,
    String rideTitle, {
    String? rideTitleEn,
  }) {
    final arrivalTime = step.arrivalTime?.trim();
    final destination = step.toName?.trim();
    final normalizedRideTitle = rideTitle.trim();
    if (arrivalTime == null ||
        arrivalTime.isEmpty ||
        destination == null ||
        destination.isEmpty ||
        normalizedRideTitle.isEmpty) {
      _rideArrivalSummary(step, rideTitle);
      throw StateError('unreachable after ride arrival validation');
    }
    final destinationEn = step.toNameEn?.trim();
    final normalizedRideTitleEn = rideTitleEn?.trim();
    return NavigationTextToken(
      NavigationTextKey.rideArrivalSummary,
      {
        'arrivalTime': arrivalTime,
        'rideTitle': normalizedRideTitle,
        if (normalizedRideTitleEn != null && normalizedRideTitleEn.isNotEmpty)
          'rideTitleEn': normalizedRideTitleEn,
        'destination': destination,
        if (destinationEn != null && destinationEn.isNotEmpty)
          'destinationEn': destinationEn,
      },
    );
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

  static String? _boardingPlaceNameEn(StepSeg step) {
    switch (step.kind) {
      case 'bus':
        return step.stops.isEmpty ? null : step.stops.first.nameEn?.trim();
      case 'rail':
        return step.fromNameEn?.trim();
      default:
        throw StateError('乗車地点英語表示の未対応step kindです: ${step.kind}');
    }
  }

  static NavigationState idle() => const NavigationState(
    mainText: '',
    subText: '',
    color: Colors.grey,
    statusLabel: '待機中',
    statusLabelToken: NavigationTextToken(NavigationTextKey.idleStatus),
    isMoving: false,
  );

  static NavigationState waitingForDeparture({
    required DateTime plannedAt,
  }) {
    final time =
        '${plannedAt.hour}:${plannedAt.minute.toString().padLeft(2, '0')}';
    return NavigationState(
      mainText: '出発前',
      subText: '$time 出発予定',
      color: Colors.white,
      statusLabel: '開始前',
      mainTextToken: const NavigationTextToken(
        NavigationTextKey.preDepartureMain,
      ),
      subTextToken: NavigationTextToken(
        NavigationTextKey.plannedDepartureSub,
        {'time': time},
      ),
      statusLabelToken: const NavigationTextToken(
        NavigationTextKey.preStartStatus,
      ),
      isMoving: false,
    );
  }

  static NavigationState waitingForMeeting({
    required ScheduleEntry entry,
    required DateTime now,
  }) {
    if (entry.itemKind != ScheduleEntryKind.meeting) {
      throw ArgumentError(
        'waitingForMeeting requires meeting entry: '
        'entryId=${entry.id}, kind=${entry.itemKind.name}',
      );
    }
    final label = entry.label.trim();
    if (label.isEmpty) {
      throw StateError('集合予定のlabelが空です: entryId=${entry.id}');
    }

    final seconds = entry.plannedAt.difference(now).inSeconds;
    if (seconds <= 0) {
      throw StateError(
        '開始済みの集合予定を集合前として表示しようとしました: '
        'entryId=${entry.id}, plannedAt=${entry.plannedAt}, now=$now',
      );
    }
    final minutes = (seconds + 59) ~/ 60;
    final time =
        '${entry.plannedAt.hour}:${entry.plannedAt.minute.toString().padLeft(2, '0')}';

    return NavigationState(
      mainText: 'あと$minutes分',
      subText: '$time $label',
      color: const Color(0xFFE1F5FE),
      statusLabel: '待機',
      mainTextToken: NavigationTextToken(
        NavigationTextKey.meetingCountdownMain,
        {'minutes': minutes},
      ),
      subTextToken: NavigationTextToken(
        NavigationTextKey.meetingScheduledSub,
        {'time': time, 'label': label},
      ),
      statusLabelToken: const NavigationTextToken(
        NavigationTextKey.waitingStatus,
      ),
      currentStepId: entry.routeStepId,
      isMoving: false,
    );
  }

  static NavigationState meetingWithNext({
    required ScheduleEntry entry,
    required ScheduleEntry nextEntry,
  }) {
    if (entry.itemKind != ScheduleEntryKind.meeting) {
      throw ArgumentError(
        'meetingWithNext requires meeting entry: '
        'entryId=${entry.id}, kind=${entry.itemKind.name}',
      );
    }
    if (nextEntry.id == entry.id) {
      throw StateError('集合予定の次の予定が同じentryです: entryId=${entry.id}');
    }
    if (nextEntry.legIndex != entry.legIndex) {
      throw StateError(
        '集合予定と次の予定のlegIndexが一致しません: '
        'meeting=${entry.legIndex}, next=${nextEntry.legIndex}',
      );
    }
    if (nextEntry.plannedAt.isBefore(entry.plannedAt)) {
      throw StateError(
        '集合予定より前の予定を次の予定として表示できません: '
        'meeting=${entry.plannedAt}, next=${nextEntry.plannedAt}',
      );
    }

    final nextLabel = nextEntry.label.trim();
    if (nextLabel.isEmpty) {
      throw StateError('集合後の次の予定のlabelが空です: entryId=${nextEntry.id}');
    }
    final nextTime =
        '${nextEntry.plannedAt.hour}:${nextEntry.plannedAt.minute.toString().padLeft(2, '0')}';

    return NavigationState(
      mainText: '人数を確認しましょう',
      subText: '次の予定\n$nextTime $nextLabel',
      color: const Color(0xFFC8E6C9),
      statusLabel: '集合',
      mainTextToken: const NavigationTextToken(
        NavigationTextKey.meetingActionMain,
      ),
      subTextToken: NavigationTextToken(
        NavigationTextKey.meetingNextSub,
        {'time': nextTime, 'label': nextLabel},
      ),
      statusLabelToken: const NavigationTextToken(
        NavigationTextKey.meetingStatus,
      ),
      currentStepId: entry.routeStepId,
      isMoving: false,
    );
  }

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
      subTextToken: NavigationTextToken(
        NavigationTextKey.startsInSub,
        {
          'hours': diff.inHours,
          'minutes': diff.inMinutes % 60,
        },
      ),
      statusLabelToken: const NavigationTextToken(
        NavigationTextKey.preStartStatus,
      ),
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
        statusLabelToken: const NavigationTextToken(
          NavigationTextKey.movingStatus,
        ),
      );
    }

    if (entry.itemKind == ScheduleEntryKind.ride && step != null) {
      return NavigationState.navigating(
        step: step,
        busProgress: busProgress,
        railProgress: railProgress,
        statusLabel: _rideStatusLabel(step),
        statusLabelToken: _rideStatusToken(step),
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
        subTextToken: entry.description.isEmpty
            ? const NavigationTextToken(
                NavigationTextKey.meetingDefaultSub,
              )
            : null,
        statusLabelToken: const NavigationTextToken(
          NavigationTextKey.meetingStatus,
        ),
        isMoving: false,
      );
    }

    if (entry.itemKind == ScheduleEntryKind.arrival ||
        entry.itemKind == ScheduleEntryKind.goal) {
      NavigationTextToken? mainTextToken;
      if (entry.itemKind == ScheduleEntryKind.arrival &&
          step != null &&
          step.isRide) {
        final routeTitle = _shortRideTitle(step);
        final destination = step.toName?.trim();
        if (destination == null || destination.isEmpty) {
          throw StateError(
            '到着予定に降車地点がありません: stepId=${step.stepId}',
          );
        }
        mainTextToken = NavigationTextToken(
          NavigationTextKey.rideCurrentPlaceMain,
          {
            'rideTitle': routeTitle,
            if (step.titleEn?.trim().isNotEmpty == true)
              'rideTitleEn': step.titleEn!.trim(),
            'placeName': destination,
            if (step.toNameEn?.trim().isNotEmpty == true)
              'placeNameEn': step.toNameEn!.trim(),
          },
        );
      }

      return NavigationState(
        mainText: entry.label,
        subText: entry.description.isNotEmpty ? entry.description : '到着しました',
        color: const Color(0xFFFFCC80),
        statusLabel: '到着',
        mainTextToken: mainTextToken,
        subTextToken: entry.description.isEmpty
            ? const NavigationTextToken(
                NavigationTextKey.arrivedDefaultSub,
              )
            : null,
        statusLabelToken: const NavigationTextToken(
          NavigationTextKey.arrivedStatus,
        ),
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
      subTextToken: entry.description.isEmpty
          ? const NavigationTextToken(
              NavigationTextKey.waitingDefaultSub,
            )
          : null,
      statusLabelToken: const NavigationTextToken(
        NavigationTextKey.waitingStatus,
      ),
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
    NavigationTextToken? statusLabelToken,
  }) {
    if (step.kind == 'walk') {
      if (busProgress != null || railProgress != null) {
        throw StateError('徒歩stepに乗車進捗が渡されました: ${step.stepId}');
      }
      final destination = step.to;
      if (destination == null || destination.isEmpty) {
        throw StateError('徒歩stepに目的地がありません: ${step.stepId}');
      }
      return NavigationState(
        mainText: '$destinationにむかう',
        subText: '${step.meters}m 徒歩',
        color: const Color(0xFF81D4FA),
        statusLabel: statusLabel ?? '移動中',
        mainTextToken: NavigationTextToken(
          NavigationTextKey.walkHeadingMain,
          {
            'destination': destination,
            if (step.toNameEn?.trim().isNotEmpty == true)
              'destinationEn': step.toNameEn!.trim(),
          },
        ),
        subTextToken: NavigationTextToken(
          NavigationTextKey.walkDistanceSub,
          {'meters': step.meters},
        ),
        statusLabelToken: statusLabelToken ??
            const NavigationTextToken(NavigationTextKey.movingStatus),
        nextStopName: destination,
        nextStopNameEn: step.toNameEn,
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
          mainText: '$routeTitle 📍',
          subText: _rideArrivalSummary(step, routeTitle),
          color: const Color(0xFF81D4FA),
          statusLabel: statusLabel ?? _rideStatusLabel(step),
          mainTextToken: NavigationTextToken(
            NavigationTextKey.positionCheckingMain,
            {
              'rideTitle': routeTitle,
              if (step.titleEn?.trim().isNotEmpty == true)
                'rideTitleEn': step.titleEn!.trim(),
            },
          ),
          subTextToken: _rideArrivalToken(
            step,
            routeTitle,
            rideTitleEn: step.titleEn,
          ),
          statusLabelToken: statusLabelToken ?? _rideStatusToken(step),
          currentStepId: step.stepId,
          nextStopName: step.toName,
          nextStopNameEn: step.toNameEn,
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
        statusLabelToken: statusLabelToken,
        staleNoticeText: _staleRailPositionText(railProgress),
        staleNoticeToken: _staleRailPositionToken(railProgress),
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
            ? '📍'
            : '$boardingStopName 📍',
        color: const Color(0xFFE1F5FE),
        statusLabel: '乗車待ち',
        mainTextToken: const NavigationTextToken(
          NavigationTextKey.busWaitingMain,
        ),
        subTextToken: boardingStopName == null || boardingStopName.isEmpty
            ? const NavigationTextToken(
                NavigationTextKey.positionCheckingSub,
              )
            : NavigationTextToken(
                NavigationTextKey.busPositionCheckingAtStopSub,
                {
                  'stopName': boardingStopName,
                  if (step.stops.first.nameEn?.trim().isNotEmpty == true)
                    'stopNameEn': step.stops.first.nameEn!.trim(),
                },
              ),
        statusLabelToken: const NavigationTextToken(
          NavigationTextKey.waitingToBoardStatus,
        ),
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
      statusLabelToken: statusLabelToken,
      staleNoticeText: _staleBusPositionText(busProgress),
      staleNoticeToken: _staleBusPositionToken(busProgress),
    );
  }

  static NavigationState _trackedRideNavigation({
    required StepSeg step,
    required RideNavigationProgress progress,
    BusProgress? busProgress,
    RailProgress? railProgress,
    String? statusLabel,
    NavigationTextToken? statusLabelToken,
    required String staleNoticeText,
    required NavigationTextToken staleNoticeToken,
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
            statusLabel: navigation.statusLabel,
            noticeText: '📍',
            statusLabelToken: navigation.statusLabelToken,
            noticeTextToken: staleNoticeToken,
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
        final boardingPlaceNameEn = _boardingPlaceNameEn(step);
        final rideTitleEn = progress.rideTitleEn?.trim();
        return withFreshnessNotice(
          NavigationState(
            mainText:
                '${_shortRideTitle(step)} $stopsUntilBoarding${_approachUnit(step)}前',
            subText: '乗る場所:$boardingPlaceName',
            color: const Color(0xFFE1F5FE),
            statusLabel: '乗車待ち',
            mainTextToken: NavigationTextToken(
              step.kind == 'bus'
                  ? NavigationTextKey.approachingBusMain
                  : NavigationTextKey.approachingRailMain,
              {
                'rideTitle': _shortRideTitle(step),
                if (rideTitleEn != null && rideTitleEn.isNotEmpty)
                  'rideTitleEn': rideTitleEn,
                'count': stopsUntilBoarding,
              },
            ),
            subTextToken: NavigationTextToken(
              NavigationTextKey.nowAtSub,
              {
                'placeName': boardingPlaceName,
                if (boardingPlaceNameEn != null &&
                    boardingPlaceNameEn.isNotEmpty)
                  'placeNameEn': boardingPlaceNameEn,
              },
            ),
            statusLabelToken: const NavigationTextToken(
              NavigationTextKey.waitingToBoardStatus,
            ),
            nextStopName: boardingPlaceName,
            nextStopNameEn: boardingPlaceNameEn,
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
        final arrivedPlaceEn = step.toNameEn?.trim().isNotEmpty == true
            ? step.toNameEn!.trim()
            : progress.currentPlaceNameEn?.trim();
        if (arrivedPlace == null || arrivedPlace.isEmpty) {
          throw StateError('到着表示に降車地点がありません: stepId=${step.stepId}');
        }
        return withFreshnessNotice(
          NavigationState(
            mainText: '到着',
            subText: arrivedPlace,
            color: const Color(0xFFFFCC80),
            statusLabel: '到着',
            mainTextToken: const NavigationTextToken(
              NavigationTextKey.arrivedMain,
            ),
            subTextToken: NavigationTextToken(
              NavigationTextKey.transitPlace,
              {
                'placeName': arrivedPlace,
                if (arrivedPlaceEn != null && arrivedPlaceEn.isNotEmpty)
                  'placeNameEn': arrivedPlaceEn,
              },
            ),
            statusLabelToken: const NavigationTextToken(
              NavigationTextKey.arrivedStatus,
            ),
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

        final currentPlaceEn = progress.currentPlaceNameEn?.trim();
        final rideTitleEn = progress.rideTitleEn?.trim();
        return withFreshnessNotice(
          NavigationState(
            mainText: remaining == 1
                ? '次で降ります'
                : '${progress.rideTitle} $currentPlace',
            subText: _rideArrivalSummary(step, progress.rideTitle),
            color: remaining == 1
                ? const Color(0xFFFFAB91)
                : const Color(0xFF81D4FA),
            statusLabel: statusLabel ?? _rideStatusLabel(step),
            mainTextToken: remaining == 1
                ? const NavigationTextToken(
                    NavigationTextKey.getOffNextMain,
                  )
                : NavigationTextToken(
                    NavigationTextKey.rideCurrentPlaceMain,
                    {
                      'rideTitle': progress.rideTitle,
                      if (rideTitleEn != null && rideTitleEn.isNotEmpty)
                        'rideTitleEn': rideTitleEn,
                      'placeName': currentPlace,
                      if (currentPlaceEn != null && currentPlaceEn.isNotEmpty)
                        'placeNameEn': currentPlaceEn,
                    },
                  ),
            subTextToken: _rideArrivalToken(
              step,
              progress.rideTitle,
              rideTitleEn: progress.rideTitleEn,
            ),
            statusLabelToken: statusLabelToken ?? _rideStatusToken(step),
            nextStopName: progress.nextPlaceName,
            nextStopNameEn: progress.nextPlaceNameEn,
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

  static NavigationTextToken _staleBusPositionToken(BusProgress progress) {
    final ageSeconds = progress.vehicleAgeSeconds ?? 0;
    final ageMinutes = (ageSeconds / 60).round().clamp(1, 999);
    final stopName = progress.observedStopName;
    final stopNameEn = progress.observedStopNameEn;
    final stopId = progress.observedStopId;
    return NavigationTextToken(
      NavigationTextKey.staleBusNotice,
      {
        'ageMinutes': ageMinutes,
        'placeKind': stopName != null && stopName.isNotEmpty
            ? 'name'
            : (stopId != null && stopId.isNotEmpty ? 'id' : 'unknown'),
        'place': stopName != null && stopName.isNotEmpty
            ? stopName
            : (stopId ?? ''),
        if (stopNameEn != null && stopNameEn.isNotEmpty)
          'placeEn': stopNameEn,
        'moving': progress.currentStatus == 'IN_TRANSIT_TO',
      },
    );
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

  static NavigationTextToken _staleRailPositionToken(RailProgress progress) {
    final ageSeconds = progress.vehicleAgeSeconds ?? 0;
    final ageMinutes = (ageSeconds / 60).round().clamp(1, 999);
    final place = progress.currentStatus == 'IN_TRANSIT_TO'
        ? progress.nextStopName
        : progress.currentStopName;
    final placeEn = progress.currentStatus == 'IN_TRANSIT_TO'
        ? progress.nextStopNameEn
        : progress.currentStopNameEn;
    return NavigationTextToken(
      NavigationTextKey.staleRailNotice,
      {
        'ageMinutes': ageMinutes,
        'placeName': place ?? '',
        if (placeEn != null && placeEn.isNotEmpty) 'placeNameEn': placeEn,
      },
    );
  }
}

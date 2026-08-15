import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../models/group_models.dart';
import '../models/bus_progress.dart';
import '../models/rail_progress.dart';
import '../models/route_models.dart';
import '../logic/trip_coordinator.dart';
import '../logic/trip_navigator.dart';
import '../services/bus_location_source.dart';
import '../services/train_location_source.dart';
import 'trip_provider.dart';
import 'member_nav_progress_provider.dart';
import 'minute_ticker_provider.dart';

/// スケジュール解決結果を共有するProvider
/// 時間経過(ticker)またはTripの更新で再計算される
final memberScheduleStateProvider =
    Provider.autoDispose<AsyncValue<ResolvedScheduleState>>((ref) {
      final tripAsync = ref.watch(tripStreamProvider);
      final nowTick = ref.watch(minuteTickerProvider);

      return tripAsync.whenData((trip) {
        if (trip == null) throw Exception("No Trip");

        // UI表示用には最新の時間を刻む (nowTickがまだなければ実時間)
        final now = nowTick.value ?? appClock.now();

        return TripCoordinator.resolveScheduleState(
          scheduleEntries: trip.schedule,
          now: now,
        );
      });
    }, dependencies: [tripStreamProvider]);

class RealtimeTransitState {
  final String? trackedStepId;
  final String? trackedVehicleId;
  final BusProgress? busProgress;
  final RailProgress? railProgress;

  const RealtimeTransitState({
    this.trackedStepId,
    this.trackedVehicleId,
    this.busProgress,
    this.railProgress,
  });
}

final busLocationSourceProvider = Provider<BusLocationSource>((ref) {
  return const RealtimeBusLocationSource();
});

final trainLocationSourceProvider = Provider<TrainLocationSource>((ref) {
  return const RealtimeTrainLocationSource();
});

/// ビジネスロジック: APIポーリングと時間経過による進行管理
class MemberModeController extends StateNotifier<RealtimeTransitState> {
  final Ref _ref;
  final BusLocationSource _busLocationSource;
  final TrainLocationSource _trainLocationSource;
  Timer? _pollingTimer;
  DateTime? _debugPreviousPollAt;
  String? _debugPreviousStepId;
  String? _debugPreviousVehicleId;
  int? _debugPreviousObservedSequence;
  int? _debugPreviousFromIndex;
  int? _debugPreviousVehicleTimestamp;
  String? _debugPrintedTimelineKey;

  MemberModeController(
    this._ref,
    this._busLocationSource,
    this._trainLocationSource,
  ) : super(const RealtimeTransitState());

  void initialize() {
    _startPolling();
  }

  @override
  void dispose() {
    _pollingTimer?.cancel();
    super.dispose();
  }

  void _startPolling() {
    _pollingTimer?.cancel();

    // 画面を開いた直後は必ず最新データを取得
    _checkProgress(forceRefresh: true);

    _pollingTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _checkProgress(),
    );
  }

  Future<void> pollNow() async => _checkProgress(forceRefresh: true);

  Future<void> _checkProgress({bool forceRefresh = false}) async {
    debugPrint(
      '[MemberModeController] _checkProgress START '
      'forceRefresh=$forceRefresh',
    );

    final trip = _ref.read(tripStreamProvider).value;
    if (trip == null) {
      debugPrint('[MemberModeController] trip=null');
      return;
    }

    // Keep an incomplete realtime ride authoritative after its planned arrival
    // time. Resolving by the clock alone would otherwise jump to a later walk
    // or goal while the vehicle/train is still before the alighting stop.
    final navProgress = _ref.read(memberNavProgressProvider);
    final knownBusProgress = state.busProgress ?? navProgress.busProgress;
    final knownRailProgress = state.railProgress ?? navProgress.railProgress;
    final scheduleResolved = TripCoordinator.resolveScheduleState(
      scheduleEntries: trip.schedule,
      now: appClock.now(),
      routeState: RouteState(
        stepsById: trip.stepsById,
        currentStepId: state.trackedStepId ?? navProgress.currentStepId,
        busProgress: knownBusProgress,
        railProgress: knownRailProgress,
      ),
    );
    final resolvedEntry = scheduleResolved.resolvedEntry;

    debugPrint(
      '[MemberModeController] resolvedEntry='
      '${resolvedEntry?.label} '
      'routeStepId=${resolvedEntry?.routeStepId}',
    );

    StepSeg? activeStep;
    final activeStepId = resolvedEntry?.routeStepId;
    if (activeStepId != null) {
      activeStep = trip.stepsById[activeStepId];
      if (activeStep == null) {
        throw StateError('予定が存在しないrouteStepIdを参照しています: $activeStepId');
      }
    }

    debugPrint(
      '[MemberModeController] activeStep='
      'kind=${activeStep?.kind}, '
      'routeId=${activeStep?.routeId}, '
      'tripId=${activeStep?.tripId}, '
      'stops=${activeStep?.stops.length}',
    );

    if (activeStep != null &&
        activeStep.kind == 'bus' &&
        activeStep.routeId != null &&
        activeStep.tripId != null) {
      await _updateBusProgress(activeStep, forceRefresh: forceRefresh);
    } else if (activeStep != null && activeStep.kind == 'rail') {
      await _updateRailProgress(activeStep, forceRefresh: forceRefresh);
    } else {
      // 乗車ステップではない（徒歩など）→ 状態をリセット
      if (activeStep != null && !activeStep.isRide) {
        debugPrint('[MemberModeController] 非乗車ステップ: ${activeStep.kind}');
      }
      if (state.trackedStepId != null ||
          state.trackedVehicleId != null ||
          state.busProgress != null ||
          state.railProgress != null) {
        state = const RealtimeTransitState();
      }
    }

    // 進捗を更新 (時間基準 + API補正)
    if (resolvedEntry != null) {
      final sameTrackedStep = state.trackedStepId == resolvedEntry.routeStepId;
      _ref
          .read(memberNavProgressProvider.notifier)
          .updateFromSchedule(
            trip,
            resolvedEntry,
            busProgress: sameTrackedStep ? state.busProgress : null,
            railProgress: sameTrackedStep ? state.railProgress : null,
          );
    }
  }

  Future<void> _updateBusProgress(
    StepSeg activeStep, {
    required bool forceRefresh,
  }) async {
    debugPrint(
      '[MemberModeController] バス乗車中: '
      'route=${activeStep.routeId}, trip=${activeStep.tripId}',
    );

    try {
      final trackedVehicleId = state.trackedStepId == activeStep.stepId
          ? state.trackedVehicleId
          : null;
      final location = await _busLocationSource.fetch(
        routeId: activeStep.routeId!,
        tripId: activeStep.tripId!,
        vehicleId: trackedVehicleId,
        forceRefresh: forceRefresh,
      );
      final progress = BusProgress.forStep(
        step: activeStep,
        fromStopId: location.fromStopId,
        tripStopIds: location.tripStopIds,
        observedStopId: location.rawStopId,
        observedStopName: location.rawStopName,
        currentStatus: location.currentStatus,
        vehicleAgeSeconds: location.vehicleAgeSeconds,
      );
      _logBusProgressTrace(
        step: activeStep,
        location: location,
        progress: progress,
        forceRefresh: forceRefresh,
      );
      state = RealtimeTransitState(
        trackedStepId: activeStep.stepId,
        trackedVehicleId: location.vehicleId,
        busProgress: progress,
      );
      debugPrint(
        '[MemberModeController] バス追跡成功: '
        'step=${activeStep.stepId}, phase=${progress.phase.name}, '
        'fromIndex=${progress.fromStopIndex}, '
        'fromStopId=${location.fromStopId}, '
        'rawStopId=${location.rawStopId}, '
        'rawStopName=${location.rawStopName}, '
        'observedSeq=${location.observedStopSequence}, '
        'status=${location.currentStatus}, '
        'vehicle=${location.vehicleId}, '
        'snapshotAge=${location.snapshotAgeSeconds}s, '
        'feedAge=${location.feedAgeSeconds}s, '
        'vehicleAge=${location.vehicleAgeSeconds}s, '
        'serverNow=${location.serverNow}, '
        'clientNow=${DateTime.now().toUtc().toIso8601String()}',
      );
    } on BusLocationNotAvailableException catch (e) {
      // An exact route/trip match may not appear in the realtime feed until
      // the assigned vehicle starts reporting. Keep a previously locked
      // vehicle ID, but clear stale stop progress and show the waiting UI.
      state = RealtimeTransitState(
        trackedStepId: activeStep.stepId,
        trackedVehicleId: state.trackedStepId == activeStep.stepId
            ? state.trackedVehicleId
            : null,
      );
      debugPrint('[MemberModeController] バス乗車待ち: $e');
    } catch (e) {
      debugPrint('[MemberModeController] バスAPIエラー: $e');
    }
  }

  Future<void> _updateRailProgress(
    StepSeg activeStep, {
    required bool forceRefresh,
  }) async {
    debugPrint(
      '[MemberModeController] 鉄道乗車中: '
      '${activeStep.fromName} -> ${activeStep.toName} '
      'arrival=${activeStep.arrivalTime} trip=${activeStep.tripId}',
    );

    try {
      final location = await _trainLocationSource.fetch(
        step: activeStep,
        forceRefresh: forceRefresh,
      );
      final progress = RailProgress.forLocation(
        stepId: activeStep.stepId,
        location: location,
      );
      state = RealtimeTransitState(
        trackedStepId: activeStep.stepId,
        trackedVehicleId: location.vehicleId,
        railProgress: progress,
      );
      debugPrint(
        '[MemberModeController] 鉄道追跡成功: '
        'step=${activeStep.stepId}, trip=${location.tripId}, '
        'phase=${progress.phase.name}, '
        'sequence=${location.currentStopSequence}, '
        'status=${location.currentStatus}, '
        'current=${location.currentStopName}, '
        'next=${progress.nextStopName}, '
        'remaining=${progress.remainingStops}, '
        'vehicleAge=${location.vehicleAgeSeconds}s',
      );
    } on TrainLocationNotAvailableException catch (e) {
      // A reporting train can disappear temporarily around service boundaries.
      // Keep the route step but do not synthesize a station position.
      state = RealtimeTransitState(trackedStepId: activeStep.stepId);
      debugPrint('[MemberModeController] 鉄道位置なし: $e');
    } catch (e) {
      debugPrint('[MemberModeController] 鉄道APIエラー: $e');
    }
  }

  void _logBusProgressTrace({
    required StepSeg step,
    required BusLocation location,
    required BusProgress progress,
    required bool forceRefresh,
  }) {
    if (!kDebugMode) return;

    final clientNow = DateTime.now().toUtc();
    final sameVehicle =
        _debugPreviousStepId == step.stepId &&
        _debugPreviousVehicleId == location.vehicleId;
    final elapsedSeconds = sameVehicle && _debugPreviousPollAt != null
        ? clientNow.difference(_debugPreviousPollAt!).inMilliseconds / 1000
        : null;
    final observedDelta =
        sameVehicle &&
            _debugPreviousObservedSequence != null &&
            location.observedStopSequence != null
        ? location.observedStopSequence! - _debugPreviousObservedSequence!
        : null;
    final mappedDelta =
        sameVehicle &&
            _debugPreviousFromIndex != null &&
            progress.fromStopIndex != null
        ? progress.fromStopIndex! - _debugPreviousFromIndex!
        : null;
    final vehicleTimeDelta =
        sameVehicle &&
            _debugPreviousVehicleTimestamp != null &&
            location.vehicleTimestamp != null
        ? location.vehicleTimestamp! - _debugPreviousVehicleTimestamp!
        : null;
    final remaining = progress.fromStopIndex == null
        ? null
        : step.stops.length - 1 - progress.fromStopIndex!;

    debugPrint(
      '[BusProgressTrace] sample '
      'client=${clientNow.toIso8601String()} '
      'step=${step.stepId} route=${step.routeId} trip=${step.tripId} '
      'vehicle=${location.vehicleId} forceRefresh=$forceRefresh',
    );
    debugPrint(
      '[BusProgressTrace] realtime '
      'vehicleTs=${location.vehicleTimestamp} '
      'vehicleAge=${location.vehicleAgeSeconds}s '
      'feedAge=${location.feedAgeSeconds}s '
      'status=${location.currentStatus} '
      'observedSeq=${location.observedStopSequence} '
      'rawStop=${location.rawStopId}/${location.rawStopName} '
      'fromSeq=${location.fromStopSequence} fromStop=${location.fromStopId}',
    );
    debugPrint(
      '[BusProgressTrace] mapping '
      'phase=${progress.phase.name} fromIndex=${progress.fromStopIndex} '
      'nextIndex=${progress.nextStopIndex} remaining=$remaining '
      'stopsUntilBoarding=${progress.stopsUntilBoarding}',
    );
    debugPrint(
      '[BusProgressTrace] delta '
      'clientElapsed=${elapsedSeconds?.toStringAsFixed(1)}s '
      'vehicleTimeDelta=${vehicleTimeDelta}s '
      'observedSeqDelta=$observedDelta mappedIndexDelta=$mappedDelta',
    );

    final timelineKey = '${step.stepId}/${location.vehicleId}';
    if (_debugPrintedTimelineKey != timelineKey || forceRefresh) {
      debugPrint(
        '[BusProgressTrace] planned '
        '${step.fromName} -> ${step.toName} '
        '${step.departureTime} -> ${step.arrivalTime} '
        'minutes=${step.minutes} stepStops=${step.stops.length}',
      );
      var tripSearchStart = 0;
      BusStopSchedule? previousSchedule;
      for (var stepIndex = 0; stepIndex < step.stops.length; stepIndex++) {
        final stop = step.stops[stepIndex];
        final tripIndex = location.tripStopIds.indexWhere(
          (stopId) => stopId == stop.stopId,
          tripSearchStart,
        );
        if (tripIndex >= 0) tripSearchStart = tripIndex + 1;
        final sequence = tripIndex < 0 ? null : tripIndex + 1;
        BusStopSchedule? schedule;
        if (sequence != null) {
          for (final candidate in location.tripStopSchedule) {
            if (candidate.sequence == sequence) {
              schedule = candidate;
              break;
            }
          }
        }
        final intervalMinutes = schedule == null || previousSchedule == null
            ? null
            : schedule.arrivalMinute - previousSchedule.departureMinute;
        debugPrint(
          '[BusProgressTrace] stop '
          'stepIndex=$stepIndex tripSeq=$sequence '
          'id=${stop.stopId} name=${stop.name} '
          'planned=${schedule?.arrivalTime ?? "?"} '
          'intervalFromPrevious=${intervalMinutes == null ? "-" : "$intervalMinutes min"}',
        );
        previousSchedule = schedule ?? previousSchedule;
      }
      _debugPrintedTimelineKey = timelineKey;
    }

    _debugPreviousPollAt = clientNow;
    _debugPreviousStepId = step.stepId;
    _debugPreviousVehicleId = location.vehicleId;
    _debugPreviousObservedSequence = location.observedStopSequence;
    _debugPreviousFromIndex = progress.fromStopIndex;
    _debugPreviousVehicleTimestamp = location.vehicleTimestamp;
  }
}

final memberModeControllerProvider =
    StateNotifierProvider.autoDispose<MemberModeController, RealtimeTransitState>((
      ref,
    ) {
      return MemberModeController(
        ref,
        ref.watch(busLocationSourceProvider),
        ref.watch(trainLocationSourceProvider),
      );
    }, dependencies: [tripStreamProvider, memberScheduleStateProvider]);

/// UI描画に必要な全データ
class MemberUiState {
  final NavigationState navState;
  final List<ScheduleEntry> windowEntries;
  final ScheduleEntry? resolvedEntry;
  final int completedCount;
  final String activeLabel;
  final String displayTitle;

  MemberUiState({
    required this.navState,
    required this.windowEntries,
    required this.resolvedEntry,
    required this.completedCount,
    required this.activeLabel,
    required this.displayTitle,
  });
}

/// UI State Provider
final memberUiStateProvider = Provider.autoDispose<AsyncValue<MemberUiState>>((
  ref,
) {
  final tripAsync = ref.watch(tripStreamProvider);
  final navProgress = ref.watch(memberNavProgressProvider);
  ref.watch(memberModeControllerProvider);
  final nowTick = ref.watch(minuteTicker_provider);

  return tripAsync.whenData((trip) {
    if (trip == null) throw Exception("No Trip");

    final now = nowTick.value ?? appClock.now();

    // ルート情報の構築（表示用）
    final routeState = RouteState(
      stepsById: trip.stepsById,
      currentStepId: navProgress.currentStepId,
      busProgress: navProgress.busProgress,
      railProgress: navProgress.railProgress,
    );

    final resolvedState = TripCoordinator.resolveScheduleState(
      scheduleEntries: trip.schedule,
      routeState: routeState,
      now: now,
    );

    // ナビゲーション表示状態の構築
    final navDisplayState = TripCoordinator.buildMemberNavigationState(
      trip: trip,
      routeState: routeState,
      now: now,
      resolvedState: resolvedState,
    );

    return MemberUiState(
      navState: navDisplayState,
      windowEntries: resolvedState.windowEntries,
      resolvedEntry: resolvedState.resolvedEntry,
      completedCount: resolvedState.completedCount,
      activeLabel: resolvedState.activeLabel,
      displayTitle: trip.displayTitle,
    );
  });
}, dependencies: [tripStreamProvider, memberModeControllerProvider]);

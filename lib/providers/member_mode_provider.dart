import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../models/group_models.dart';
import '../models/bus_progress.dart';
import '../models/route_models.dart';
import '../logic/trip_coordinator.dart';
import '../logic/trip_navigator.dart';
import '../services/bus_location_source.dart';
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
    });

class RealtimeBusState {
  final String? trackedStepId;
  final String? trackedVehicleId;
  final BusProgress? busProgress;

  const RealtimeBusState({
    this.trackedStepId,
    this.trackedVehicleId,
    this.busProgress,
  });
}

final busLocationSourceProvider = Provider<BusLocationSource>((ref) {
  return const RealtimeBusLocationSource();
});

/// ビジネスロジック: APIポーリングと時間経過による進行管理
class MemberModeController extends StateNotifier<RealtimeBusState> {
  final Ref _ref;
  final BusLocationSource _busLocationSource;
  Timer? _pollingTimer;

  MemberModeController(this._ref, this._busLocationSource)
    : super(const RealtimeBusState());

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
    // 初回実行
    _checkProgress();
    // 30秒ごとに時間とAPIをチェックして進行させる
    _pollingTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _checkProgress(),
    );
  }

  Future<void> pollNow() async => _checkProgress();

  Future<void> _checkProgress() async {
    debugPrint('[MemberModeController] _checkProgress START');

    final trip = _ref.read(tripStreamProvider).value;
    if (trip == null) {
      debugPrint('[MemberModeController] trip=null');
      return;
    }

    final scheduleAsync = _ref.read(memberScheduleStateProvider);

    if (scheduleAsync.asData == null) {
      debugPrint('[MemberModeController] schedule未準備: $scheduleAsync');
      return;
    }

    final scheduleResolved = scheduleAsync.asData!.value;
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

    // 2. 乗車中かつルートID/tripIDがある場合のみAPI確認
    if (activeStep != null &&
        activeStep.isRide &&
        activeStep.routeId != null &&
        activeStep.tripId != null) {
      debugPrint(
        '[MemberModeController] 乗車中: route=${activeStep.routeId}, trip=${activeStep.tripId}',
      );

      try {
        final trackedVehicleId = state.trackedStepId == activeStep.stepId
            ? state.trackedVehicleId
            : null;
        final location = await _busLocationSource.fetch(
          routeId: activeStep.routeId!,
          tripId: activeStep.tripId!,
          vehicleId: trackedVehicleId,
        );
        final progress = BusProgress.forStep(
          step: activeStep,
          fromStopId: location.fromStopId,
        );
        state = RealtimeBusState(
          trackedStepId: activeStep.stepId,
          trackedVehicleId: location.vehicleId,
          busProgress: progress,
        );
        debugPrint(
          '[MemberModeController] 追跡成功: '
          'step=${activeStep.stepId}, from=${progress.fromStopIndex}, '
          'vehicle=${location.vehicleId}',
        );
      } catch (e) {
        debugPrint('[MemberModeController] APIエラー: $e');
      }
    } else {
      // 乗車ステップではない（徒歩など）→ 状態をリセット
      if (activeStep != null && !activeStep.isRide) {
        debugPrint('[MemberModeController] 非乗車ステップ: ${activeStep.kind}');
      }
      if (state.trackedStepId != null ||
          state.trackedVehicleId != null ||
          state.busProgress != null) {
        state = const RealtimeBusState();
      }
    }

    // 3. 進捗を更新 (時間基準 + API補正)
    if (resolvedEntry != null) {
      _ref
          .read(memberNavProgressProvider.notifier)
          .updateFromSchedule(
            trip,
            resolvedEntry,
            busProgress: state.trackedStepId == resolvedEntry.routeStepId
                ? state.busProgress
                : null,
          );
    }
  }
}

final memberModeControllerProvider =
    StateNotifierProvider.autoDispose<MemberModeController, RealtimeBusState>((
      ref,
    ) {
      return MemberModeController(ref, ref.watch(busLocationSourceProvider));
    });

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
  final nowTick = ref.watch(minuteTickerProvider);

  return tripAsync.whenData((trip) {
    if (trip == null) throw Exception("No Trip");

    final now = nowTick.value ?? appClock.now();

    // ルート情報の構築（表示用）
    final routeState = RouteState(
      stepsById: trip.stepsById,
      currentStepId: navProgress.currentStepId,
      busProgress: navProgress.busProgress,
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
});

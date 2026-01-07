import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../core/api_client.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../logic/trip_coordinator.dart';
import '../logic/trip_navigator.dart';
import 'trip_provider.dart';
import 'member_nav_progress_provider.dart';
import 'minute_ticker_provider.dart';

/// スケジュール解決結果を共有するProvider
/// 時間経過(ticker)またはTripの更新で再計算される
final memberScheduleStateProvider = Provider.autoDispose<AsyncValue<ResolvedScheduleState>>((ref) {
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

/// バスロケAPIの最新状態
class RealtimeBusState {
  final int? lastApiStopIndex;
  final String? lastRealtimeBusId; // Bus Stop Pole ID
  final String? vehicleId;         // Physical Bus ID (odpt:bus)

  const RealtimeBusState({
    this.lastApiStopIndex,
    this.lastRealtimeBusId,
    this.vehicleId,
  });
}

/// ビジネスロジック: APIポーリングと時間経過による進行管理
class MemberModeController extends StateNotifier<RealtimeBusState> {
  final Ref _ref;
  Timer? _pollingTimer;

  MemberModeController(this._ref) : super(const RealtimeBusState());

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
    _pollingTimer = Timer.periodic(const Duration(seconds: 30), (_) => _checkProgress());
  }

  Future<void> pollNow() async => _checkProgress();

  Future<void> _checkProgress() async {
    final trip = _ref.read(tripStreamProvider).value;
    if (trip == null) return;

    final navProgress = _ref.read(memberNavProgressProvider);
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    final routeState = RouteState(
      steps: allSteps,
      currentStepIndex: navProgress.currentStepIndex,
      nextStopIndex: navProgress.nextStopIndex,
      isMoving: false,
    );
    final resolvedState = TripCoordinator.resolveScheduleState(
      scheduleEntries: trip.schedule,
      routeState: routeState,
      now: appClock.now(),
      realtimeBusLocationId: state.lastRealtimeBusId,
    );
    final resolvedEntry = resolvedState.resolvedEntry!;
    StepSeg? activeStep;
    int? apiStopIndex;

    // 1. アクティブなエントリーがあれば、それに対応するステップを特定
    final stepIndex = resolvedEntry.routeStepIndex!;
    if (stepIndex >= 0 && stepIndex < allSteps.length) {
      activeStep = allSteps[stepIndex];
    }

    // 2. 乗車中かつルートIDがある場合のみAPI確認 (Realtime基準)
    if (activeStep != null && activeStep.isRide && activeStep.routeId != null) {
      if (activeStep.tripId == null) {
        // tripIdがない場合はAPI叩けないのでスキップ
        debugPrint('[MemberModeController] Skip API poll: tripId is null');
      } else {
        try {
          debugPrint('[MemberModeController] Fetching bus location for route=${activeStep.routeId}, trip=${activeStep.tripId}, vehicle=${state.vehicleId}');
          final result = await ApiClient.fetchBusLocation(
            routeId: activeStep.routeId!,
            tripId: activeStep.tripId!,
            vehicleId: state.vehicleId,
          );
          debugPrint('[MemberModeController] API Result: $result');
          
          final fromPoleId = result['odpt:fromBusstopPole'];
          final vehicleId = result['odpt:bus']; // Get physical bus ID

          if (fromPoleId != null) {
            final index = activeStep.stops.indexWhere((s) => s.stopId == fromPoleId);
            if (index != -1) {
              apiStopIndex = index;
              // APIから取れた位置をStateに保持
              state = RealtimeBusState(
                lastRealtimeBusId: fromPoleId,
                lastApiStopIndex: index,
                vehicleId: vehicleId, // Update/Keep vehicle ID
              );
              debugPrint("[MemberModeController] API Update success: Bus index $index / ID: $fromPoleId / Vehicle: $vehicleId");
            } else {
               final availableStopIds = activeStep.stops.map((s) => s.stopId).toList();
               debugPrint("[MemberModeController] Bus pole $fromPoleId found in API but not in step stops. Available: $availableStopIds");
               // Even if not in current segment steps, we found the bus on the correct trip!
               // It implies the bus is approaching the first stop of this segment (upstream).
               // We update the ID so the coordinator knows we are tracking it, but keep index null (or 0?)
               // If we set index null, progress bar relies on time.
               state = RealtimeBusState(
                 lastRealtimeBusId: fromPoleId,
                 lastApiStopIndex: null, // Not in "this" segment's stop list
                 vehicleId: vehicleId, // Lock onto this vehicle
               );
            }
          } else {
            debugPrint("[MemberModeController] API returned null/empty fromBusstopPole");
          }
        } catch (e) {
          debugPrint('[MemberModeController] API Error: $e');
        }
      }
    } else {
      debugPrint('[MemberModeController] Not in ride mode or missing IDs. activeStep=$activeStep, isRide=${activeStep?.isRide}, routeId=${activeStep?.routeId}');
      // 徒歩中などはAPI状態をリセット（あるいは前回の値を保持せずクリア）
      if (state.lastApiStopIndex != null) {
        state = const RealtimeBusState(lastApiStopIndex: null, lastRealtimeBusId: null);
      }
    }

    // 3. 進捗を更新 (時間基準 + API補正)
    // activeEntry (時間基準) をベースにしつつ、API情報 (apiStopIndex) があればそれを強制適用する
    _ref.read(memberNavProgressProvider.notifier).updateFromSchedule(
      trip,
      resolvedEntry,
      // APIで位置が取れていればそのバス停インデックスを、取れていなければStateの前回値を優先
      // どちらもなければnullになり、純粋な時間基準(updateFromScheduleのデフォルト挙動)になる
      forceStopIndex: apiStopIndex ?? state.lastApiStopIndex,
    );
  }
}

final memberModeControllerProvider = StateNotifierProvider.autoDispose<MemberModeController, RealtimeBusState>((ref) {
  return MemberModeController(ref);
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
final memberUiStateProvider = Provider.autoDispose<AsyncValue<MemberUiState>>((ref) {
  final tripAsync = ref.watch(tripStreamProvider);
  final navProgress = ref.watch(memberNavProgressProvider);
  final realtimeState = ref.watch(memberModeControllerProvider);
  final nowTick = ref.watch(minuteTickerProvider);
  
  return tripAsync.whenData((trip) {
    if (trip == null) throw Exception("No Trip");

    final now = nowTick.value ?? appClock.now();

    // ルート情報の構築（表示用）
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    final routeState = RouteState(
      steps: allSteps,
      currentStepIndex: navProgress.currentStepIndex,
      nextStopIndex: navProgress.nextStopIndex,
      isMoving: false,
    );
    
    final resolvedState = TripCoordinator.resolveScheduleState(
      scheduleEntries: trip.schedule,
      routeState: routeState,
      now: now,
      realtimeBusLocationId: realtimeState.lastRealtimeBusId,
    );

    // ナビゲーション表示状態の構築
    final navDisplayState = TripCoordinator.buildMemberNavigationState(
      trip: trip,
      routeState: routeState,
      now: now,
      realtimeBusLocationId: realtimeState.lastRealtimeBusId,
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

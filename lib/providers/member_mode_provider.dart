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
/// trip_idベースで追跡するため、vehicleIdは不要
class RealtimeBusState {
  /// 現在のバス位置（セグメント内のバス停インデックス）
  final int? lastApiStopIndex;
  /// 最後に取得したバス停ポールID
  final String? lastRealtimeBusId;

  const RealtimeBusState({
    this.lastApiStopIndex,
    this.lastRealtimeBusId,
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
    debugPrint('[MemberModeController] _checkProgress START');

    final trip = _ref.read(tripStreamProvider).value;
    if (trip == null) {
      debugPrint('[MemberModeController] trip=null');
      return;
    }

    final scheduleAsync = _ref.read(memberScheduleStateProvider);

    if (scheduleAsync.asData == null) {
      debugPrint(
        '[MemberModeController] schedule未準備: $scheduleAsync',
      );
      return;
    }

    final scheduleResolved = scheduleAsync.asData!.value;
    final resolvedEntry = scheduleResolved.resolvedEntry;

    debugPrint(
      '[MemberModeController] resolvedEntry='
      '${resolvedEntry?.label} '
      'routeStepIndex=${resolvedEntry?.routeStepIndex}',
    );

    final allSteps =
        trip.legs.expand((leg) => leg.candidate.steps).toList();

    StepSeg? activeStep;
    int? apiStopIndex;

    if (resolvedEntry?.routeStepIndex != null) {
      final stepIndex = resolvedEntry!.routeStepIndex!;

      // meeting は routeStepIndex=-1 が正常
      if (stepIndex >= 0) {
        if (stepIndex >= allSteps.length) {
          throw StateError(
            'routeStepIndexが範囲外です: '
            '$stepIndex / steps=${allSteps.length}',
          );
        }

        activeStep = allSteps[stepIndex];
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
    if (activeStep != null && activeStep.isRide && activeStep.routeId != null && activeStep.tripId != null) {
      debugPrint('[MemberModeController] 乗車中: route=${activeStep.routeId}, trip=${activeStep.tripId}');
      
      try {
        // trip_idベースでAPIを呼び出し（vehicleIdは指定しない）
        final result = await ApiClient.fetchBusLocation(
          routeId: activeStep.routeId!,
          tripId: activeStep.tripId!,
          // vehicleId は指定しない: trip_id でフィルタされる
        );
        debugPrint('[MemberModeController] API結果: $result');
        
        final fromPoleId = result['odpt:fromBusstopPole'] as String?;

        if (fromPoleId != null) {
          // セグメント内のバス停リストからAPIで返されたポールIDを検索
          int index = activeStep.stops.indexWhere((s) => s.stopId == fromPoleId);

          if (index != -1) {
            // ────────────────────────────────────────
            // セグメント内にいる → 追跡成功
            // ────────────────────────────────────────
            apiStopIndex = index;
            state = RealtimeBusState(
              lastRealtimeBusId: fromPoleId,
              lastApiStopIndex: index,
            );
            debugPrint("[MemberModeController] 追跡成功: index=$index, id=$fromPoleId");
          } else {
            // ────────────────────────────────────────
            // セグメント外にいる
            // ────────────────────────────────────────
            debugPrint("[MemberModeController] バス停 $fromPoleId はセグメント外");
            debugPrint("[MemberModeController] セグメント: ${activeStep.stops.map((s) => s.stopId).toList()}");
            debugPrint("[MemberModeController] 前回位置: ${state.lastApiStopIndex}");
            
            final wasRiding = state.lastApiStopIndex != null;
            
            if (wasRiding) {
              // 乗車中 + ロスト → 到着済み
              debugPrint("[MemberModeController] 乗車中にロスト → 到着済み");
              if (activeStep.stops.isNotEmpty) {
                apiStopIndex = activeStep.stops.length - 1;
              }
              state = RealtimeBusState(
                lastRealtimeBusId: activeStep.stops.isNotEmpty ? activeStep.stops.last.stopId : fromPoleId,
                lastApiStopIndex: activeStep.stops.isNotEmpty ? activeStep.stops.length - 1 : null,
              );
            } else {
              // 未乗車 + ロスト → 遅延継続
              debugPrint("[MemberModeController] 未乗車でロスト → 遅延継続");
              state = RealtimeBusState(
                lastRealtimeBusId: fromPoleId,
                lastApiStopIndex: null,
              );
            }
          }
        } else {
          debugPrint("[MemberModeController] APIレスポンスにバス停IDなし");
        }
      } catch (e) {
        debugPrint('[MemberModeController] APIエラー: $e');
      }
    } else {
      // 乗車ステップではない（徒歩など）→ 状態をリセット
      if (activeStep != null && !activeStep.isRide) {
        debugPrint('[MemberModeController] 非乗車ステップ: ${activeStep.kind}');
      }
      if (state.lastApiStopIndex != null || state.lastRealtimeBusId != null) {
        state = const RealtimeBusState();
      }
    }

    // 3. 進捗を更新 (時間基準 + API補正)
    if (resolvedEntry != null) {
      _ref.read(memberNavProgressProvider.notifier).updateFromSchedule(
        trip,
        resolvedEntry,
        forceStopIndex: apiStopIndex ?? state.lastApiStopIndex,
      );
     }
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

import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../core/app_clock.dart';
import '../core/api_client.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../logic/trip_coordinator.dart';
import '../logic/schedule_resolver.dart';
import 'trip_provider.dart';
import 'location_provider.dart';
import 'member_nav_progress_provider.dart';
import 'minute_ticker_provider.dart';

/// バスロケAPIの最新状態
class RealtimeBusState {
  final int? lastApiStopIndex;
  final String? lastRealtimeBusId;
  const RealtimeBusState({this.lastApiStopIndex, this.lastRealtimeBusId});
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

    // 【重要】GPS位置を使わず、現在時刻のみで「本来いるべきスケジュール」を解決する
    final scheduleResolved = ScheduleResolver.resolve(
      scheduleSorted: ScheduleResolver.sortCopy(trip.schedule),
      now: appClock.now(),
      trip: trip,
      currentStepIndex: null,
      nextStopIndex: null,
    );

    final activeEntry = scheduleResolved.activeEntry;
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    StepSeg? activeStep;
    int? apiStopIndex;

    // 1. アクティブなエントリーがあれば、それに対応するステップを特定
    if (activeEntry?.routeStepIndex != null) {
      final stepIndex = activeEntry!.routeStepIndex!;
      if (stepIndex >= 0 && stepIndex < allSteps.length) {
        activeStep = allSteps[stepIndex];
      }
    }

    // 2. 乗車中かつルートIDがある場合のみAPI確認 (Realtime基準)
    if (activeStep != null && activeStep.isRide && activeStep.routeId != null) {
      if (activeStep.tripId == null) {
        // tripIdがない場合はAPI叩けないのでスキップ
        debugPrint('Skip API poll: tripId is null');
      } else {
        try {
          final result = await ApiClient.fetchBusLocation(
            routeId: activeStep.routeId!,
            tripId: activeStep.tripId!,
          );
          final fromPoleId = result['odpt:fromBusstopPole'];

          if (fromPoleId != null) {
            final index = activeStep.stops.indexWhere((s) => s.stopId == fromPoleId);
            if (index != -1) {
              apiStopIndex = index;
              // APIから取れた位置をStateに保持
              state = RealtimeBusState(
                lastRealtimeBusId: fromPoleId,
                lastApiStopIndex: index,
              );
              debugPrint("API Update: Bus index $index / ID: $fromPoleId");
            }
          }
        } catch (e) {
          debugPrint('API Error: $e');
        }
      }
    } else {
      // 徒歩中などはAPI状態をリセット（あるいは前回の値を保持せずクリア）
      if (state.lastApiStopIndex != null) {
        state = const RealtimeBusState(lastApiStopIndex: null, lastRealtimeBusId: null);
      }
    }

    // 3. 進捗を更新 (時間基準 + API補正)
    // activeEntry (時間基準) をベースにしつつ、API情報 (apiStopIndex) があればそれを強制適用する
    if (activeEntry != null) {
      _ref.read(memberNavProgressProvider.notifier).updateFromSchedule(
        trip,
        activeEntry,
        // APIで位置が取れていればそのバス停インデックスを、取れていなければStateの前回値を優先
        // どちらもなければnullになり、純粋な時間基準(updateFromScheduleのデフォルト挙動)になる
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
  final ScheduleEntry? activeEntry;
  final int completedCount;
  final String activeLabel;
  final String displayTitle;
  final LatLng? currentPos;

  MemberUiState({
    required this.navState,
    required this.windowEntries,
    required this.activeEntry,
    required this.completedCount,
    required this.activeLabel,
    required this.displayTitle,
    this.currentPos,
  });
}

/// UI State Provider
final memberUiStateProvider = Provider.autoDispose<AsyncValue<MemberUiState>>((ref) {
  final tripAsync = ref.watch(tripStreamProvider);
  final locationAsync = ref.watch(locationStreamProvider);
  final manualOverride = ref.watch(locationOverrideProvider);
  final navProgress = ref.watch(memberNavProgressProvider);
  final realtimeState = ref.watch(memberModeControllerProvider);
  final nowTick = ref.watch(minuteTickerProvider);
  
  return tripAsync.whenData((trip) {
    if (trip == null) throw Exception("No Trip");

    final now = nowTick.value ?? appClock.now();
    final currentPos = manualOverride ??
        (locationAsync.value != null ? LatLng(locationAsync.value!.latitude, locationAsync.value!.longitude) : null);

    // ルート情報の構築（表示用）
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    final routeState = RouteState(
      steps: allSteps,
      currentStepIndex: navProgress.currentStepIndex,
      nextStopIndex: navProgress.nextStopIndex,
      isMoving: false,
    );
    
    // スケジュールの解決
    final scheduleResolved = ScheduleResolver.resolve(
      scheduleSorted: ScheduleResolver.sortCopy(trip.schedule),
      now: now,
      trip: trip,
      currentStepIndex: routeState.currentStepIndex,
      nextStopIndex: routeState.nextStopIndex,
    );

    // ナビゲーション表示状態の構築
    final navDisplayState = TripCoordinator.buildMemberNavigationState(
      trip: trip,
      scheduleState: scheduleResolved,
      routeState: routeState,
      now: now,
      realtimeBusLocationId: realtimeState.lastRealtimeBusId,
    );

    return MemberUiState(
      navState: navDisplayState,
      windowEntries: scheduleResolved.window,
      activeEntry: scheduleResolved.activeEntry,
      completedCount: scheduleResolved.completedCount,
      activeLabel: scheduleResolved.activeLabel,
      displayTitle: trip.displayTitle,
      currentPos: currentPos,
    );
  });
});
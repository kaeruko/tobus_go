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

    // 【変更】共通のスケジュールProviderから結果を取得
    // 自身がTimer内なので watch はできないが read で取得する。
    // AutoDisposeなので、UIでwatchされていなければ再計算コストがかかるかもしれないが、ロジックは一元化される。
    final scheduleAsync = _ref.read(memberScheduleStateProvider);
    
    // データがまだ無い、エラーなどの場合は何もしない
    if (scheduleAsync.asData == null) return;
    final scheduleResolved = scheduleAsync.asData!.value;

    final resolvedEntry = scheduleResolved.resolvedEntry;
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    StepSeg? activeStep;
    int? apiStopIndex;

    // 1. アクティブなエントリーがあれば、それに対応するステップを特定
    if (resolvedEntry?.routeStepIndex != null) {
      final stepIndex = resolvedEntry!.routeStepIndex!;
      if (stepIndex >= 0 && stepIndex < allSteps.length) {
        activeStep = allSteps[stepIndex];
      }
    }

    // 2. 乗車中かつルートIDがある場合のみAPI確認 (Realtime基準)
    if (activeStep != null && activeStep.isRide && activeStep.routeId != null) {
      debugPrint('[MemberModeController] CONFIRMATION: Active Step RouteID=${activeStep.routeId} (Title=${activeStep.title})');
      if (activeStep.tripId == null) {
        // tripIdがない場合はAPI叩けないのでスキップ
        debugPrint('[MemberModeController] Skip API poll: tripId is null');
      } else {
        // バスロケーションAPIを呼び出してリアルタイム位置を取得
        try {
          debugPrint('[MemberModeController] バス位置取得中: route=${activeStep.routeId}, trip=${activeStep.tripId}, vehicle=${state.vehicleId}');
          final result = await ApiClient.fetchBusLocation(
            routeId: activeStep.routeId!,
            tripId: activeStep.tripId!,
            vehicleId: state.vehicleId,
          );
          debugPrint('[MemberModeController] API結果: $result');
          
          // APIレスポンスからバス停ポールIDと車両IDを取得
          final fromPoleId = result['odpt:fromBusstopPole'];
          final vehicleId = result['odpt:bus']; // 物理的なバスID

          if (fromPoleId != null) {
            // 現在のステップのバス停リストからAPIで返されたポールIDを検索
            int index = activeStep.stops.indexWhere((s) => s.stopId == fromPoleId);

            if (index != -1) {
              // バス停が見つかった場合: インデックスとIDを更新
              apiStopIndex = index;
              // APIから取れた位置をStateに保持
              state = RealtimeBusState(
                lastRealtimeBusId: fromPoleId,
                lastApiStopIndex: index,
                vehicleId: vehicleId, // 車両IDを更新/保持
              );
              debugPrint("[MemberModeController] API更新成功: インデックス $index / ID: $fromPoleId / 車両: $vehicleId");
            } else {
               // バス停がこのセグメントのリストに見つからない場合
               final availableStopIds = activeStep.stops.map((s) => s.stopId).toList();
               final availableStopNames = activeStep.stops.map((s) => s.name).toList();
               debugPrint("[MemberModeController] バス停 $fromPoleId (車両: $vehicleId) はAPIで取得できたが、現在のステップのバス停リストには存在しない");
               debugPrint("[MemberModeController] 現在のステップのバス停ID: $availableStopIds");
               debugPrint("[MemberModeController] 現在のステップのバス停名: $availableStopNames");
               
               // このセグメントのバス停リストにはないが、正しいトリップ上でバスを発見した
               // → バスはこのセグメントの最初のバス停に向かっている（上流にいる）と推測
               // coordinatorに追跡中であることを知らせるためIDは更新するが、
               // インデックスはnullのままにする（プログレスバーは時間基準で表示される）
               state = RealtimeBusState(
                 lastRealtimeBusId: fromPoleId,
                 lastApiStopIndex: null, // このセグメントのバス停リストには存在しない
                 vehicleId: vehicleId, // この車両をロックオン
               );
            }
          } else {
            // APIからバス停ポールIDが返されなかった場合
            debugPrint("[MemberModeController] APIからfromBusstopPoleがnullまたは空で返された");
          }
        } catch (e) {
          // API呼び出し時のエラーハンドリング
          debugPrint('[MemberModeController] APIエラー: $e');
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
    // resolvedEntry (時間基準) をベースにしつつ、API情報 (apiStopIndex) があればそれを強制適用する
    if (resolvedEntry != null) {
      _ref.read(memberNavProgressProvider.notifier).updateFromSchedule(
        trip,
        resolvedEntry,
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

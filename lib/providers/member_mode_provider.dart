import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../core/app_clock.dart';
import '../core/api_client.dart';
import '../models/trip_models.dart';
import '../logic/trip_navigator.dart';
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

/// ビジネスロジック: APIポーリングと位置情報連携の仲介
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
    _pollingTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      _pollRealtimeData().catchError((error, stackTrace) {
        FlutterError.reportError(FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          context: const ErrorDescription('member realtime polling'),
        ));
        return Future.error(error, stackTrace);
      });
    });
  }

  /// 位置情報更新時のハンドラ
  void onLocationUpdated(LatLng pos, Trip trip) {
    // NavProgressProviderに進捗計算を依頼。
    // APIから取得した最新のバス停情報(lastApiStopIndex)があれば渡して補正させる。
    _ref.read(memberNavProgressProvider.notifier).updateProgress(
      trip, 
      pos, 
      forceStopIndex: state.lastApiStopIndex
    );
  }

  Future<void> _pollRealtimeData() async {
    final trip = _ref.read(tripStreamProvider).value;
    final navState = _ref.read(memberNavProgressProvider);
    if (trip == null) return;

    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    if (navState.currentStepIndex <= 0 || navState.currentStepIndex >= allSteps.length) return;

    final currentStep = allSteps[navState.currentStepIndex];

    // 乗車中かつルートIDがある場合のみAPI確認
    if (currentStep.isRide && currentStep.routeId != null) {
      debugPrint('Polling realtime bus location for route ${currentStep.routeId}');

      final result = await ApiClient.fetchBusLocation(
        routeId: currentStep.routeId!,
        tripId: currentStep.tripId,
      );
      final fromPoleId = result['odpt:fromBusstopPole'];

      if (fromPoleId != null) {
        final index = currentStep.stops.indexWhere((s) => s.stopId == fromPoleId);
        // APIから取れた位置を保持
        state = RealtimeBusState(
          lastRealtimeBusId: fromPoleId,
          lastApiStopIndex: (index != -1) ? index : state.lastApiStopIndex,
        );
        debugPrint('[Realtime] bus stop index resolved: ${index != -1 ? index : 'unknown'} (ID: $fromPoleId)');
      }
    } else {
      // 徒歩中などはリセット
      if (state.lastApiStopIndex != null) {
        state = const RealtimeBusState(lastApiStopIndex: null, lastRealtimeBusId: null);
      }
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
      scheduleSorted: trip.schedule..sort((a, b) => a.plannedAt.compareTo(b.plannedAt)),
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
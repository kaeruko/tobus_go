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
    _pollRealtimeData();
    _pollingTimer = Timer.periodic(const Duration(seconds: 30), (_) => _pollRealtimeData());
  }

  Future<void> pollNow() async => _pollRealtimeData();

  Future<void> _pollRealtimeData() async {
    final trip = _ref.read(tripStreamProvider).value;
    if (trip == null) return;

    final schedule = ScheduleResolver.sortCopy(trip.schedule);
    final scheduleResolved = ScheduleResolver.resolve(
      scheduleSorted: schedule,
      now: appClock.now(),
      trip: trip,
      currentStepIndex: null,
      nextStopIndex: null,
    );

    final activeEntry = scheduleResolved.activeEntry;
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    StepSeg? activeStep;

    if (activeEntry?.routeStepIndex != null) {
      final stepIndex = activeEntry!.routeStepIndex!;
      if (stepIndex >= 0 && stepIndex < allSteps.length) {
        activeStep = allSteps[stepIndex];
        _ref.read(memberNavProgressProvider.notifier).updateFromSchedule(
          trip,
          activeEntry,
          forceStopIndex: state.lastApiStopIndex,
        );
      }
    }

    // 乗車中かつルートIDがある場合のみAPI確認
    if (activeStep != null && activeStep.isRide && activeStep.routeId != null) {
      if (activeStep.tripId == null) {
        throw StateError('tripId is required to poll realtime bus location');
      }

      final result = await ApiClient.fetchBusLocation(
        routeId: activeStep.routeId!,
        tripId: activeStep.tripId!,
      );
      final fromPoleId = result['odpt:fromBusstopPole'];

      if (fromPoleId != null) {
        final index = activeStep.stops.indexWhere((s) => s.stopId == fromPoleId);
        // APIから取れた位置を保持
        state = RealtimeBusState(
          lastRealtimeBusId: fromPoleId,
          lastApiStopIndex: (index != -1) ? index : state.lastApiStopIndex,
        );
        if (activeEntry != null) {
          _ref.read(memberNavProgressProvider.notifier).updateFromSchedule(
            trip,
            activeEntry,
            forceStopIndex: (index != -1) ? index : state.lastApiStopIndex,
          );
        }
        if (index != -1) debugPrint("API Update: Bus index $index / ID: $fromPoleId");
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
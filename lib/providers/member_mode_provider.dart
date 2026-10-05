import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../constants.dart';
import '../core/app_clock.dart';
import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../models/bus_progress.dart';
import '../models/rail_progress.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../logic/alighting_alert.dart';
import '../logic/bus_arrival_fallback.dart';
import '../logic/replan_anchor.dart';
import '../logic/replan_transit_memory.dart';
import '../logic/replan_transit_observation.dart';
import '../logic/trip_coordinator.dart';
import '../logic/trip_navigator.dart';
import '../services/bus_location_source.dart';
import '../services/train_location_source.dart';
import 'trip_provider.dart';
import 'member_nav_progress_provider.dart';
import 'minute_ticker_provider.dart';

Leg resolveGroupActiveLeg(Trip trip) {
  if (trip.tripType != TripType.group) {
    throw StateError(
      'Group active leg resolverにGroup以外のtripが渡されました: '
      'tripId=${trip.id}, type=${trip.tripType.name}',
    );
  }

  final activeLegIndex = trip.activeLegIndex;
  if (activeLegIndex < 0 || activeLegIndex >= trip.legs.length) {
    throw StateError(
      'Groupのactive legを特定できません: '
      'tripId=${trip.id}, activeLegIndex=$activeLegIndex, '
      'legs=${trip.legs.length}, completedLegIndex=${trip.completedLegIndex}',
    );
  }
  return trip.legs[activeLegIndex];
}

ScheduleEntry _navigationEntryWithFixedTransitClock(
  Trip trip,
  ScheduleEntry entry,
) {
  if (entry.itemKind != ScheduleEntryKind.ride &&
      entry.itemKind != ScheduleEntryKind.arrival) {
    return entry;
  }

  final stepId = entry.routeStepId;
  if (stepId == null || stepId.isEmpty) {
    throw StateError(
      '乗車系予定にrouteStepIdがありません: '
      'tripId=${trip.id}, entryId=${entry.id}, kind=${entry.itemKind.name}',
    );
  }
  final step = trip.stepsById[stepId];
  if (step == null) {
    throw StateError(
      '乗車系予定が存在しないrouteStepIdを参照しています: '
      'tripId=${trip.id}, entryId=${entry.id}, routeStepId=$stepId',
    );
  }
  if (!step.isRide) {
    throw StateError(
      '乗車系予定のrouteStepIdが乗車stepではありません: '
      'tripId=${trip.id}, entryId=${entry.id}, '
      'routeStepId=$stepId, stepKind=${step.kind}',
    );
  }

  final fixed = entry.itemKind == ScheduleEntryKind.ride
      ? trip.routeStepDepartureAt(stepId)
      : trip.routeStepArrivalAt(stepId);
  if (entry.plannedAt == fixed) return entry;

  debugPrint(
    '[ScheduleIntegrity] navigation uses fixed transit clock: '
    'entryId=${entry.id} stepId=$stepId kind=${entry.itemKind.name} '
    'stored=${entry.plannedAt.toIso8601String()} '
    'fixed=${fixed.toIso8601String()}',
  );
  return ScheduleEntry(
    id: entry.id,
    plannedAt: fixed,
    label: entry.label,
    description: entry.description,
    itemKind: entry.itemKind,
    legIndex: entry.legIndex,
    generatedBy: entry.generatedBy,
    routeStepId: entry.routeStepId,
    routeRole: entry.routeRole,
  );
}

List<ScheduleEntry> _navigationScheduleForTrip(Trip trip) {
  Iterable<ScheduleEntry> canonicalize(Iterable<ScheduleEntry> entries) =>
      entries.map((entry) => _navigationEntryWithFixedTransitClock(trip, entry));

  if (trip.isSolo) {
    if (trip.legs.length != 1) {
      throw StateError(
        'Solo navigationは1 legを前提とします: '
        'tripId=${trip.id}, legs=${trip.legs.length}',
      );
    }
    return trip.schedule;
  }

  resolveGroupActiveLeg(trip);
  final activeLegIndex = trip.activeLegIndex;
  final entries = canonicalize(
    trip.schedule.where((entry) => entry.legIndex == activeLegIndex),
  ).toList(growable: false);
  if (entries.isEmpty) {
    throw StateError(
      'Groupのactive legに予定がありません: '
      'tripId=${trip.id}, activeLegIndex=$activeLegIndex',
    );
  }
  return entries;
}

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
          scheduleEntries: _navigationScheduleForTrip(trip),
          now: now,
        );
      });
    }, dependencies: [tripStreamProvider]);

class RealtimeTransitState {
  final String? trackedStepId;
  final String? trackedVehicleId;
  final BusProgress? busProgress;
  final RailProgress? railProgress;
  final ReplanTransitMemory replanTransitMemory;

  const RealtimeTransitState({
    this.trackedStepId,
    this.trackedVehicleId,
    this.busProgress,
    this.railProgress,
    this.replanTransitMemory = const ReplanTransitMemory(),
  });

  RidingTransitObservation? get ridingTransitObservation =>
      replanTransitMemory.ridingTransit;

  ReplanTransitPlace? get lastConfirmedTransitPlace =>
      replanTransitMemory.lastConfirmedTransitPlace;
}

class _PendingAlightingHaptic {
  final AlightingAlert alert;
  final StepSeg step;

  const _PendingAlightingHaptic({required this.alert, required this.step});
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
  final AlightingAlertTracker _alightingAlertTracker = AlightingAlertTracker();
  Timer? _pollingTimer;
  DateTime? _debugPreviousPollAt;
  String? _debugPreviousStepId;
  String? _debugPreviousVehicleId;
  int? _debugPreviousObservedSequence;
  int? _debugPreviousFromIndex;
  int? _debugPreviousVehicleTimestamp;
  String? _debugPrintedTimelineKey;
  bool _checkProgressInFlight = false;

  MemberModeController(
    this._ref,
    this._busLocationSource,
    this._trainLocationSource,
  ) : super(const RealtimeTransitState());

  /// Restores history while keeping completion of the same ride authoritative.
  void restoreHistoricalTransitMemory(ReplanTransitMemory restored) {
    final current = state.replanTransitMemory;
    // ODPT can answer before disk restoration with a sample from a service
    // already finished here. Completion of that same ride outranks its sample.
    final restoredFinishesTrackedRide =
        restored.completedRideStepId != null &&
        current.completedRideStepId == null &&
        restored.completedRideStepId == state.trackedStepId;
    if (current.ridingTransit != null ||
        current.lastConfirmedTransitPlace != null ||
        current.knownOnboardStepId != null ||
        current.completedRideStepId != null) {
      if (!restoredFinishesTrackedRide) return;
    }
    if (restored.lastConfirmedTransitPlace == null &&
        restored.knownOnboardStepId == null &&
        restored.completedRideStepId == null) {
      return;
    }
    state = RealtimeTransitState(
      trackedStepId:
          restored.knownOnboardStepId ?? restored.completedRideStepId,
      replanTransitMemory: restored,
    );
  }

  void _initialize() {
    _startPolling();
  }

  @override
  void dispose() {
    debugPrint(
      '[MemberModeController] dispose '
      'trackedStep=${state.trackedStepId} '
      'vehicle=${state.trackedVehicleId} '
      'busPhase=${state.busProgress?.phase.name} '
      'railPhase=${state.railProgress?.phase.name} '
      'knownOnboard=${state.replanTransitMemory.knownOnboardStepId}',
    );
    _pollingTimer?.cancel();
    super.dispose();
  }

  void _startPolling() {
    _pollingTimer?.cancel();
    _pollingTimer = Timer.periodic(
      kRealtimePollInterval,
      (_) => _checkProgress(),
    );

    // Register the timer first: resolving a newly loaded Trip can dispose this
    // controller synchronously during the first poll, which must cancel it.
    _checkProgress(forceRefresh: true);
  }

  Future<void> pollNow() async => _checkProgress(forceRefresh: true);

  Future<void> _checkProgress({bool forceRefresh = false}) async {
    if (!mounted) return;
    if (_checkProgressInFlight) {
      debugPrint(
        '[MemberModeController] _checkProgress SKIP '
        'forceRefresh=$forceRefresh reason=in_flight',
      );
      return;
    }

    _PendingAlightingHaptic? pendingHaptic;
    _checkProgressInFlight = true;
    try {
      pendingHaptic = await _runProgressCheck(forceRefresh: forceRefresh);
    } finally {
      _checkProgressInFlight = false;
    }

    if (pendingHaptic != null && mounted) {
      await _performAlightingAlertHaptic(
        pendingHaptic.alert,
        step: pendingHaptic.step,
      );
    }
  }

  Future<_PendingAlightingHaptic?> _runProgressCheck({
    bool forceRefresh = false,
  }) async {
    debugPrint(
      '[MemberModeController] _checkProgress START '
      'forceRefresh=$forceRefresh',
    );

    final trip = _ref.read(tripStreamProvider).valueOrNull;
    if (!mounted) return null;
    if (trip == null) {
      debugPrint('[MemberModeController] trip=null');
      return null;
    }

    if (kDebugMode) {
      final debugNow = appClock.now();
      debugPrint(
        '[ScheduleClockDebug] '
        'now=${debugNow.toIso8601String()} '
        'nowUtc=${debugNow.isUtc} '
        'schedule=${trip.schedule.map((entry) {
          return '${entry.plannedAt.toIso8601String()}'
              '|utc=${entry.plannedAt.isUtc}'
              '|${entry.label}';
        }).join(' || ')}',
      );
    }

    final navProgress = _ref.read(memberNavProgressProvider);
    // Reading progress may refresh its Trip identity and replace this session.
    if (!mounted) return null;
    var knownBusProgress = state.busProgress ?? navProgress.busProgress;
    final memory = state.replanTransitMemory;
    final rememberedBusStepId =
        knownBusProgress?.stepId ??
        memory.completedRideStepId ??
        memory.knownOnboardStepId;
    final rememberedBusStep = trip.stepsById[rememberedBusStepId];
    if (rememberedBusStep?.kind == 'bus') {
      final arrivalAt = _plannedRideArrivalAt(trip, rememberedBusStep!.stepId);
      final alreadyCompleted =
          memory.completedRideStepId == rememberedBusStepId ||
          knownBusProgress?.phase == BusProgressPhase.arrived;
      final scheduleCompleted = shouldCompleteBusFromSchedule(
        now: appClock.now(),
        plannedArrivalAt: arrivalAt,
      );
      if ((alreadyCompleted && !scheduleCompleted) ||
          (scheduleCompleted &&
              (knownBusProgress != null ||
                  memory.knownOnboardStepId != null))) {
        _completeBusRide(
          rememberedBusStep,
          lastProgress: knownBusProgress,
          completedAt: alreadyCompleted
              ? _completedBusTime(arrivalAt)
              : arrivalAt,
        );
        knownBusProgress = state.busProgress;
      }
    }

    final knownRailProgress = state.railProgress ?? navProgress.railProgress;
    final scheduleResolved = TripCoordinator.resolveScheduleState(
      scheduleEntries: _navigationScheduleForTrip(trip),
      now: appClock.now(),
      routeState: RouteState(
        stepsById: trip.stepsById,
        currentStepId: state.trackedStepId ?? navProgress.currentStepId,
        busProgress: knownBusProgress,
        railProgress: knownRailProgress,
      ),
    );
    var resolvedEntry = scheduleResolved.resolvedEntry;

    // A restored onboard marker has no realtime progress. Poll that exact ride
    // again, then use realtime or the planned-arrival fallback to resolve it.
    final knownOnboardStepId = state.replanTransitMemory.knownOnboardStepId;
    if (knownOnboardStepId != null &&
        state.replanTransitMemory.ridingTransit == null &&
        resolvedEntry?.routeStepId != knownOnboardStepId) {
      resolvedEntry = _knownOnboardRideEntry(trip, knownOnboardStepId);
      debugPrint(
        '[MemberModeController] Realtime不明の乗車stepを継続追跡: '
        '$knownOnboardStepId',
      );
    }

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

    if (kDebugMode) {
      final stepId = activeStep?.stepId;
      final stepSchedules = stepId == null
          ? []
          : trip.schedule
                .where((entry) => entry.routeStepId == stepId)
                .map(
                  (entry) => {
                    'legIndex': entry.legIndex,
                    'kind': entry.itemKind.name,
                    'source': entry.generatedBy.name,
                    'plannedAt': entry.plannedAt.toIso8601String(),
                  },
                )
                .toList();
      final diagnostic = {
        'tripId': trip.id,
        'tripType': trip.tripType.name,
        'travelPhase': trip.travelPhase.name,
        'completedLegIndex': trip.completedLegIndex,
        'activeLegIndex': trip.activeLegIndex,
        'legDirections': trip.legs.map((leg) => leg.direction.name).toList(),
        'trackedStepId': state.trackedStepId,
        'knownOnboardStepId': state.replanTransitMemory.knownOnboardStepId,
        'completedRideStepId': state.replanTransitMemory.completedRideStepId,
        'resolvedStepId': stepId,
        'stepSchedules': stepSchedules,
      };
      debugPrint('[TripLegDebug] ${jsonEncode(diagnostic)}');
    }

    AlightingAlert? pendingAlightingAlert;

    if (activeStep != null &&
        activeStep.kind == 'bus' &&
        activeStep.routeId != null &&
        activeStep.tripId != null) {
      final plannedDepartureAt = _plannedRideDepartureAt(
        trip,
        activeStep.stepId,
      );
      final plannedArrivalAt = _plannedRideArrivalAt(trip, activeStep.stepId);
      pendingAlightingAlert = await _updateBusProgress(
        activeStep,
        plannedDepartureAt: plannedDepartureAt,
        plannedArrivalAt: plannedArrivalAt,
        forceRefresh: forceRefresh,
      );
    } else if (activeStep != null && activeStep.kind == 'rail') {
      await _updateRailProgress(activeStep, forceRefresh: forceRefresh);
    } else {
      // 徒歩などに移っても、最後に確定した駅/停留所は再探索用に保持する。
      if (activeStep != null && !activeStep.isRide) {
        debugPrint('[MemberModeController] 非乗車ステップ: ${activeStep.kind}');
      }
      final nextMemory = state.replanTransitMemory.clearActiveRide();
      if (state.trackedStepId != null ||
          state.trackedVehicleId != null ||
          state.busProgress != null ||
          state.railProgress != null ||
          state.ridingTransitObservation != null ||
          state.replanTransitMemory.knownOnboardStepId != null) {
        state = RealtimeTransitState(replanTransitMemory: nextMemory);
      }
    }

    if (!mounted) return null;

    // 進捗を更新 (時間基準 + API補正)
    if (resolvedEntry != null) {
      final progressNotifier = _ref.read(memberNavProgressProvider.notifier);
      if (!mounted) return null;
      final sameTrackedStep = state.trackedStepId == resolvedEntry.routeStepId;
      final rideRealtimeUnavailable =
          sameTrackedStep &&
          state.replanTransitMemory.knownOnboardStepId ==
              resolvedEntry.routeStepId &&
          state.replanTransitMemory.ridingTransit == null;
      progressNotifier.updateFromSchedule(
        trip,
        resolvedEntry,
        busProgress: sameTrackedStep ? state.busProgress : null,
        railProgress: sameTrackedStep ? state.railProgress : null,
        rideRealtimeUnavailable: rideRealtimeUnavailable,
      );
      final committed = _ref.read(memberNavProgressProvider);
      debugPrint(
        '[MemberModeController] navProgress committed '
        'entry=${resolvedEntry.id} '
        'entryKind=${resolvedEntry.itemKind.name} '
        'entryStep=${resolvedEntry.routeStepId} '
        'currentStep=${committed.currentStepId} '
        'busPhase=${committed.busProgress?.phase.name} '
        'busFrom=${committed.busProgress?.fromStopId} '
        'busNext=${committed.busProgress?.nextStopId} '
        'railPhase=${committed.railProgress?.phase.name} '
        'realtimeUnavailable=${committed.rideRealtimeUnavailable}',
      );
    }

    // Return the notification effect only after navigation state is committed.
    // _checkProgress releases its in-flight guard before awaiting the platform
    // channel so a subsequent explicit poll is never blocked by haptics.
    if (pendingAlightingAlert == null) {
      return null;
    }
    if (activeStep == null || activeStep.kind != 'bus') {
      throw StateError(
        '降車通知がbus step以外で生成されました: '
        'stepId=${activeStep?.stepId}, kind=${activeStep?.kind}',
      );
    }
    return _PendingAlightingHaptic(
      alert: pendingAlightingAlert,
      step: activeStep,
    );
  }

  Future<AlightingAlert?> _updateBusProgress(
    StepSeg activeStep, {
    required DateTime plannedDepartureAt,
    required DateTime plannedArrivalAt,
    required bool forceRefresh,
  }) async {
    debugPrint(
      '[MemberModeController] バス乗車中: '
      'route=${activeStep.routeId}, trip=${activeStep.tripId}',
    );

    final now = appClock.now();
    final alreadyCompleted =
        state.replanTransitMemory.completedRideStepId == activeStep.stepId ||
        state.busProgress?.stepId == activeStep.stepId &&
            state.busProgress?.phase == BusProgressPhase.arrived;
    if (alreadyCompleted ||
        shouldCompleteBusFromSchedule(
          now: now,
          plannedArrivalAt: plannedArrivalAt,
        )) {
      _completeBusRide(
        activeStep,
        lastProgress: state.busProgress?.stepId == activeStep.stepId
            ? state.busProgress
            : null,
        completedAt: alreadyCompleted
            ? _completedBusTime(plannedArrivalAt)
            : plannedArrivalAt,
      );
      return null;
    }

    try {
      final trackedVehicleId = state.trackedStepId == activeStep.stepId
          ? state.trackedVehicleId
          : null;
      final location = await _fetchBusLocationWithSingleNotFoundRetry(
        activeStep,
        plannedDepartureAt: plannedDepartureAt,
        plannedArrivalAt: plannedArrivalAt,
        vehicleId: trackedVehicleId,
        forceRefresh: forceRefresh,
      );
      if (!mounted) return null;
      // A disk load may restore completion while this request is in flight.
      // Its later vehicle sample must never reactivate that finished service.
      if (state.replanTransitMemory.completedRideStepId == activeStep.stepId) {
        _completeBusRide(
          activeStep,
          completedAt: _completedBusTime(plannedArrivalAt),
        );
        return null;
      }

      final realtimeProgress = BusProgress.forStep(
        step: activeStep,
        fromStopId: location.fromStopId,
        beforeFirstStop: location.beforeFirstStop,
        tripStopIds: location.tripStopIds,
        observedStopId: location.rawStopId,
        observedStopName: location.rawStopName,
        observedStopNameEn: location.rawStopNameEn,
        currentStatus: location.currentStatus,
        vehicleAgeSeconds: location.vehicleAgeSeconds,
      );
      final now = appClock.now();
      final assumeArrived = shouldCompleteBusFromSchedule(
        now: now,
        plannedArrivalAt: plannedArrivalAt,
      );
      final progress = assumeArrived
          ? completeBusAtDestination(
              step: activeStep,
              lastProgress: realtimeProgress,
            )
          : realtimeProgress;
      if (assumeArrived) {
        debugPrint(
          '[MemberModeController] バス降車を予定時刻で確定: '
          'step=${activeStep.stepId} '
          'plannedArrival=${plannedArrivalAt.toIso8601String()} '
          'vehicleAge=${location.vehicleAgeSeconds}s '
          'observedStop=${location.rawStopId}/${location.rawStopName}',
        );
      }
      final nextMemory = _replanMemoryForBus(
        step: activeStep,
        progress: progress,
        location: location,
        now: assumeArrived ? plannedArrivalAt : now,
      );
      _logBusProgressTrace(
        step: activeStep,
        location: location,
        progress: realtimeProgress,
        forceRefresh: forceRefresh,
      );
      state = RealtimeTransitState(
        trackedStepId: activeStep.stepId,
        trackedVehicleId: location.vehicleId,
        busProgress: progress,
        replanTransitMemory: nextMemory,
      );

      final alightingAlert = assumeArrived
          ? null
          : _alightingAlertTracker.evaluate(
              step: activeStep,
              location: location,
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
        'lastConfirmed=${nextMemory.lastConfirmedTransitPlace?.name}, '
        'lastConfirmedAt=${nextMemory.lastConfirmedTransitAt?.toIso8601String()}, '
        'serverNow=${location.serverNow}, '
        'clientNow=${DateTime.now().toUtc().toIso8601String()}',
      );
      return alightingAlert;
    } on BusLocationNotAvailableException catch (e) {
      if (!mounted) return null;
      if (state.replanTransitMemory.completedRideStepId == activeStep.stepId) {
        _completeBusRide(
          activeStep,
          completedAt: _completedBusTime(plannedArrivalAt),
        );
        return null;
      }

      final now = appClock.now();
      final navProgress = _ref.read(memberNavProgressProvider);
      if (!mounted) return null;
      final lastProgress = state.busProgress?.stepId == activeStep.stepId
          ? state.busProgress
          : navProgress.busProgress?.stepId == activeStep.stepId
          ? navProgress.busProgress
          : null;

      // The timetable is authoritative for completion. A request that started
      // before arrival can finish after it, so check the clock again here.
      if (shouldCompleteBusFromSchedule(
        now: now,
        plannedArrivalAt: plannedArrivalAt,
      )) {
        _completeBusRide(
          activeStep,
          lastProgress: lastProgress,
          completedAt: plannedArrivalAt,
        );
        debugPrint(
          '[MemberModeController] バス降車を予定時刻で確定(API取得失敗後): '
          'step=${activeStep.stepId} '
          'plannedArrival=${plannedArrivalAt.toIso8601String()} '
          'lastObserved=${lastProgress?.observedStopId}/'
          '${lastProgress?.observedStopName} '
          'error=$e',
        );
        return null;
      }

      if (e.code == 'bus_realtime_not_started') {
        state = RealtimeTransitState(
          trackedStepId: activeStep.stepId,
          replanTransitMemory: state.replanTransitMemory.clearActiveRide(),
        );
        debugPrint(
          '[MemberModeController] バスRealtime開始前: '
          'step=${activeStep.stepId} plannedDeparture='
          '${plannedDepartureAt.toIso8601String()}',
        );
        return null;
      }

      // An exact route/trip match may not appear in the realtime feed until
      // the assigned vehicle starts reporting. Preserve an already-confirmed
      // onboard fact for this exact step, but never retain a stale forecast.
      state = RealtimeTransitState(
        trackedStepId: activeStep.stepId,
        trackedVehicleId: state.trackedStepId == activeStep.stepId
            ? state.trackedVehicleId
            : null,
        replanTransitMemory: state.replanTransitMemory
            .markRideRealtimeUnavailable(activeStep.stepId),
      );
      debugPrint('[MemberModeController] バス位置なし: $e');
      return null;
    } catch (e, stackTrace) {
      if (!mounted) return null;
      debugPrint('[MemberModeController] バスAPIエラー: $e');
      debugPrintStack(stackTrace: stackTrace);
      rethrow;
    }
  }

  Future<BusLocation> _fetchBusLocationWithSingleNotFoundRetry(
    StepSeg activeStep, {
    required DateTime plannedDepartureAt,
    required DateTime plannedArrivalAt,
    required String? vehicleId,
    required bool forceRefresh,
  }) async {
    Future<BusLocation> fetchOnce({required bool force}) {
      return _busLocationSource.fetch(
        routeId: activeStep.routeId!,
        tripId: activeStep.tripId!,
        boardingStopId: activeStep.departureStopId,
        scheduledDepartureAt: plannedDepartureAt,
        vehicleId: vehicleId,
        forceRefresh: force,
      );
    }

    try {
      return await fetchOnce(force: forceRefresh);
    } on BusLocationNotAvailableException catch (e) {
      final now = appClock.now();
      final retry =
          e.code == 'bus_trip_not_found' &&
          shouldRetryMissingBusRealtime(
            now: now,
            plannedDepartureAt: plannedDepartureAt,
            plannedArrivalAt: plannedArrivalAt,
          );
      if (!retry) rethrow;

      debugPrint(
        '[MemberModeController] バス便404を1回だけ再取得: '
        'step=${activeStep.stepId} '
        'plannedDeparture=${plannedDepartureAt.toIso8601String()} '
        'plannedArrival=${plannedArrivalAt.toIso8601String()}',
      );
      // Keep route/trip/stop/vehicle identity unchanged. Force only the backend
      // snapshot refresh so the retry actually re-reads ODPT instead of the
      // same cached feed.
      return await fetchOnce(force: true);
    }
  }

  void _completeBusRide(
    StepSeg step, {
    BusProgress? lastProgress,
    required DateTime completedAt,
  }) {
    if (state.busProgress?.stepId == step.stepId &&
        state.busProgress?.phase == BusProgressPhase.arrived &&
        state.replanTransitMemory.completedRideStepId == step.stepId) {
      return;
    }
    state = RealtimeTransitState(
      trackedStepId: step.stepId,
      trackedVehicleId: state.trackedStepId == step.stepId
          ? state.trackedVehicleId
          : null,
      busProgress: completeBusAtDestination(
        step: step,
        lastProgress: lastProgress,
      ),
      replanTransitMemory: state.replanTransitMemory.markArrived(
        _destinationPlace(step),
        confirmedAt: completedAt,
        stepId: step.stepId,
      ),
    );
  }

  DateTime _completedBusTime(DateTime plannedArrivalAt) {
    final now = appClock.now();
    return state.replanTransitMemory.lastConfirmedTransitAt ??
        (now.isBefore(plannedArrivalAt) ? now : plannedArrivalAt);
  }

  Future<void> _performAlightingAlertHaptic(
    AlightingAlert alert, {
    required StepSeg step,
  }) async {
    switch (alert) {
      case AlightingAlert.twoStopsBefore:
        debugPrint(
          '[MemberModeController] 降車予告: あと2停留所 '
          'step=${step.stepId} destination=${step.toName}',
        );
        await HapticFeedback.mediumImpact();
        break;
      case AlightingAlert.nextStop:
        debugPrint(
          '[MemberModeController] 降車予告: 次で降車 '
          'step=${step.stepId} destination=${step.toName}',
        );
        await HapticFeedback.heavyImpact();
        break;
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
      if (!mounted) return;
      final progress = RailProgress.forLocation(
        stepId: activeStep.stepId,
        location: location,
      );
      final nextMemory = _replanMemoryForRail(
        step: activeStep,
        progress: progress,
        location: location,
        now: appClock.now(),
      );
      state = RealtimeTransitState(
        trackedStepId: activeStep.stepId,
        trackedVehicleId: location.vehicleId,
        railProgress: progress,
        replanTransitMemory: nextMemory,
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
        'lastConfirmed=${nextMemory.lastConfirmedTransitPlace?.name}, '
        'lastConfirmedAt=${nextMemory.lastConfirmedTransitAt?.toIso8601String()}, '
        'vehicleAge=${location.vehicleAgeSeconds}s',
      );
    } on TrainLocationNotAvailableException catch (e) {
      if (!mounted) return;
      // A reporting train can disappear temporarily around service boundaries.
      // Keep confirmed onboard/last-station facts, but do not synthesize a
      // station position or retain a stale predicted next station.
      state = RealtimeTransitState(
        trackedStepId: activeStep.stepId,
        trackedVehicleId: state.trackedStepId == activeStep.stepId
            ? state.trackedVehicleId
            : null,
        replanTransitMemory: state.replanTransitMemory
            .markRideRealtimeUnavailable(activeStep.stepId),
      );
      debugPrint('[MemberModeController] 鉄道位置なし: $e');
    } catch (e, stackTrace) {
      if (!mounted) return;
      debugPrint('[MemberModeController] 鉄道APIエラー: $e');
      debugPrintStack(stackTrace: stackTrace);
      rethrow;
    }
  }

  ReplanTransitMemory _replanMemoryForBus({
    required StepSeg step,
    required BusProgress progress,
    required BusLocation location,
    required DateTime now,
  }) {
    switch (progress.phase) {
      case BusProgressPhase.approaching:
        return state.replanTransitMemory.clearActiveRide();
      case BusProgressPhase.arrived:
        return state.replanTransitMemory.markArrived(
          _destinationPlace(step),
          confirmedAt: now,
          stepId: step.stepId,
        );
      case BusProgressPhase.riding:
        final observation = ReplanTransitObservationAdapter.fromBus(
          step: step,
          progress: progress,
          location: location,
          now: now,
        );
        return state.replanTransitMemory.observeRide(observation);
    }
  }

  ReplanTransitMemory _replanMemoryForRail({
    required StepSeg step,
    required RailProgress progress,
    required TrainLocation location,
    required DateTime now,
  }) {
    switch (progress.phase) {
      case RailProgressPhase.approaching:
        return state.replanTransitMemory.clearActiveRide();
      case RailProgressPhase.arrived:
        return state.replanTransitMemory.markArrived(
          _destinationPlace(step),
          confirmedAt: now,
        );
      case RailProgressPhase.riding:
        final observation = ReplanTransitObservationAdapter.fromRail(
          step: step,
          progress: progress,
          location: location,
          now: now,
        );
        return state.replanTransitMemory.observeRide(observation);
    }
  }

  DateTime _plannedRideDepartureAt(Trip trip, String stepId) {
    final matches = trip.schedule
        .where(
          (entry) =>
              entry.generatedBy == ScheduleEntrySource.route &&
              entry.itemKind == ScheduleEntryKind.ride &&
              entry.routeStepId == stepId,
        )
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '乗車stepの発車予定を一意に特定できません: '
        'stepId=$stepId, matches=${matches.length}',
      );
    }
    final stored = matches.single.plannedAt;
    final fixed = trip.routeStepDepartureAt(stepId);
    if (stored != fixed) {
      debugPrint(
        '[ScheduleIntegrity] ride departure differs from fixed route clock: '
        'stepId=$stepId stored=$stored fixed=$fixed',
      );
    }
    return fixed;
  }

  DateTime _plannedRideArrivalAt(Trip trip, String stepId) {
    final matches = trip.schedule
        .where(
          (entry) =>
              entry.generatedBy == ScheduleEntrySource.route &&
              entry.itemKind == ScheduleEntryKind.arrival &&
              entry.routeStepId == stepId,
        )
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '乗車stepの降車予定を一意に特定できません: '
        'stepId=$stepId, matches=${matches.length}',
      );
    }
    final stored = matches.single.plannedAt;
    final fixed = trip.routeStepArrivalAt(stepId);
    if (stored != fixed) {
      debugPrint(
        '[ScheduleIntegrity] ride arrival differs from fixed route clock: '
        'stepId=$stepId stored=$stored fixed=$fixed',
      );
    }
    return fixed;
  }

  ScheduleEntry _knownOnboardRideEntry(Trip trip, String stepId) {
    final step = trip.stepsById[stepId];
    if (step == null) {
      throw StateError('乗車中として記憶したstepがTripにありません: $stepId');
    }
    if (!step.isRide) {
      throw StateError(
        '乗車中として記憶したstepが乗車stepではありません: '
        'stepId=$stepId, kind=${step.kind}',
      );
    }

    final matches = trip.schedule
        .where(
          (entry) =>
              entry.generatedBy == ScheduleEntrySource.route &&
              entry.itemKind == ScheduleEntryKind.ride &&
              entry.routeStepId == stepId,
        )
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '乗車中stepのride予定を一意に特定できません: '
        'stepId=$stepId, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  ReplanTransitPlace _destinationPlace(StepSeg step) {
    if (!step.isRide || step.stops.isEmpty) {
      throw StateError(
        '降車地点を確定できない乗車stepです: '
        'stepId=${step.stepId}, kind=${step.kind}, stops=${step.stops.length}',
      );
    }
    final stop = step.stops.last;
    return ReplanTransitPlace(
      name: stop.name,
      stopId: stop.stopId,
      point: stop.point,
    );
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
    StateNotifierProvider.autoDispose<
      MemberModeController,
      RealtimeTransitState
    >((ref) {
      // Own both progress and polling in the same Trip-scoped session.
      // Watching the notifier restarts only when the session is recreated,
      // not when a position changes.
      ref.watch(memberNavProgressProvider.notifier);
      final controller = MemberModeController(
        ref,
        ref.watch(busLocationSourceProvider),
        ref.watch(trainLocationSourceProvider),
      );
      // Provider/widget creation must finish before a poll can update progress.
      // A disposed instance must never start its timer after deferred startup.
      scheduleMicrotask(() {
        if (controller.mounted) controller._initialize();
      });
      return controller;
    }, dependencies: [tripStreamProvider, memberNavProgressProvider]);

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
final memberUiStateProvider = Provider.autoDispose<AsyncValue<MemberUiState>>(
  (ref) {
    final tripAsync = ref.watch(tripStreamProvider);
    final navProgress = ref.watch(memberNavProgressProvider);
    final realtime = ref.watch(memberModeControllerProvider);
    final nowTick = ref.watch(minuteTickerProvider);

    return tripAsync.whenData((trip) {
      if (trip == null) throw Exception("No Trip");

      final now = nowTick.value ?? appClock.now();

      // Disk restoration can finish between polls. A persisted completion must
      // already be visible without waiting for the next realtime request.
      final completedStepId = realtime.replanTransitMemory.completedRideStepId;
      final completedStep = trip.stepsById[completedStepId];
      final restoredBusCompletion =
          completedStep?.kind == 'bus' &&
              realtime.trackedStepId == completedStepId &&
              navProgress.railProgress == null
          ? completeBusAtDestination(step: completedStep!)
          : null;

      // ルート情報の構築（表示用）
      final routeState = RouteState(
        stepsById: trip.stepsById,
        currentStepId:
            restoredBusCompletion?.stepId ?? navProgress.currentStepId,
        busProgress: restoredBusCompletion ?? navProgress.busProgress,
        railProgress: navProgress.railProgress,
      );

      final resolvedState = TripCoordinator.resolveScheduleState(
        scheduleEntries: _navigationScheduleForTrip(trip),
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
      final displayState = navProgress.rideRealtimeUnavailable
          ? navDisplayState.withNotice(
              statusLabel: navDisplayState.statusLabel,
              noticeText: '📍',
              statusLabelToken: navDisplayState.statusLabelToken,
              noticeTextToken: const NavigationTextToken(
                NavigationTextKey.realtimeUnavailableNotice,
              ),
            )
          : navDisplayState;

      return MemberUiState(
        navState: displayState,
        windowEntries: resolvedState.windowEntries,
        resolvedEntry: resolvedState.resolvedEntry,
        completedCount: resolvedState.completedCount,
        activeLabel: resolvedState.activeLabel,
        displayTitle: trip.displayTitle,
      );
    });
  },
  dependencies: [
    tripStreamProvider,
    memberNavProgressProvider,
    memberModeControllerProvider,
  ],
);

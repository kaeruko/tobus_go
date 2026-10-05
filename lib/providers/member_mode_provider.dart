import 'dart:async';
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

List<ScheduleEntry> _navigationScheduleForTrip(Trip trip) {
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
  final entries = trip.schedule
      .where((entry) => entry.legIndex == activeLegIndex)
      .toList(growable: false);
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

    _checkProgressInFlight = true;
    try {
      await _runProgressCheck(forceRefresh: forceRefresh);
    } finally {
      _checkProgressInFlight = false;
    }
  }

  Future<void> _runProgressCheck({bool forceRefresh = false}) async {
    debugPrint(
      '[MemberModeController] _checkProgress START '
      'forceRefresh=$forceRefresh',
    );

    final trip = _ref.read(tripStreamProvider).valueOrNull;
    if (!mounted) return;
    if (trip == null) {
      debugPrint('[MemberModeController] trip=null');
      return;
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

    // Keep an incomplete realtime ride authoritative after its planned arrival
    // time. Resolving by the clock alone would otherwise jump to a later walk
    // or goal while the vehicle/train is still before the alighting stop.
    final navProgress = _ref.read(memberNavProgressProvider);
    // Reading progress may refresh its Trip identity and replace this session.
    if (!mounted) return;
    final knownBusProgress = state.busProgress ?? navProgress.busProgress;
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

    // Once onboard has been confirmed, a temporary realtime 404 must not let
    // the wall clock advance navigation to a later walk/goal. Keep polling the
    // exact ride until realtime proves arrival (or reports the ride again).
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

    if (activeStep != null &&
        activeStep.kind == 'bus' &&
        activeStep.routeId != null &&
        activeStep.tripId != null) {
      final plannedDepartureAt = _plannedRideDepartureAt(
        trip,
        activeStep.stepId,
      );
      final plannedArrivalAt = _plannedRideArrivalAt(trip, activeStep.stepId);
      await _updateBusProgress(
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

    if (!mounted) return;

    // 進捗を更新 (時間基準 + API補正)
    if (resolvedEntry != null) {
      final progressNotifier = _ref.read(memberNavProgressProvider.notifier);
      if (!mounted) return;
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
  }

  Future<void> _updateBusProgress(
    StepSeg activeStep, {
    required DateTime plannedDepartureAt,
    required DateTime plannedArrivalAt,
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
        boardingStopId: activeStep.departureStopId,
        scheduledDepartureAt: plannedDepartureAt,
        vehicleId: trackedVehicleId,
        forceRefresh: forceRefresh,
      );
      if (!mounted) return;
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
      final assumeArrived = shouldAssumeBusArrivedFromStaleRealtime(
        now: now,
        plannedArrivalAt: plannedArrivalAt,
        progress: realtimeProgress,
        staleAfterSeconds: NavigationState.staleRidePositionAfterSeconds,
      );
      final progress = assumeArrived
          ? assumeBusArrivedAtDestination(
              step: activeStep,
              realtimeProgress: realtimeProgress,
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
        now: now,
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
      if (alightingAlert != null) {
        await _performAlightingAlertHaptic(alightingAlert, step: activeStep);
      }

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
    } on BusLocationNotAvailableException catch (e) {
      if (!mounted) return;
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
        return;
      }

      final now = appClock.now();
      final navProgress = _ref.read(memberNavProgressProvider);
      if (!mounted) return;
      final lastRidingProgress =
          state.busProgress?.stepId == activeStep.stepId
              ? state.busProgress
              : navProgress.busProgress?.stepId == activeStep.stepId
                  ? navProgress.busProgress
                  : null;
      final knownOnboard =
          state.replanTransitMemory.knownOnboardStepId == activeStep.stepId;

      if (e.code == 'bus_trip_not_found' &&
          lastRidingProgress?.phase == BusProgressPhase.riding &&
          shouldAssumeBusArrivedAfterRealtimeLoss(
            now: now,
            plannedArrivalAt: plannedArrivalAt,
            knownOnboard: knownOnboard,
          )) {
        final arrivedProgress = assumeBusArrivedAtDestination(
          step: activeStep,
          realtimeProgress: lastRidingProgress!,
        );
        state = RealtimeTransitState(
          trackedStepId: activeStep.stepId,
          trackedVehicleId: state.trackedStepId == activeStep.stepId
              ? state.trackedVehicleId
              : null,
          busProgress: arrivedProgress,
          replanTransitMemory: state.replanTransitMemory.markArrived(
            _destinationPlace(activeStep),
            confirmedAt: now,
          ),
        );
        debugPrint(
          '[MemberModeController] バスRealtime終了後、予定時刻で降車を確定: '
          'step=${activeStep.stepId} '
          'plannedArrival=${plannedArrivalAt.toIso8601String()} '
          'lastObserved=${lastRidingProgress.observedStopId}/'
          '${lastRidingProgress.observedStopName} '
          'error=$e',
        );
        return;
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
    } catch (e, stackTrace) {
      if (!mounted) return;
      debugPrint('[MemberModeController] バスAPIエラー: $e');
      debugPrintStack(stackTrace: stackTrace);
      rethrow;
    }
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
    return matches.single.plannedAt;
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
    return matches.single.plannedAt;
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

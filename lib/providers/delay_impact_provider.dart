import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../logic/delay_impact_analyzer.dart';
import '../logic/next_ride_delay_adjuster.dart';
import '../logic/next_ride_realtime.dart';
import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/rail_progress.dart';
import '../services/bus_location_source.dart';
import '../services/train_location_source.dart';
import 'member_mode_provider.dart';
import 'minute_ticker_provider.dart';
import 'trip_provider.dart';

/// Current transfer impact derived only from route/realtime facts.
///
/// While riding, realtime predicts the planned alighting time. After the ride
/// is confirmed as arrived, analysis continues from the last confirmed transit
/// place and the current clock while counting the full transfer walk. GPS is
/// never used to claim partial progress through that walk.
final delayImpactProvider = Provider.autoDispose<DelayImpact?>((ref) {
  final tripAsync = ref.watch(tripStreamProvider);
  final uiAsync = ref.watch(memberUiStateProvider);
  final realtime = ref.watch(memberModeControllerProvider);
  final nowTick = ref.watch(minuteTickerProvider);

  if (!tripAsync.hasValue || !uiAsync.hasValue) return null;
  final trip = tripAsync.value;
  final uiState = uiAsync.value;
  if (trip == null || uiState == null) return null;

  final observation = realtime.ridingTransitObservation;
  if (observation != null) {
    if (observation.predictedDestinationAvailableAt == null) return null;
    return DelayImpactAnalyzer.analyze(
      trip: trip,
      observation: observation,
    );
  }

  final activeEntry = uiState.resolvedEntry;
  final confirmedPlace = realtime.lastConfirmedTransitPlace;
  if (activeEntry == null || confirmedPlace == null) return null;
  if (activeEntry.generatedBy != ScheduleEntrySource.route) return null;

  final activeStepId = activeEntry.routeStepId;
  if (activeStepId == null || activeStepId.isEmpty) return null;
  final activeStep = trip.stepsById[activeStepId];
  if (activeStep == null) {
    throw StateError(
      '遅延判定中の予定が存在しないrouteStepIdを参照しています: $activeStepId',
    );
  }

  final busProgress = realtime.busProgress;
  final railProgress = realtime.railProgress;
  if (busProgress != null && railProgress != null) {
    throw StateError('遅延判定中にbus/rail進捗が同時に存在しています');
  }

  final arrivedCurrentRide =
      activeStep.isRide &&
      activeEntry.itemKind == ScheduleEntryKind.arrival &&
      ((busProgress?.stepId == activeStepId &&
              busProgress?.phase == BusProgressPhase.arrived) ||
          (railProgress?.stepId == activeStepId &&
              railProgress?.phase == RailProgressPhase.arrived));

  final approachingNextRide =
      activeStep.isRide &&
      activeEntry.itemKind == ScheduleEntryKind.ride &&
      ((busProgress?.stepId == activeStepId &&
              busProgress?.phase == BusProgressPhase.approaching) ||
          (railProgress?.stepId == activeStepId &&
              railProgress?.phase == RailProgressPhase.approaching));

  // A non-ride route step after alighting is safe to analyze from the last
  // confirmed station/stop. For ride entries, require explicit realtime proof
  // of either the previous arrival or that the next vehicle is still only
  // approaching; a temporary realtime 404 must not be reinterpreted as arrival.
  if (activeStep.isRide && !arrivedCurrentRide && !approachingNextRide) {
    return null;
  }

  final now = nowTick.value ?? appClock.now();
  return DelayImpactAnalyzer.analyzeFromConfirmedTransferPlace(
    trip: trip,
    activeEntry: activeEntry,
    confirmedPlace: confirmedPlace,
    availableAt: now,
  );
}, dependencies: [
  tripStreamProvider,
  memberUiStateProvider,
  memberModeControllerProvider,
]);

/// Realtime estimate for the exact service used by the next planned ride.
///
/// A 404 means that exact service is not currently visible in the feed and is
/// represented as null. Other errors are preserved so the UI can state that it
/// fell back to the scheduled departure instead of silently swallowing them.
final nextRideRealtimeDepartureProvider =
    FutureProvider.autoDispose<NextRideRealtimeDeparture?>((ref) async {
      final base = ref.watch(delayImpactProvider);
      final tripAsync = ref.watch(tripStreamProvider);
      final nowTick = ref.watch(minuteTickerProvider);
      if (base == null || !tripAsync.hasValue) return null;

      final trip = tripAsync.value;
      if (trip == null) return null;
      final step = trip.stepsById[base.nextRideStepId];
      if (step == null) {
        throw StateError(
          '次便Realtime対象のstepがTripにありません: ${base.nextRideStepId}',
        );
      }
      if (!step.isRide) {
        throw StateError(
          '次便Realtime対象が乗車stepではありません: '
          'stepId=${step.stepId}, kind=${step.kind}',
        );
      }

      final now = nowTick.value ?? appClock.now();
      switch (step.kind) {
        case 'bus':
          final routeId = step.routeId?.trim();
          final tripId = step.tripId?.trim();
          if (routeId == null || routeId.isEmpty) {
            throw StateError('次便バスstepにrouteIdがありません: ${step.stepId}');
          }
          if (tripId == null || tripId.isEmpty) {
            throw StateError('次便バスstepにtripIdがありません: ${step.stepId}');
          }
          try {
            final location = await ref.read(busLocationSourceProvider).fetch(
              routeId: routeId,
              tripId: tripId,
              forceRefresh: true,
            );
            return NextRideRealtimeAdapter.fromBus(
              step: step,
              location: location,
              now: now,
            );
          } on BusLocationNotAvailableException {
            return null;
          }
        case 'rail':
          try {
            final location = await ref.read(trainLocationSourceProvider).fetch(
              step: step,
              forceRefresh: true,
            );
            return NextRideRealtimeAdapter.fromRail(
              step: step,
              location: location,
              now: now,
            );
          } on TrainLocationNotAvailableException {
            return null;
          }
        default:
          throw StateError(
            '次便Realtimeの未対応step kindです: ${step.kind}',
          );
      }
    }, dependencies: [
      delayImpactProvider,
      tripStreamProvider,
      busLocationSourceProvider,
      trainLocationSourceProvider,
    ]);

class DelayImpactResolution {
  final DelayImpact? impact;
  final NextRideRealtimeDeparture? nextRideRealtime;
  final DateTime? scheduledNextDepartureAt;
  final bool checkingNextRideRealtime;
  final Object? nextRideRealtimeError;

  const DelayImpactResolution({
    required this.impact,
    this.nextRideRealtime,
    this.scheduledNextDepartureAt,
    this.checkingNextRideRealtime = false,
    this.nextRideRealtimeError,
  });
}

/// UI-ready transfer judgement. Until next-service realtime arrives, the
/// schedule-only judgement remains visible. When exact next-service realtime is
/// available, it replaces only the next departure side of the comparison.
final resolvedDelayImpactProvider =
    Provider.autoDispose<DelayImpactResolution>((ref) {
      final base = ref.watch(delayImpactProvider);
      if (base == null) {
        return const DelayImpactResolution(impact: null);
      }

      final nextAsync = ref.watch(nextRideRealtimeDepartureProvider);
      return nextAsync.when(
        loading: () => DelayImpactResolution(
          impact: base,
          checkingNextRideRealtime: true,
        ),
        error: (error, stack) => DelayImpactResolution(
          impact: base,
          nextRideRealtimeError: error,
        ),
        data: (realtime) {
          if (realtime == null) {
            return DelayImpactResolution(impact: base);
          }
          final adjusted = NextRideDelayAdjuster.apply(
            base: base,
            realtime: realtime,
          );
          return DelayImpactResolution(
            impact: adjusted.impact,
            nextRideRealtime: adjusted.realtime,
            scheduledNextDepartureAt: adjusted.scheduledNextDepartureAt,
          );
        },
      );
    }, dependencies: [
      delayImpactProvider,
      nextRideRealtimeDepartureProvider,
    ]);

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../logic/delay_impact_analyzer.dart';
import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/rail_progress.dart';
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

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../logic/replan_anchor.dart';
import '../logic/replan_anchor_context.dart';
import 'member_mode_provider.dart';
import 'minute_ticker_provider.dart';
import 'replan_transit_persistence_provider.dart';
import 'trip_provider.dart';

/// The non-GPS anchor that can be used for a route replan right now.
///
/// A null value means there is no active route-derived schedule step, persisted
/// transit history is still being restored, the user was confirmed onboard but
/// the current realtime position is temporarily unavailable, or the last
/// moving-vehicle prediction has expired before realtime confirmed the stop.
/// Persisted data never restores an ETA; it only restores route-derived
/// historical facts.
final replanAnchorProvider = Provider.autoDispose<ReplanAnchor?>((ref) {
  final tripAsync = ref.watch(tripStreamProvider);
  final uiAsync = ref.watch(memberUiStateProvider);
  final effectiveMemory = ref.watch(effectiveReplanTransitMemoryProvider);
  final nowTick = ref.watch(minuteTickerProvider);

  if (!tripAsync.hasValue || !uiAsync.hasValue) {
    return null;
  }
  if (effectiveMemory.restoring || effectiveMemory.restoreError != null) {
    return null;
  }

  final trip = tripAsync.value;
  final uiState = uiAsync.value;
  final memory = effectiveMemory.memory;
  if (trip == null || uiState == null || memory == null) {
    return null;
  }

  final activeStepId = uiState.resolvedEntry?.routeStepId;
  if (activeStepId == null) {
    return null;
  }

  if (memory.ridingTransit == null && memory.knownOnboardStepId != null) {
    return null;
  }

  final now = nowTick.value ?? appClock.now();
  final ridingTransit = memory.ridingTransit;
  if (ridingTransit != null && !ridingTransit.canResolveAnchorAt(now)) {
    // The vehicle was still reported in transit when this forecast was made,
    // but its predicted next-stop time has now passed. Do not pretend the next
    // stop was reached, do not coerce ETA to `now`, and do not fall back to GPS
    // or the previously confirmed stop. Wait for the next realtime observation.
    return null;
  }

  final context = ReplanAnchorContextBuilder.build(
    trip: trip,
    activeStepId: activeStepId,
    memory: memory,
  );
  return ReplanAnchorResolver.resolve(context: context, now: now);
}, dependencies: [
  tripStreamProvider,
  memberUiStateProvider,
  memberModeControllerProvider,
  effectiveReplanTransitMemoryProvider,
]);

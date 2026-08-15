import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/delay_impact_analyzer.dart';
import 'member_mode_provider.dart';
import 'trip_provider.dart';

/// Current transfer impact derived from the same non-GPS realtime observation
/// used by replanning. Null means there is no active ride observation, no later
/// transit boarding in the same leg, or realtime does not contain enough data
/// to estimate the planned alighting time. We do not synthesize an ETA in that
/// last case, so the UI never claims a missed connection without evidence.
final delayImpactProvider = Provider.autoDispose<DelayImpact?>((ref) {
  final tripAsync = ref.watch(tripStreamProvider);
  final realtime = ref.watch(memberModeControllerProvider);

  if (!tripAsync.hasValue) return null;
  final trip = tripAsync.value;
  final observation = realtime.ridingTransitObservation;
  if (trip == null || observation == null) return null;
  if (observation.predictedDestinationAvailableAt == null) return null;

  return DelayImpactAnalyzer.analyze(
    trip: trip,
    observation: observation,
  );
}, dependencies: [tripStreamProvider, memberModeControllerProvider]);

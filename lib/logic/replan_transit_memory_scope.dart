import '../models/trip_models.dart';
import 'replan_transit_memory.dart';

/// Keeps historical places across legs, but scopes active rides to this leg.
/// Invalid step references remain errors even when the Trip has ended.
ReplanTransitMemory scopeReplanTransitMemoryToTrip({
  required Trip trip,
  required ReplanTransitMemory memory,
}) {
  final activeStepIds = <String>{
    if (memory.knownOnboardStepId != null) memory.knownOnboardStepId!,
    if (memory.ridingTransit != null) memory.ridingTransit!.stepId,
  };
  var belongsToActiveLeg = true;
  for (final stepId in activeStepIds) {
    final step = trip.stepsById[stepId];
    if (step == null) {
      throw StateError('保存済み乗車stepが現在のTripにありません: $stepId');
    }
    if (!step.isRide) {
      throw StateError(
        '保存済み乗車stepが乗車stepではありません: '
        'stepId=$stepId, kind=${step.kind}',
      );
    }

    final ownerLegIndex = trip.legs.indexWhere(
      (leg) =>
          leg.candidate.steps.any((candidate) => candidate.stepId == stepId),
    );
    if (ownerLegIndex != trip.activeLegIndex) belongsToActiveLeg = false;
  }

  if (trip.travelPhase != TravelPhase.active || !belongsToActiveLeg) {
    return memory.clearActiveRide();
  }
  return memory;
}

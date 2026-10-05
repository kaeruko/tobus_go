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
  int ownerLegIndex(String stepId) {
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

    return trip.legs.indexWhere(
      (leg) =>
          leg.candidate.steps.any((candidate) => candidate.stepId == stepId),
    );
  }

  var activeRideBelongsToLeg = true;
  for (final stepId in activeStepIds) {
    if (ownerLegIndex(stepId) != trip.activeLegIndex) {
      activeRideBelongsToLeg = false;
    }
  }
  final completedStepId = memory.completedRideStepId;
  final completedRideBelongsToLeg =
      completedStepId == null ||
      ownerLegIndex(completedStepId) == trip.activeLegIndex;
  final tripActive = trip.travelPhase == TravelPhase.active;
  final keepActiveRide = tripActive && activeRideBelongsToLeg;
  final keepCompletedRide = tripActive && completedRideBelongsToLeg;
  if (keepActiveRide && keepCompletedRide) return memory;

  return ReplanTransitMemory(
    ridingTransit: keepActiveRide ? memory.ridingTransit : null,
    knownOnboardStepId: keepActiveRide ? memory.knownOnboardStepId : null,
    completedRideStepId: keepCompletedRide ? completedStepId : null,
    lastConfirmedTransitPlace: memory.lastConfirmedTransitPlace,
    lastConfirmedTransitAt: memory.lastConfirmedTransitAt,
  );
}

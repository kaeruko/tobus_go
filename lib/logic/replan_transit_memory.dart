import 'replan_anchor.dart';

/// Keeps only the transit facts that must survive navigation step changes.
///
/// [ridingTransit] is valid only while a bus/train observation is currently
/// usable. [lastConfirmedTransitPlace] survives after alighting so a later walk
/// can still replan from the last station/bus stop without using GPS.
///
/// [knownOnboardStepId] remembers that the user was confirmed onboard even if
/// the realtime feed temporarily disappears. It is cleared only when the ride
/// is known to be approaching/not-yet-boarded, arrived, or the navigation moves
/// to a non-ride step. This prevents a temporary 404 from making the previous
/// station look like an actionable replan origin.
class ReplanTransitMemory {
  final RidingTransitObservation? ridingTransit;
  final ReplanTransitPlace? lastConfirmedTransitPlace;
  final String? knownOnboardStepId;

  const ReplanTransitMemory({
    this.ridingTransit,
    this.lastConfirmedTransitPlace,
    this.knownOnboardStepId,
  });

  ReplanTransitMemory observeRide(RidingTransitObservation observation) {
    final currentPlace = observation.currentPlace;
    if (currentPlace == null) {
      throw StateError(
        '乗車中観測に最後に確定した駅/停留所がありません: '
        'stepId=${observation.stepId}',
      );
    }
    return ReplanTransitMemory(
      ridingTransit: observation,
      lastConfirmedTransitPlace: currentPlace,
      knownOnboardStepId: observation.stepId,
    );
  }

  ReplanTransitMemory markArrived(ReplanTransitPlace destination) {
    return ReplanTransitMemory(lastConfirmedTransitPlace: destination);
  }

  /// Clears active-ride state when boarding has not happened, arrival is known,
  /// or navigation has moved to a non-ride step.
  ReplanTransitMemory clearActiveRide() {
    if (ridingTransit == null && knownOnboardStepId == null) return this;
    return ReplanTransitMemory(
      lastConfirmedTransitPlace: lastConfirmedTransitPlace,
    );
  }

  /// Drops a stale realtime forecast while preserving only an already-confirmed
  /// onboard fact for the same route step.
  ///
  /// A feed miss before any successful onboard observation does not manufacture
  /// an onboard state. Likewise, an onboard marker from another step is not
  /// carried into a newly active ride.
  ReplanTransitMemory markRideRealtimeUnavailable(String stepId) {
    final normalizedStepId = stepId.trim();
    if (normalizedStepId.isEmpty) {
      throw ArgumentError.value(stepId, 'stepId', 'must not be empty');
    }

    final wasKnownOnboardForStep =
        ridingTransit?.stepId == normalizedStepId ||
        knownOnboardStepId == normalizedStepId;

    return ReplanTransitMemory(
      lastConfirmedTransitPlace: lastConfirmedTransitPlace,
      knownOnboardStepId: wasKnownOnboardForStep ? normalizedStepId : null,
    );
  }

  bool isKnownOnboardWithoutRealtime(String stepId) {
    final normalizedStepId = stepId.trim();
    if (normalizedStepId.isEmpty) {
      throw ArgumentError.value(stepId, 'stepId', 'must not be empty');
    }
    return ridingTransit == null && knownOnboardStepId == normalizedStepId;
  }
}

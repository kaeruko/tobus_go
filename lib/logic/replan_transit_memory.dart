import 'replan_anchor.dart';

/// Keeps only the transit facts that must survive navigation step changes.
///
/// [ridingTransit] is valid only while a bus/train observation is currently
/// usable. [lastConfirmedTransitPlace] survives after alighting so a later walk
/// can still replan from the last station/bus stop without using GPS.
class ReplanTransitMemory {
  final RidingTransitObservation? ridingTransit;
  final ReplanTransitPlace? lastConfirmedTransitPlace;

  const ReplanTransitMemory({
    this.ridingTransit,
    this.lastConfirmedTransitPlace,
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
    );
  }

  ReplanTransitMemory markArrived(ReplanTransitPlace destination) {
    return ReplanTransitMemory(lastConfirmedTransitPlace: destination);
  }

  ReplanTransitMemory clearActiveRide() {
    if (ridingTransit == null) return this;
    return ReplanTransitMemory(
      lastConfirmedTransitPlace: lastConfirmedTransitPlace,
    );
  }
}

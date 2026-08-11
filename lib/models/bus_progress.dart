import 'route_models.dart';

/// A bus position expressed relative to one route step.
///
/// [fromStopIndex] is the stop the vehicle has most recently departed from.
/// [nextStopIndex] is therefore either `fromStopIndex + 1` or null at the
/// destination.
class BusProgress {
  final String stepId;
  final String fromStopId;
  final int fromStopIndex;
  final String? nextStopId;
  final int? nextStopIndex;

  const BusProgress({
    required this.stepId,
    required this.fromStopId,
    required this.fromStopIndex,
    required this.nextStopId,
    required this.nextStopIndex,
  });

  factory BusProgress.forStep({
    required StepSeg step,
    required String fromStopId,
  }) {
    final fromIndex = step.stops.indexWhere(
      (stop) => stop.stopId == fromStopId,
    );
    if (fromIndex == -1) {
      throw StateError('バス位置が経路外です: stepId=${step.stepId}, stopId=$fromStopId');
    }

    final nextIndex = fromIndex + 1 < step.stops.length ? fromIndex + 1 : null;
    return BusProgress(
      stepId: step.stepId,
      fromStopId: fromStopId,
      fromStopIndex: fromIndex,
      nextStopId: nextIndex == null ? null : step.stops[nextIndex].stopId,
      nextStopIndex: nextIndex,
    );
  }
}

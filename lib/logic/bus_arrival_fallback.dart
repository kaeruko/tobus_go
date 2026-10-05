import '../models/bus_progress.dart';
import '../models/route_models.dart';

/// Bus navigation follows its schedule even when ODPT reports an older stop.
bool shouldCompleteBusFromSchedule({
  required DateTime now,
  required DateTime plannedArrivalAt,
}) {
  return !now.isBefore(plannedArrivalAt);
}

/// A missing realtime trip is retried only while the schedule says the rider
/// should currently be on the bus. The schedule remains the progress truth.
bool shouldRetryMissingBusRealtime({
  required DateTime now,
  required DateTime plannedDepartureAt,
  required DateTime plannedArrivalAt,
}) {
  if (!plannedDepartureAt.isBefore(plannedArrivalAt)) {
    throw ArgumentError.value(
      plannedArrivalAt,
      'plannedArrivalAt',
      'must be after plannedDepartureAt',
    );
  }
  return !now.isBefore(plannedDepartureAt) && now.isBefore(plannedArrivalAt);
}

/// Builds completion without manufacturing a realtime observation.
BusProgress completeBusAtDestination({
  required StepSeg step,
  BusProgress? lastProgress,
}) {
  if (step.kind != 'bus') {
    throw StateError(
      'bus以外のstepを降車扱いにできません: '
      'stepId=${step.stepId}, kind=${step.kind}',
    );
  }
  if (step.stops.isEmpty) {
    throw StateError('停留所のないバスStepを降車扱いにできません: ${step.stepId}');
  }
  if (lastProgress != null && lastProgress.stepId != step.stepId) {
    throw StateError(
      'BusProgressのstepIdが一致しません: '
      '${lastProgress.stepId} != ${step.stepId}',
    );
  }

  final destinationIndex = step.stops.length - 1;
  return BusProgress(
    stepId: step.stepId,
    fromStopId: step.stops[destinationIndex].stopId,
    fromStopIndex: destinationIndex,
    nextStopId: null,
    nextStopIndex: null,
    phase: BusProgressPhase.arrived,
    observedStopId: lastProgress?.observedStopId,
    observedStopName: lastProgress?.observedStopName,
    observedStopNameEn: lastProgress?.observedStopNameEn,
    currentStatus: lastProgress?.currentStatus,
    vehicleAgeSeconds: lastProgress?.vehicleAgeSeconds,
  );
}

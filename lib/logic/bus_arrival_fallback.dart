import '../models/bus_progress.dart';
import '../models/route_models.dart';

/// Bus navigation follows its schedule even when ODPT reports an older stop.
bool shouldCompleteBusFromSchedule({
  required DateTime now,
  required DateTime plannedArrivalAt,
}) {
  return !now.isBefore(plannedArrivalAt);
}

bool shouldAssumeBusArrivedAfterRealtimeLoss({
  required DateTime now,
  required DateTime plannedArrivalAt,
  required bool hasSeenVehicle,
}) {
  // An initial feed miss has no disappearance evidence. In that case the
  // schedule decides; an already tracked service disappearing ends the ride.
  return hasSeenVehicle ||
      shouldCompleteBusFromSchedule(
        now: now,
        plannedArrivalAt: plannedArrivalAt,
      );
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

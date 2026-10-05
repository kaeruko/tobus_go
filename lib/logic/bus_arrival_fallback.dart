import '../models/bus_progress.dart';
import '../models/route_models.dart';

bool shouldAssumeBusArrivedFromStaleRealtime({
  required DateTime now,
  required DateTime plannedArrivalAt,
  required BusProgress progress,
  required double staleAfterSeconds,
}) {
  if (!staleAfterSeconds.isFinite || staleAfterSeconds <= 0) {
    throw ArgumentError.value(
      staleAfterSeconds,
      'staleAfterSeconds',
      'must be finite and greater than zero',
    );
  }
  if (progress.phase != BusProgressPhase.riding) return false;

  final vehicleAgeSeconds = progress.vehicleAgeSeconds;
  if (vehicleAgeSeconds == null) return false;
  if (!vehicleAgeSeconds.isFinite || vehicleAgeSeconds < 0) {
    throw StateError(
      'vehicleAgeSeconds must be finite and non-negative: $vehicleAgeSeconds',
    );
  }

  return !now.isBefore(plannedArrivalAt) &&
      vehicleAgeSeconds >= staleAfterSeconds;
}

bool shouldAssumeBusArrivedAfterRealtimeLoss({
  required DateTime now,
  required DateTime plannedArrivalAt,
  required bool knownOnboard,
}) {
  return knownOnboard && !now.isBefore(plannedArrivalAt);
}

BusProgress assumeBusArrivedAtDestination({
  required StepSeg step,
  required BusProgress realtimeProgress,
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
  if (realtimeProgress.stepId != step.stepId) {
    throw StateError(
      'BusProgressのstepIdが一致しません: '
      '${realtimeProgress.stepId} != ${step.stepId}',
    );
  }
  if (realtimeProgress.phase != BusProgressPhase.riding) {
    throw StateError(
      '乗車中ではないBusProgressを予定時刻で降車扱いにできません: '
      'stepId=${step.stepId}, phase=${realtimeProgress.phase.name}',
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
    observedStopId: realtimeProgress.observedStopId,
    observedStopName: realtimeProgress.observedStopName,
    observedStopNameEn: realtimeProgress.observedStopNameEn,
    currentStatus: realtimeProgress.currentStatus,
    vehicleAgeSeconds: realtimeProgress.vehicleAgeSeconds,
  );
}

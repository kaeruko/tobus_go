import 'route_models.dart';

enum BusProgressPhase { approaching, riding, arrived }

/// A bus position expressed relative to one route step.
///
/// [fromStopIndex] is null while the vehicle is still approaching the
/// boarding stop. During the ride it is the stop most recently departed from.
class BusProgress {
  final String stepId;
  final String? fromStopId;
  final int? fromStopIndex;
  final String? nextStopId;
  final int? nextStopIndex;
  final int? stopsUntilBoarding;
  final BusProgressPhase phase;
  final String? observedStopId;
  final String? observedStopName;
  final String? currentStatus;
  final double? vehicleAgeSeconds;

  const BusProgress({
    required this.stepId,
    required this.fromStopId,
    required this.fromStopIndex,
    required this.nextStopId,
    required this.nextStopIndex,
    this.stopsUntilBoarding,
    required this.phase,
    this.observedStopId,
    this.observedStopName,
    this.currentStatus,
    this.vehicleAgeSeconds,
  });

  factory BusProgress.forStep({
    required StepSeg step,
    required String? fromStopId,
    bool beforeFirstStop = false,
    List<String> tripStopIds = const [],
    String? observedStopId,
    String? observedStopName,
    String? currentStatus,
    double? vehicleAgeSeconds,
  }) {
    if (step.stops.isEmpty) {
      throw StateError('停留所のないバスStepです: stepId=${step.stepId}');
    }

    final boardingStopId = step.stops.first.stopId;
    final status = currentStatus?.trim();
    final inferredBeforeFirstStop =
        fromStopId == null &&
        const {'INCOMING_AT', 'IN_TRANSIT_TO', '0', '2'}.contains(status);
    final isBeforeFirstStop = beforeFirstStop || inferredBeforeFirstStop;

    if (isBeforeFirstStop) {
      if (fromStopId != null) {
        throw StateError(
          '始発前のバス位置に直前停留所があります: '
          'stepId=${step.stepId}, stopId=$fromStopId',
        );
      }
      return BusProgress(
        stepId: step.stepId,
        fromStopId: null,
        fromStopIndex: null,
        nextStopId: boardingStopId,
        nextStopIndex: 0,
        stopsUntilBoarding: null,
        phase: BusProgressPhase.approaching,
        observedStopId: observedStopId,
        observedStopName: observedStopName,
        currentStatus: currentStatus,
        vehicleAgeSeconds: vehicleAgeSeconds,
      );
    }

    if (fromStopId == null || fromStopId.isEmpty) {
      throw StateError(
        '始発前ではないバス位置に直前停留所がありません: stepId=${step.stepId}',
      );
    }

    final fromIndex = step.stops.indexWhere(
      (stop) => stop.stopId == fromStopId,
    );
    if (fromIndex >= 0) {
      final isDestination = fromIndex == step.stops.length - 1;
      final nextIndex = isDestination ? null : fromIndex + 1;
      return BusProgress(
        stepId: step.stepId,
        fromStopId: fromStopId,
        fromStopIndex: fromIndex,
        nextStopId: nextIndex == null ? null : step.stops[nextIndex].stopId,
        nextStopIndex: nextIndex,
        phase: isDestination
            ? BusProgressPhase.arrived
            : BusProgressPhase.riding,
        observedStopId: observedStopId,
        observedStopName: observedStopName,
        currentStatus: currentStatus,
        vehicleAgeSeconds: vehicleAgeSeconds,
      );
    }

    final destinationStopId = step.stops.last.stopId;
    final observedTripIndex = tripStopIds.indexOf(fromStopId);
    final boardingTripIndex = tripStopIds.indexOf(boardingStopId ?? '');
    final destinationTripIndex = tripStopIds.indexOf(destinationStopId ?? '');

    if (observedTripIndex >= 0 &&
        boardingTripIndex >= 0 &&
        destinationTripIndex >= boardingTripIndex) {
      if (observedTripIndex < boardingTripIndex) {
        return BusProgress(
          stepId: step.stepId,
          fromStopId: fromStopId,
          fromStopIndex: null,
          nextStopId: boardingStopId,
          nextStopIndex: 0,
          stopsUntilBoarding: boardingTripIndex - observedTripIndex,
          phase: BusProgressPhase.approaching,
          observedStopId: observedStopId,
          observedStopName: observedStopName,
          currentStatus: currentStatus,
          vehicleAgeSeconds: vehicleAgeSeconds,
        );
      }
      if (observedTripIndex > destinationTripIndex) {
        final destinationIndex = step.stops.length - 1;
        return BusProgress(
          stepId: step.stepId,
          fromStopId: fromStopId,
          fromStopIndex: destinationIndex,
          nextStopId: null,
          nextStopIndex: null,
          phase: BusProgressPhase.arrived,
          observedStopId: observedStopId,
          observedStopName: observedStopName,
          currentStatus: currentStatus,
          vehicleAgeSeconds: vehicleAgeSeconds,
        );
      }
    }

    throw StateError(
      'バス位置を乗車区間に対応付けできません: '
      'stepId=${step.stepId}, stopId=$fromStopId',
    );
  }
}

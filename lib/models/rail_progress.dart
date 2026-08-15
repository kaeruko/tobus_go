import '../services/train_location_source.dart';


enum RailProgressPhase { approaching, riding, arrived }


class RailProgress {
  final String stepId;
  final String tripId;
  final RailProgressPhase phase;
  final int boardingSequence;
  final int destinationSequence;
  final int lastReachedSequence;
  final int remainingStops;
  final int? stopsUntilBoarding;
  final String? currentStopName;
  final String? nextStopName;
  final String currentStatus;
  final double? vehicleAgeSeconds;

  const RailProgress({
    required this.stepId,
    required this.tripId,
    required this.phase,
    required this.boardingSequence,
    required this.destinationSequence,
    required this.lastReachedSequence,
    required this.remainingStops,
    this.stopsUntilBoarding,
    this.currentStopName,
    this.nextStopName,
    required this.currentStatus,
    this.vehicleAgeSeconds,
  });

  factory RailProgress.forLocation({
    required String stepId,
    required TrainLocation location,
  }) {
    if (stepId.isEmpty) {
      throw ArgumentError.value(stepId, 'stepId', 'must not be empty');
    }

    late final int lastReachedSequence;
    if (location.currentStatus == 'STOPPED_AT') {
      lastReachedSequence = location.currentStopSequence;
    } else if (location.currentStatus == 'IN_TRANSIT_TO' ||
        location.currentStatus == 'INCOMING_AT') {
      lastReachedSequence = location.currentStopSequence - 1;
    } else {
      throw StateError(
        '未対応の列車current_statusです: ${location.currentStatus}',
      );
    }

    if (lastReachedSequence < 0) {
      throw StateError(
        '列車の最終到達sequenceが負です: '
        'observed=${location.currentStopSequence}, status=${location.currentStatus}',
      );
    }

    final stopBySequence = {
      for (final stop in location.tripStops) stop.sequence: stop,
    };
    if (!stopBySequence.containsKey(location.boardingSequence)) {
      throw StateError(
        '列車の乗車sequenceがtrip_stopsにありません: '
        '${location.boardingSequence}',
      );
    }
    if (!stopBySequence.containsKey(location.destinationSequence)) {
      throw StateError(
        '列車の降車sequenceがtrip_stopsにありません: '
        '${location.destinationSequence}',
      );
    }

    if (lastReachedSequence < location.boardingSequence) {
      final stopsUntilBoarding =
          location.boardingSequence - lastReachedSequence;
      return RailProgress(
        stepId: stepId,
        tripId: location.tripId,
        phase: RailProgressPhase.approaching,
        boardingSequence: location.boardingSequence,
        destinationSequence: location.destinationSequence,
        lastReachedSequence: lastReachedSequence,
        remainingStops: location.destinationSequence - lastReachedSequence,
        stopsUntilBoarding: stopsUntilBoarding,
        currentStopName: stopBySequence[lastReachedSequence]?.stopName,
        nextStopName: stopBySequence[location.boardingSequence]?.stopName,
        currentStatus: location.currentStatus,
        vehicleAgeSeconds: location.vehicleAgeSeconds,
      );
    }

    if (lastReachedSequence >= location.destinationSequence) {
      return RailProgress(
        stepId: stepId,
        tripId: location.tripId,
        phase: RailProgressPhase.arrived,
        boardingSequence: location.boardingSequence,
        destinationSequence: location.destinationSequence,
        lastReachedSequence: lastReachedSequence,
        remainingStops: 0,
        currentStopName:
            stopBySequence[location.destinationSequence]?.stopName,
        currentStatus: location.currentStatus,
        vehicleAgeSeconds: location.vehicleAgeSeconds,
      );
    }

    final remaining = location.destinationSequence - lastReachedSequence;
    final nextSequence = location.currentStatus == 'STOPPED_AT'
        ? lastReachedSequence + 1
        : location.currentStopSequence;
    return RailProgress(
      stepId: stepId,
      tripId: location.tripId,
      phase: RailProgressPhase.riding,
      boardingSequence: location.boardingSequence,
      destinationSequence: location.destinationSequence,
      lastReachedSequence: lastReachedSequence,
      remainingStops: remaining,
      currentStopName: stopBySequence[lastReachedSequence]?.stopName,
      nextStopName: stopBySequence[nextSequence]?.stopName,
      currentStatus: location.currentStatus,
      vehicleAgeSeconds: location.vehicleAgeSeconds,
    );
  }
}

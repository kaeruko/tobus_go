import '../services/train_location_source.dart';


enum RailProgressPhase { approaching, riding, arrived }


class RailProgress {
  final String stepId;
  final String tripId;
  final String tripHeadsign;
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
    required this.tripHeadsign,
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

    final tripStops = location.tripStops;
    if (tripStops.isEmpty) {
      throw StateError('列車のtrip_stopsが空です: trip=${location.tripId}');
    }

    // GTFS stop_sequence is an ordering key, not a station count. Values may
    // skip numbers, so all progress/count calculations below use the ordered
    // tripStops index. The original sequence is retained only for diagnostics
    // and exact lookup by other realtime adapters.
    for (var index = 1; index < tripStops.length; index++) {
      final previous = tripStops[index - 1].sequence;
      final current = tripStops[index].sequence;
      if (current <= previous) {
        throw StateError(
          '列車のtrip_stopsがstop_sequence昇順ではありません: '
          'trip=${location.tripId}, index=$index, $previous->$current',
        );
      }
    }

    int requiredIndex(int sequence, String label) {
      final matches = <int>[];
      for (var index = 0; index < tripStops.length; index++) {
        if (tripStops[index].sequence == sequence) {
          matches.add(index);
        }
      }
      if (matches.length != 1) {
        throw StateError(
          '列車の$label sequenceをtrip_stopsで一意に特定できません: '
          'trip=${location.tripId}, sequence=$sequence, matches=${matches.length}',
        );
      }
      return matches.single;
    }

    final currentIndex = requiredIndex(
      location.currentStopSequence,
      'current_stop',
    );
    final boardingIndex = requiredIndex(
      location.boardingSequence,
      'boarding',
    );
    final destinationIndex = requiredIndex(
      location.destinationSequence,
      'destination',
    );
    if (destinationIndex <= boardingIndex) {
      throw StateError(
        '列車の乗車・降車順がtrip_stops上で不正です: '
        'trip=${location.tripId}, boardingIndex=$boardingIndex, '
        'destinationIndex=$destinationIndex',
      );
    }

    late final int lastReachedIndex;
    if (location.currentStatus == 'STOPPED_AT') {
      lastReachedIndex = currentIndex;
    } else if (location.currentStatus == 'IN_TRANSIT_TO' ||
        location.currentStatus == 'INCOMING_AT') {
      lastReachedIndex = currentIndex - 1;
    } else {
      throw StateError(
        '未対応の列車current_statusです: ${location.currentStatus}',
      );
    }

    // Before the first trip stop there is no real last-reached sequence. Keep a
    // synthetic value only for the existing diagnostic field; station counts
    // never use arithmetic on it.
    final lastReachedSequence = lastReachedIndex >= 0
        ? tripStops[lastReachedIndex].sequence
        : location.currentStopSequence - 1;

    if (lastReachedIndex < boardingIndex) {
      final stopsUntilBoarding = boardingIndex - lastReachedIndex;
      return RailProgress(
        stepId: stepId,
        tripId: location.tripId,
        tripHeadsign: location.tripHeadsign,
        phase: RailProgressPhase.approaching,
        boardingSequence: location.boardingSequence,
        destinationSequence: location.destinationSequence,
        lastReachedSequence: lastReachedSequence,
        remainingStops: destinationIndex - lastReachedIndex,
        stopsUntilBoarding: stopsUntilBoarding,
        currentStopName: lastReachedIndex >= 0
            ? tripStops[lastReachedIndex].stopName
            : null,
        nextStopName: tripStops[boardingIndex].stopName,
        currentStatus: location.currentStatus,
        vehicleAgeSeconds: location.vehicleAgeSeconds,
      );
    }

    if (lastReachedIndex >= destinationIndex) {
      return RailProgress(
        stepId: stepId,
        tripId: location.tripId,
        tripHeadsign: location.tripHeadsign,
        phase: RailProgressPhase.arrived,
        boardingSequence: location.boardingSequence,
        destinationSequence: location.destinationSequence,
        lastReachedSequence: lastReachedSequence,
        remainingStops: 0,
        currentStopName: tripStops[destinationIndex].stopName,
        currentStatus: location.currentStatus,
        vehicleAgeSeconds: location.vehicleAgeSeconds,
      );
    }

    final nextStopIndex = location.currentStatus == 'STOPPED_AT'
        ? lastReachedIndex + 1
        : currentIndex;
    if (nextStopIndex < 0 || nextStopIndex >= tripStops.length) {
      throw StateError(
        '列車の次駅indexがtrip_stops範囲外です: '
        'trip=${location.tripId}, nextStopIndex=$nextStopIndex, '
        'stops=${tripStops.length}',
      );
    }

    return RailProgress(
      stepId: stepId,
      tripId: location.tripId,
      tripHeadsign: location.tripHeadsign,
      phase: RailProgressPhase.riding,
      boardingSequence: location.boardingSequence,
      destinationSequence: location.destinationSequence,
      lastReachedSequence: lastReachedSequence,
      remainingStops: destinationIndex - lastReachedIndex,
      currentStopName: tripStops[lastReachedIndex].stopName,
      nextStopName: tripStops[nextStopIndex].stopName,
      currentStatus: location.currentStatus,
      vehicleAgeSeconds: location.vehicleAgeSeconds,
    );
  }
}

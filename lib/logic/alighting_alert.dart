import '../models/route_models.dart';
import '../services/bus_location_source.dart';

enum AlightingAlert { twoStopsBefore, nextStop }

/// Emits at most two alighting alerts for one bus ride:
/// two stops before the planned alighting stop, then one stop before.
///
/// Stop matching is performed against the ordered GTFS trip schedule rather
/// than by stop name. This keeps repeated stop IDs on loop-like routes
/// distinguishable by their occurrence in the trip.
class AlightingAlertTracker {
  final Set<String> _emitted = <String>{};
  final Map<String, int> _closestRemainingStops = <String, int>{};

  AlightingAlert? evaluate({
    required StepSeg step,
    required BusLocation location,
  }) {
    if (step.kind != 'bus') {
      throw StateError(
        '降車通知はbus stepだけです: stepId=${step.stepId}, kind=${step.kind}',
      );
    }

    final routeId = step.routeId?.trim();
    final tripId = step.tripId?.trim();
    if (routeId == null || routeId.isEmpty) {
      throw StateError('降車通知対象のbus stepにrouteIdがありません: ${step.stepId}');
    }
    if (tripId == null || tripId.isEmpty) {
      throw StateError('降車通知対象のbus stepにtripIdがありません: ${step.stepId}');
    }
    if (location.routeId != routeId || location.tripId != tripId) {
      throw StateError(
        '降車通知のRealtimeが経路と一致しません: '
        'expected=$routeId/$tripId, '
        'actual=${location.routeId}/${location.tripId}',
      );
    }
    if (step.stops.length < 2) {
      throw StateError(
        '降車通知対象のbus stepに乗車・降車停留所がありません: '
        'stepId=${step.stepId}, stops=${step.stops.length}',
      );
    }

    if (location.beforeFirstStop) {
      return null;
    }

    final currentSequence = location.fromStopSequence;
    if (currentSequence == null || currentSequence <= 0) {
      throw StateError(
        '降車通知に必要なfrom_stop_sequenceがありません: '
        'stepId=${step.stepId}, value=$currentSequence',
      );
    }

    final schedule = location.tripStopSchedule;
    if (schedule.isEmpty) {
      throw StateError(
        '降車通知に必要なtrip_stop_scheduleがありません: '
        'stepId=${step.stepId}, tripId=$tripId',
      );
    }

    for (var index = 1; index < schedule.length; index++) {
      if (schedule[index].sequence <= schedule[index - 1].sequence) {
        throw StateError(
          'trip_stop_scheduleのsequenceが昇順ではありません: '
          'tripId=$tripId, '
          '${schedule[index - 1].sequence} -> ${schedule[index].sequence}',
        );
      }
    }

    final mappedScheduleIndexes = <int>[];
    var searchStart = 0;
    for (final routeStop in step.stops) {
      final stopId = routeStop.stopId?.trim();
      if (stopId == null || stopId.isEmpty) {
        throw StateError(
          '降車通知対象のroute stopにstopIdがありません: '
          'stepId=${step.stepId}, stop=${routeStop.name}',
        );
      }

      var matchedIndex = -1;
      for (var index = searchStart; index < schedule.length; index++) {
        if (schedule[index].stopId == stopId) {
          matchedIndex = index;
          break;
        }
      }
      if (matchedIndex < 0) {
        throw StateError(
          'route stopをGTFS便の停留所列へ対応付けできません: '
          'stepId=${step.stepId}, stopId=$stopId, '
          'searchStart=$searchStart',
        );
      }

      mappedScheduleIndexes.add(matchedIndex);
      searchStart = matchedIndex + 1;
    }

    final boardingIndex = mappedScheduleIndexes.first;
    final destinationIndex = mappedScheduleIndexes.last;
    if (destinationIndex <= boardingIndex) {
      throw StateError(
        '降車停留所が乗車停留所より後にありません: '
        'stepId=${step.stepId}, boardingIndex=$boardingIndex, '
        'destinationIndex=$destinationIndex',
      );
    }

    final currentMatches = <int>[];
    for (var index = 0; index < schedule.length; index++) {
      if (schedule[index].sequence == currentSequence) {
        currentMatches.add(index);
      }
    }
    if (currentMatches.length != 1) {
      throw StateError(
        'from_stop_sequenceをGTFS便で一意に特定できません: '
        'tripId=$tripId, sequence=$currentSequence, '
        'matches=${currentMatches.length}',
      );
    }

    final currentIndex = currentMatches.single;
    if (currentIndex < boardingIndex || currentIndex >= destinationIndex) {
      return null;
    }

    final remainingStops = destinationIndex - currentIndex;
    final trackingKey = '${step.stepId}|$tripId';
    final closestSeen = _closestRemainingStops[trackingKey];

    // Realtime samples can arrive out of order. Once a nearer stop has been
    // observed, never emit an older "two stops before" alert afterwards.
    if (closestSeen != null && remainingStops > closestSeen) {
      return null;
    }
    if (closestSeen == null || remainingStops < closestSeen) {
      _closestRemainingStops[trackingKey] = remainingStops;
    }

    final alert = switch (remainingStops) {
      2 => AlightingAlert.twoStopsBefore,
      1 => AlightingAlert.nextStop,
      _ => null,
    };
    if (alert == null) {
      return null;
    }

    final emittedKey = '$trackingKey:$remainingStops';
    if (!_emitted.add(emittedKey)) {
      return null;
    }
    return alert;
  }
}

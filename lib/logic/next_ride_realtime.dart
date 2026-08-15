import '../models/route_models.dart';
import '../services/bus_location_source.dart';
import '../services/train_location_source.dart';

enum NextRideRealtimeDepartureStatus {
  predicted,
  atBoardingPlace,
  passedBoardingPlace,
}

class NextRideRealtimeDeparture {
  final String stepId;
  final String boardingPlaceName;
  final NextRideRealtimeDepartureStatus status;
  final DateTime observedAt;
  final DateTime? predictedDepartureAt;

  NextRideRealtimeDeparture({
    required String stepId,
    required String boardingPlaceName,
    required this.status,
    required this.observedAt,
    this.predictedDepartureAt,
  })  : stepId = stepId.trim(),
        boardingPlaceName = boardingPlaceName.trim() {
    if (this.stepId.isEmpty) {
      throw ArgumentError.value(stepId, 'stepId', 'must not be empty');
    }
    if (this.boardingPlaceName.isEmpty) {
      throw ArgumentError.value(
        boardingPlaceName,
        'boardingPlaceName',
        'must not be empty',
      );
    }
    if (status == NextRideRealtimeDepartureStatus.predicted &&
        predictedDepartureAt == null) {
      throw ArgumentError(
        'predicted status requires predictedDepartureAt',
      );
    }
    if (status != NextRideRealtimeDepartureStatus.predicted &&
        predictedDepartureAt != null) {
      throw ArgumentError(
        '$status must not contain predictedDepartureAt',
      );
    }
    if (predictedDepartureAt != null &&
        predictedDepartureAt!.isBefore(observedAt)) {
      throw ArgumentError(
        'predictedDepartureAt must not be before observedAt',
      );
    }
  }

  DateTime? get effectiveDepartureAt {
    switch (status) {
      case NextRideRealtimeDepartureStatus.predicted:
        return predictedDepartureAt!;
      case NextRideRealtimeDepartureStatus.atBoardingPlace:
        return observedAt;
      case NextRideRealtimeDepartureStatus.passedBoardingPlace:
        return null;
    }
  }
}

/// Converts the vehicle position of the *next planned ride* into an estimate of
/// when that exact service reaches/departs the planned boarding place.
///
/// This is deliberately separate from the currently-riding observation. It
/// never substitutes a different service and never uses GPS. When the vehicle
/// is still before the boarding place, the estimate is conservative:
///
///   latest vehicle sample + full scheduled remaining running time
///
/// If the exact service is not present in realtime, callers should keep the
/// schedule-only transfer judgement rather than inventing a delay.
class NextRideRealtimeAdapter {
  static const double staleAfterSeconds = 90;

  const NextRideRealtimeAdapter._();

  static NextRideRealtimeDeparture fromBus({
    required StepSeg step,
    required BusLocation location,
    required DateTime now,
  }) {
    if (step.kind != 'bus') {
      throw StateError(
        '次便バスRealtimeはbus stepだけです: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }
    final routeId = step.routeId?.trim();
    final tripId = step.tripId?.trim();
    if (routeId == null || routeId.isEmpty) {
      throw StateError('次便バスstepにrouteIdがありません: ${step.stepId}');
    }
    if (tripId == null || tripId.isEmpty) {
      throw StateError('次便バスstepにtripIdがありません: ${step.stepId}');
    }
    if (location.routeId != routeId || location.tripId != tripId) {
      throw StateError(
        '次便バスRealtimeが経路と一致しません: '
        'expected=$routeId/$tripId, '
        'actual=${location.routeId}/${location.tripId}',
      );
    }

    final sampleAt = _vehicleSampleAt(
      vehicleTimestamp: location.vehicleTimestamp,
      vehicleAgeSeconds: location.vehicleAgeSeconds,
      now: now,
      transport: 'bus',
      stepId: step.stepId,
    );
    final boarding = _busBoardingSchedule(step, location);
    final status = _requiredStatus(
      location.currentStatus,
      transport: 'bus',
      stepId: step.stepId,
    );

    if (status == 'STOPPED_AT') {
      final current = _busScheduleAt(
        location,
        _requiredSequence(
          location.fromStopSequence,
          label: 'from_stop_sequence',
          stepId: step.stepId,
        ),
      );
      if (current.sequence > boarding.sequence) {
        return _passed(step, boarding.stopName, sampleAt);
      }
      if (current.sequence == boarding.sequence) {
        return _atBoarding(step, boarding.stopName, sampleAt);
      }
      return _predictedBusDeparture(
        step: step,
        from: current,
        boarding: boarding,
        sampleAt: sampleAt,
      );
    }

    if (status != 'IN_TRANSIT_TO' && status != 'INCOMING_AT') {
      throw StateError('次便判定で未対応のバスcurrent_statusです: $status');
    }

    final fromSequence = _requiredSequence(
      location.fromStopSequence,
      label: 'from_stop_sequence',
      stepId: step.stepId,
    );
    final observedSequence = _requiredSequence(
      location.observedStopSequence,
      label: 'observed_stop_sequence',
      stepId: step.stepId,
    );
    if (observedSequence <= fromSequence) {
      throw StateError(
        '次便バスのsequenceが前進していません: '
        '$fromSequence -> $observedSequence',
      );
    }

    final from = _busScheduleAt(location, fromSequence);
    final observed = _busScheduleAt(location, observedSequence);
    if (boarding.sequence <= from.sequence ||
        boarding.sequence < observed.sequence) {
      return _passed(step, boarding.stopName, sampleAt);
    }

    return _predictedBusDeparture(
      step: step,
      from: from,
      boarding: boarding,
      sampleAt: sampleAt,
    );
  }

  static NextRideRealtimeDeparture fromRail({
    required StepSeg step,
    required TrainLocation location,
    required DateTime now,
  }) {
    if (step.kind != 'rail') {
      throw StateError(
        '次便鉄道Realtimeはrail stepだけです: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }

    final sampleAt = _vehicleSampleAt(
      vehicleTimestamp: location.vehicleTimestamp,
      vehicleAgeSeconds: location.vehicleAgeSeconds,
      now: now,
      transport: 'rail',
      stepId: step.stepId,
    );
    _validateTrainStopOrder(location);

    final boarding = _trainStopAt(location, location.boardingSequence);
    final boardingIndex = _trainStopIndex(location, boarding.sequence);
    _validateRailBoardingPlace(step, boarding);
    final currentIndex = _trainStopIndex(
      location,
      location.currentStopSequence,
    );
    final status = _requiredStatus(
      location.currentStatus,
      transport: 'rail',
      stepId: step.stepId,
    );

    if (status == 'STOPPED_AT') {
      if (currentIndex > boardingIndex) {
        return _passed(step, boarding.stopName, sampleAt);
      }
      if (currentIndex == boardingIndex) {
        return _atBoarding(step, boarding.stopName, sampleAt);
      }
      final current = location.tripStops[currentIndex];
      return _predictedRailDeparture(
        step: step,
        from: current,
        boarding: boarding,
        sampleAt: sampleAt,
      );
    }

    if (status != 'IN_TRANSIT_TO' && status != 'INCOMING_AT') {
      throw StateError('次便判定で未対応の列車current_statusです: $status');
    }
    if (currentIndex == 0) {
      throw StateError(
        '走行中列車の直前駅を特定できません: '
        'stepId=${step.stepId}, currentSequence=${location.currentStopSequence}',
      );
    }

    final previousIndex = currentIndex - 1;
    if (boardingIndex <= previousIndex) {
      return _passed(step, boarding.stopName, sampleAt);
    }

    final previous = location.tripStops[previousIndex];
    return _predictedRailDeparture(
      step: step,
      from: previous,
      boarding: boarding,
      sampleAt: sampleAt,
    );
  }

  static NextRideRealtimeDeparture _predictedBusDeparture({
    required StepSeg step,
    required BusStopSchedule from,
    required BusStopSchedule boarding,
    required DateTime sampleAt,
  }) {
    final minutes = boarding.departureMinute - from.departureMinute;
    if (minutes <= 0) {
      throw StateError(
        '次便バスの乗車地点までの予定時間が不正です: '
        '${from.stopName} -> ${boarding.stopName}, $minutes分',
      );
    }
    return NextRideRealtimeDeparture(
      stepId: step.stepId,
      boardingPlaceName: boarding.stopName,
      status: NextRideRealtimeDepartureStatus.predicted,
      observedAt: sampleAt,
      predictedDepartureAt: sampleAt.add(Duration(minutes: minutes)),
    );
  }

  static NextRideRealtimeDeparture _predictedRailDeparture({
    required StepSeg step,
    required TrainTripStop from,
    required TrainTripStop boarding,
    required DateTime sampleAt,
  }) {
    final fromDeparture = _requiredTrainClock(
      from.departureTime,
      label: 'departure_time',
      stopName: from.stopName,
    );
    final boardingDeparture = _requiredTrainClock(
      boarding.departureTime,
      label: 'departure_time',
      stopName: boarding.stopName,
    );
    final seconds = boardingDeparture - fromDeparture;
    if (seconds <= 0) {
      throw StateError(
        '次便列車の乗車駅までの予定時間が不正です: '
        '${from.stopName} -> ${boarding.stopName}, $seconds秒',
      );
    }
    return NextRideRealtimeDeparture(
      stepId: step.stepId,
      boardingPlaceName: boarding.stopName,
      status: NextRideRealtimeDepartureStatus.predicted,
      observedAt: sampleAt,
      predictedDepartureAt: sampleAt.add(Duration(seconds: seconds)),
    );
  }

  static NextRideRealtimeDeparture _atBoarding(
    StepSeg step,
    String placeName,
    DateTime sampleAt,
  ) {
    return NextRideRealtimeDeparture(
      stepId: step.stepId,
      boardingPlaceName: placeName,
      status: NextRideRealtimeDepartureStatus.atBoardingPlace,
      observedAt: sampleAt,
    );
  }

  static NextRideRealtimeDeparture _passed(
    StepSeg step,
    String placeName,
    DateTime sampleAt,
  ) {
    return NextRideRealtimeDeparture(
      stepId: step.stepId,
      boardingPlaceName: placeName,
      status: NextRideRealtimeDepartureStatus.passedBoardingPlace,
      observedAt: sampleAt,
    );
  }

  static BusStopSchedule _busBoardingSchedule(
    StepSeg step,
    BusLocation location,
  ) {
    if (step.stops.isEmpty) {
      throw StateError('次便バスstepに乗車停留所がありません: ${step.stepId}');
    }
    final routeStop = step.stops.first;
    final stopId = routeStop.stopId?.trim();
    if (stopId == null || stopId.isEmpty) {
      throw StateError('次便バス乗車停留所にstopIdがありません: ${step.stepId}');
    }
    final matches = location.tripStopSchedule
        .where((stop) => stop.stopId == stopId)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '次便バス乗車停留所を時刻表で一意に特定できません: '
        'stepId=${step.stepId}, stopId=$stopId, matches=${matches.length}',
      );
    }
    final schedule = matches.single;
    if (schedule.stopName.trim() != routeStop.name.trim()) {
      throw StateError(
        '次便バスの経路/GTFS停留所名が一致しません: '
        '${routeStop.name} != ${schedule.stopName}',
      );
    }
    return schedule;
  }

  static BusStopSchedule _busScheduleAt(BusLocation location, int sequence) {
    final matches = location.tripStopSchedule
        .where((stop) => stop.sequence == sequence)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '次便バス時刻表のsequenceを一意に特定できません: '
        'trip=${location.tripId}, sequence=$sequence, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static TrainTripStop _trainStopAt(TrainLocation location, int sequence) {
    final matches = location.tripStops
        .where((stop) => stop.sequence == sequence)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '次便列車時刻表のsequenceを一意に特定できません: '
        'trip=${location.tripId}, sequence=$sequence, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static int _trainStopIndex(TrainLocation location, int sequence) {
    final matches = <int>[];
    for (var index = 0; index < location.tripStops.length; index++) {
      if (location.tripStops[index].sequence == sequence) {
        matches.add(index);
      }
    }
    if (matches.length != 1) {
      throw StateError(
        '次便列車のsequence indexを一意に特定できません: '
        'trip=${location.tripId}, sequence=$sequence, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static void _validateTrainStopOrder(TrainLocation location) {
    for (var index = 1; index < location.tripStops.length; index++) {
      final previous = location.tripStops[index - 1].sequence;
      final current = location.tripStops[index].sequence;
      if (current <= previous) {
        throw StateError(
          '次便列車のtrip_stopsがsequence順ではありません: '
          '$previous -> $current',
        );
      }
    }
  }

  static void _validateRailBoardingPlace(
    StepSeg step,
    TrainTripStop boarding,
  ) {
    final routeName = step.fromName?.trim();
    if (routeName == null || routeName.isEmpty) {
      throw StateError('次便列車stepに乗車駅名がありません: ${step.stepId}');
    }
    if (routeName != boarding.stopName.trim()) {
      throw StateError(
        '次便列車の経路/GTFS乗車駅名が一致しません: '
        '$routeName != ${boarding.stopName}',
      );
    }
    if (step.stops.isNotEmpty && step.stops.first.name.trim() != routeName) {
      throw StateError(
        '次便列車stepのfromName/stops先頭が一致しません: '
        '$routeName != ${step.stops.first.name}',
      );
    }
  }

  static String _requiredStatus(
    String? value, {
    required String transport,
    required String stepId,
  }) {
    final status = value?.trim();
    if (status == null || status.isEmpty) {
      throw StateError('$transportのcurrent_statusがありません: stepId=$stepId');
    }
    return status;
  }

  static int _requiredSequence(
    int? value, {
    required String label,
    required String stepId,
  }) {
    if (value == null || value <= 0) {
      throw StateError('$labelが不正です: stepId=$stepId, value=$value');
    }
    return value;
  }

  static DateTime _vehicleSampleAt({
    required int? vehicleTimestamp,
    required double? vehicleAgeSeconds,
    required DateTime now,
    required String transport,
    required String stepId,
  }) {
    if (vehicleTimestamp == null || vehicleTimestamp <= 0) {
      throw StateError('$transportのvehicle timestampがありません: stepId=$stepId');
    }
    if (vehicleAgeSeconds != null) {
      if (!vehicleAgeSeconds.isFinite || vehicleAgeSeconds < 0) {
        throw StateError(
          '$transportのvehicle ageが不正です: '
          'stepId=$stepId, age=$vehicleAgeSeconds',
        );
      }
      if (vehicleAgeSeconds > staleAfterSeconds) {
        throw StateError(
          '$transportの次便Realtimeが古すぎます: '
          'stepId=$stepId, age=$vehicleAgeSeconds秒',
        );
      }
    }

    final sampleAt = DateTime.fromMillisecondsSinceEpoch(
      vehicleTimestamp * 1000,
      isUtc: true,
    );
    final age = now.difference(sampleAt);
    if (age.isNegative) {
      throw StateError(
        '$transportのvehicle timestampが現在時刻より未来です: '
        'stepId=$stepId, sample=${sampleAt.toIso8601String()}, '
        'now=${now.toIso8601String()}',
      );
    }
    if (age.inMilliseconds / 1000 > staleAfterSeconds) {
      throw StateError(
        '$transportの次便Realtime timestampが古すぎます: '
        'stepId=$stepId, age=${age.inMilliseconds / 1000}秒',
      );
    }
    return sampleAt;
  }

  static int _requiredTrainClock(
    String? value, {
    required String label,
    required String stopName,
  }) {
    final text = value?.trim();
    if (text == null || text.isEmpty) {
      throw StateError('列車$stopNameの$labelがありません');
    }
    final parts = text.split(':');
    if (parts.length != 2 && parts.length != 3) {
      throw StateError('列車$stopNameの$labelが不正です: $text');
    }
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    final second = parts.length == 3 ? int.tryParse(parts[2]) : 0;
    if (hour == null ||
        minute == null ||
        second == null ||
        hour < 0 ||
        minute < 0 ||
        minute >= 60 ||
        second < 0 ||
        second >= 60) {
      throw StateError('列車$stopNameの$labelが不正です: $text');
    }
    return hour * 3600 + minute * 60 + second;
  }
}

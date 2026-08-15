import '../models/bus_progress.dart';
import '../models/rail_progress.dart';
import '../models/route_models.dart';
import '../services/bus_location_source.dart';
import '../services/train_location_source.dart';
import 'replan_anchor.dart';

/// Converts the existing bus/train realtime models into the transport-neutral
/// observation consumed by [ReplanAnchorResolver].
///
/// No user GPS is used here. While a vehicle is moving, the next stop's
/// availability is conservatively estimated as:
///
///   latest vehicle sample time + the full scheduled stop-to-stop duration
///
/// The same conservative rule is used to estimate the planned alighting point:
/// the latest vehicle sample plus the full scheduled duration from the last
/// confirmed stop to the alighting stop. The sample can already be part-way
/// through the segment, so these estimates may be later than the real arrival.
/// That is intentional for replanning: it avoids suggesting a connection that
/// depends on an optimistic arrival assumption.
/// Missing/stale timestamps or inconsistent timetable data are not repaired.
class ReplanTransitObservationAdapter {
  const ReplanTransitObservationAdapter._();

  static RidingTransitObservation fromBus({
    required StepSeg step,
    required BusProgress progress,
    required BusLocation location,
    required DateTime now,
  }) {
    if (step.kind != 'bus') {
      throw StateError(
        'BusLocationから再探索観測を作れるのはbus stepだけです: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }
    if (progress.stepId != step.stepId) {
      throw StateError(
        'BusProgressのstepIdが一致しません: '
        '${progress.stepId} != ${step.stepId}',
      );
    }
    if (progress.phase == BusProgressPhase.approaching) {
      throw StateError(
        '乗車前のバス位置からRidingTransitObservationは作りません: '
        'stepId=${step.stepId}',
      );
    }
    if (location.tripId != step.tripId) {
      throw StateError(
        'バスのtripIdが経路と一致しません: '
        '${location.tripId} != ${step.tripId}',
      );
    }

    final status = _requiredStatus(
      location.currentStatus,
      transport: 'bus',
      stepId: step.stepId,
    );

    if (status == 'STOPPED_AT') {
      final currentSchedule = _busScheduleAt(
        location,
        _requiredSequence(
          location.fromStopSequence,
          label: 'from_stop_sequence',
          stepId: step.stepId,
        ),
      );
      if (currentSchedule.stopId != location.fromStopId) {
        throw StateError(
          '停車中バスの現在停留所が時刻表と一致しません: '
          'location=${location.fromStopId}, schedule=${currentSchedule.stopId}',
        );
      }
      final destinationSchedule = _busDestinationSchedule(step, location);
      final predictedDestination = _predictBusDestination(
        step: step,
        location: location,
        from: currentSchedule,
        destination: destinationSchedule,
        now: now,
      );
      return RidingTransitObservation(
        stepId: step.stepId,
        motion: RidingTransitMotion.stopped,
        currentPlace: _busPlace(step, currentSchedule),
        predictedDestinationAvailableAt: predictedDestination,
      );
    }

    if (status != 'IN_TRANSIT_TO' && status != 'INCOMING_AT') {
      throw StateError(
        '再探索で未対応のバスcurrent_statusです: $status',
      );
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
        '走行中バスのsequenceが前進していません: '
        '$fromSequence -> $observedSequence',
      );
    }

    final currentSchedule = _busScheduleAt(location, fromSequence);
    final nextSchedule = _busScheduleAt(location, observedSequence);
    if (currentSchedule.stopId != location.fromStopId) {
      throw StateError(
        '走行中バスの直前停留所が時刻表と一致しません: '
        'location=${location.fromStopId}, schedule=${currentSchedule.stopId}',
      );
    }
    final rawNextStopId = location.rawStopId;
    if (rawNextStopId == null || rawNextStopId.isEmpty) {
      throw StateError('走行中バスにGTFS-RTの次停留所IDがありません');
    }
    if (nextSchedule.stopId != rawNextStopId) {
      throw StateError(
        '走行中バスの次停留所が時刻表と一致しません: '
        'realtime=$rawNextStopId, schedule=${nextSchedule.stopId}',
      );
    }

    final segmentMinutes =
        nextSchedule.arrivalMinute - currentSchedule.departureMinute;
    if (segmentMinutes <= 0) {
      throw StateError(
        'バスの停留所間所要時間が不正です: '
        '${currentSchedule.stopName} -> ${nextSchedule.stopName}, '
        '$segmentMinutes分',
      );
    }

    final predicted = _predictFromVehicleSample(
      vehicleTimestamp: location.vehicleTimestamp,
      scheduledSegment: Duration(minutes: segmentMinutes),
      now: now,
      transport: 'bus',
      stepId: step.stepId,
    );
    final destinationSchedule = _busDestinationSchedule(step, location);
    final predictedDestination = _predictBusDestination(
      step: step,
      location: location,
      from: currentSchedule,
      destination: destinationSchedule,
      now: now,
    );

    return RidingTransitObservation(
      stepId: step.stepId,
      motion: RidingTransitMotion.inTransit,
      currentPlace: _busPlace(step, currentSchedule),
      nextPlace: _busPlace(step, nextSchedule),
      predictedNextAvailableAt: predicted,
      predictedDestinationAvailableAt: predictedDestination,
    );
  }

  static RidingTransitObservation fromRail({
    required StepSeg step,
    required RailProgress progress,
    required TrainLocation location,
    required DateTime now,
  }) {
    if (step.kind != 'rail') {
      throw StateError(
        'TrainLocationから再探索観測を作れるのはrail stepだけです: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }
    if (progress.stepId != step.stepId) {
      throw StateError(
        'RailProgressのstepIdが一致しません: '
        '${progress.stepId} != ${step.stepId}',
      );
    }
    if (progress.tripId != location.tripId) {
      throw StateError(
        'RailProgressとTrainLocationのtripIdが一致しません: '
        '${progress.tripId} != ${location.tripId}',
      );
    }
    if (progress.phase == RailProgressPhase.approaching) {
      throw StateError(
        '乗車前の列車位置からRidingTransitObservationは作りません: '
        'stepId=${step.stepId}',
      );
    }

    final status = _requiredStatus(
      location.currentStatus,
      transport: 'rail',
      stepId: step.stepId,
    );

    if (status == 'STOPPED_AT') {
      final currentStop = _trainStopAt(
        location,
        location.currentStopSequence,
      );
      final destinationStop = _trainDestinationStop(step, location);
      final predictedDestination = _predictRailDestination(
        step: step,
        location: location,
        from: currentStop,
        destination: destinationStop,
        now: now,
      );
      return RidingTransitObservation(
        stepId: step.stepId,
        motion: RidingTransitMotion.stopped,
        currentPlace: _railPlace(step, currentStop),
        predictedDestinationAvailableAt: predictedDestination,
      );
    }

    if (status != 'IN_TRANSIT_TO' && status != 'INCOMING_AT') {
      throw StateError(
        '再探索で未対応の列車current_statusです: $status',
      );
    }

    final currentStop = _trainStopAt(location, progress.lastReachedSequence);
    final nextStop = _trainStopAt(location, location.currentStopSequence);
    if (nextStop.sequence <= currentStop.sequence) {
      throw StateError(
        '走行中列車のsequenceが前進していません: '
        '${currentStop.sequence} -> ${nextStop.sequence}',
      );
    }

    final currentDeparture = _requiredTrainClock(
      currentStop.departureTime,
      label: 'departure_time',
      stopName: currentStop.stopName,
    );
    final nextArrival = _requiredTrainClock(
      nextStop.arrivalTime,
      label: 'arrival_time',
      stopName: nextStop.stopName,
    );
    final segmentSeconds = nextArrival - currentDeparture;
    if (segmentSeconds <= 0) {
      throw StateError(
        '列車の駅間所要時間が不正です: '
        '${currentStop.stopName} -> ${nextStop.stopName}, '
        '$segmentSeconds秒',
      );
    }

    final predicted = _predictFromVehicleSample(
      vehicleTimestamp: location.vehicleTimestamp,
      scheduledSegment: Duration(seconds: segmentSeconds),
      now: now,
      transport: 'rail',
      stepId: step.stepId,
    );
    final destinationStop = _trainDestinationStop(step, location);
    final predictedDestination = _predictRailDestination(
      step: step,
      location: location,
      from: currentStop,
      destination: destinationStop,
      now: now,
    );

    return RidingTransitObservation(
      stepId: step.stepId,
      motion: RidingTransitMotion.inTransit,
      currentPlace: _railPlace(step, currentStop),
      nextPlace: _railPlace(step, nextStop),
      predictedNextAvailableAt: predicted,
      predictedDestinationAvailableAt: predictedDestination,
    );
  }

  static String _requiredStatus(
    String? value, {
    required String transport,
    required String stepId,
  }) {
    final status = value?.trim();
    if (status == null || status.isEmpty) {
      throw StateError(
        '$transportのcurrent_statusがありません: stepId=$stepId',
      );
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

  static BusStopSchedule _busScheduleAt(BusLocation location, int sequence) {
    final matches = location.tripStopSchedule
        .where((stop) => stop.sequence == sequence)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        'バス時刻表のsequenceを一意に特定できません: '
        'trip=${location.tripId}, sequence=$sequence, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static BusStopSchedule _busDestinationSchedule(
    StepSeg step,
    BusLocation location,
  ) {
    if (step.stops.isEmpty) {
      throw StateError('バス乗車stepに降車停留所がありません: ${step.stepId}');
    }
    final destinationStopId = step.stops.last.stopId;
    if (destinationStopId == null || destinationStopId.isEmpty) {
      throw StateError('バス降車停留所にstopIdがありません: ${step.stepId}');
    }
    final matches = location.tripStopSchedule
        .where((stop) => stop.stopId == destinationStopId)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        'バス降車停留所を時刻表で一意に特定できません: '
        'stepId=${step.stepId}, stopId=$destinationStopId, '
        'matches=${matches.length}',
      );
    }
    final schedule = matches.single;
    if (schedule.stopName.trim() != step.stops.last.name.trim()) {
      throw StateError(
        '経路とGTFS時刻表のバス降車停留所名が一致しません: '
        '${step.stops.last.name} != ${schedule.stopName}',
      );
    }
    return schedule;
  }

  static DateTime _predictBusDestination({
    required StepSeg step,
    required BusLocation location,
    required BusStopSchedule from,
    required BusStopSchedule destination,
    required DateTime now,
  }) {
    final remainingMinutes =
        destination.arrivalMinute - from.departureMinute;
    if (remainingMinutes <= 0) {
      throw StateError(
        'バス降車地点までの残り予定時間が不正です: '
        'stepId=${step.stepId}, ${from.stopName} -> ${destination.stopName}, '
        '$remainingMinutes分',
      );
    }
    return _predictFromVehicleSample(
      vehicleTimestamp: location.vehicleTimestamp,
      scheduledSegment: Duration(minutes: remainingMinutes),
      now: now,
      transport: 'bus',
      stepId: step.stepId,
    );
  }

  static TrainTripStop _trainStopAt(TrainLocation location, int sequence) {
    final matches = location.tripStops
        .where((stop) => stop.sequence == sequence)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '列車時刻表のsequenceを一意に特定できません: '
        'trip=${location.tripId}, sequence=$sequence, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static TrainTripStop _trainDestinationStop(
    StepSeg step,
    TrainLocation location,
  ) {
    final destination = _trainStopAt(location, location.destinationSequence);
    _railPlace(step, destination);
    return destination;
  }

  static DateTime _predictRailDestination({
    required StepSeg step,
    required TrainLocation location,
    required TrainTripStop from,
    required TrainTripStop destination,
    required DateTime now,
  }) {
    final currentDeparture = _requiredTrainClock(
      from.departureTime,
      label: 'departure_time',
      stopName: from.stopName,
    );
    final destinationArrival = _requiredTrainClock(
      destination.arrivalTime,
      label: 'arrival_time',
      stopName: destination.stopName,
    );
    final remainingSeconds = destinationArrival - currentDeparture;
    if (remainingSeconds <= 0) {
      throw StateError(
        '列車降車駅までの残り予定時間が不正です: '
        'stepId=${step.stepId}, ${from.stopName} -> ${destination.stopName}, '
        '$remainingSeconds秒',
      );
    }
    return _predictFromVehicleSample(
      vehicleTimestamp: location.vehicleTimestamp,
      scheduledSegment: Duration(seconds: remainingSeconds),
      now: now,
      transport: 'rail',
      stepId: step.stepId,
    );
  }

  static ReplanTransitPlace _busPlace(
    StepSeg step,
    BusStopSchedule schedule,
  ) {
    final matches = step.stops
        .where((stop) => stop.stopId == schedule.stopId)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '経路上のバス停をIDで一意に特定できません: '
        'stepId=${step.stepId}, stopId=${schedule.stopId}, '
        'matches=${matches.length}',
      );
    }
    final stop = matches.single;
    if (stop.name.trim() != schedule.stopName.trim()) {
      throw StateError(
        '経路とGTFS時刻表のバス停名が一致しません: '
        '${stop.name} != ${schedule.stopName}',
      );
    }
    return ReplanTransitPlace(
      name: stop.name,
      stopId: stop.stopId,
      point: stop.point,
    );
  }

  static ReplanTransitPlace _railPlace(
    StepSeg step,
    TrainTripStop staticStop,
  ) {
    // The route graph uses ODPT station IDs while the static train GTFS uses
    // its own stop IDs. The exact Japanese station name is the common identity
    // already used by train trip resolution, so rail points are matched by name.
    final wantedName = staticStop.stopName.trim();
    final matches = step.stops
        .where((stop) => stop.name.trim() == wantedName)
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '経路上の駅を駅名で一意に特定できません: '
        'stepId=${step.stepId}, station=$wantedName, matches=${matches.length}',
      );
    }
    final stop = matches.single;
    return ReplanTransitPlace(
      name: stop.name,
      stopId: stop.stopId,
      point: stop.point,
    );
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

  static DateTime _predictFromVehicleSample({
    required int? vehicleTimestamp,
    required Duration scheduledSegment,
    required DateTime now,
    required String transport,
    required String stepId,
  }) {
    if (vehicleTimestamp == null || vehicleTimestamp <= 0) {
      throw StateError(
        '$transportのvehicle timestampがありません: stepId=$stepId',
      );
    }
    if (scheduledSegment <= Duration.zero) {
      throw StateError(
        '$transportの予定区間時間が不正です: '
        'stepId=$stepId, duration=$scheduledSegment',
      );
    }

    final sampleAt = DateTime.fromMillisecondsSinceEpoch(
      vehicleTimestamp * 1000,
      isUtc: true,
    );
    final predicted = sampleAt.add(scheduledSegment);
    if (!predicted.isAfter(now)) {
      throw StateError(
        '$transportの次停車地点到着見込みが古すぎます: '
        'stepId=$stepId, sample=${sampleAt.toIso8601String()}, '
        'duration=$scheduledSegment, predicted=${predicted.toIso8601String()}, '
        'now=${now.toIso8601String()}',
      );
    }
    return predicted;
  }
}

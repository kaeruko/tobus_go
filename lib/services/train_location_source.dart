import '../core/api_client.dart';
import '../models/route_models.dart';


class TrainLocationNotAvailableException implements Exception {
  final String? code;

  const TrainLocationNotAvailableException({this.code});

  @override
  String toString() => code ?? 'train_location_not_available';
}


class TrainTripStop {
  final int sequence;
  final String stopId;
  final String stopName;
  final String? arrivalTime;
  final String? departureTime;

  const TrainTripStop({
    required this.sequence,
    required this.stopId,
    required this.stopName,
    this.arrivalTime,
    this.departureTime,
  });

  factory TrainTripStop.fromJson(Map<String, dynamic> json) {
    final sequence = (json['sequence'] as num?)?.toInt();
    final stopId = json['stop_id']?.toString();
    final stopName = json['stop_name']?.toString();
    if (sequence == null) {
      throw const FormatException('train trip stop is missing sequence');
    }
    if (stopId == null || stopId.isEmpty) {
      throw const FormatException('train trip stop is missing stop_id');
    }
    if (stopName == null || stopName.isEmpty) {
      throw const FormatException('train trip stop is missing stop_name');
    }
    return TrainTripStop(
      sequence: sequence,
      stopId: stopId,
      stopName: stopName,
      arrivalTime: json['arrival_time']?.toString(),
      departureTime: json['departure_time']?.toString(),
    );
  }
}


class TrainLocation {
  final String tripId;
  final String routeId;
  final String vehicleId;
  final int currentStopSequence;
  final String currentStatus;
  final String currentStopId;
  final String currentStopName;
  final int boardingSequence;
  final int destinationSequence;
  final int? vehicleTimestamp;
  final double? vehicleAgeSeconds;
  final List<TrainTripStop> tripStops;

  const TrainLocation({
    required this.tripId,
    required this.routeId,
    required this.vehicleId,
    required this.currentStopSequence,
    required this.currentStatus,
    required this.currentStopId,
    required this.currentStopName,
    required this.boardingSequence,
    required this.destinationSequence,
    this.vehicleTimestamp,
    this.vehicleAgeSeconds,
    required this.tripStops,
  });

  factory TrainLocation.fromJson(Map<String, dynamic> json) {
    final tripId = json['trip_id']?.toString();
    final routeId = json['route_id']?.toString();
    final vehicleId = json['vehicle_id']?.toString();
    final currentStopSequence = (json['current_stop_sequence'] as num?)?.toInt();
    final currentStatus = json['current_status']?.toString();
    final currentStopId = json['current_stop_id']?.toString();
    final currentStopName = json['current_stop_name']?.toString();
    final boardingSequence = (json['boarding_sequence'] as num?)?.toInt();
    final destinationSequence = (json['destination_sequence'] as num?)?.toInt();
    final rawTripStops = json['trip_stops'];

    if (tripId == null || tripId.isEmpty) {
      throw const FormatException('train location is missing trip_id');
    }
    if (routeId == null || routeId.isEmpty) {
      throw const FormatException('train location is missing route_id');
    }
    if (vehicleId == null || vehicleId.isEmpty) {
      throw const FormatException('train location is missing vehicle_id');
    }
    if (currentStopSequence == null) {
      throw const FormatException('train location is missing current_stop_sequence');
    }
    if (currentStatus == null || currentStatus.isEmpty) {
      throw const FormatException('train location is missing current_status');
    }
    if (currentStopId == null || currentStopId.isEmpty) {
      throw const FormatException('train location is missing current_stop_id');
    }
    if (currentStopName == null || currentStopName.isEmpty) {
      throw const FormatException('train location is missing current_stop_name');
    }
    if (boardingSequence == null || destinationSequence == null) {
      throw const FormatException(
        'train location is missing boarding/destination sequence',
      );
    }
    if (destinationSequence <= boardingSequence) {
      throw FormatException(
        'train location has invalid ride sequence: '
        '$boardingSequence->$destinationSequence',
      );
    }
    if (rawTripStops is! List || rawTripStops.isEmpty) {
      throw const FormatException('train location is missing trip_stops');
    }

    final tripStops = rawTripStops
        .map(
          (value) => TrainTripStop.fromJson(
            Map<String, dynamic>.from(value as Map),
          ),
        )
        .toList(growable: false);

    return TrainLocation(
      tripId: tripId,
      routeId: routeId,
      vehicleId: vehicleId,
      currentStopSequence: currentStopSequence,
      currentStatus: currentStatus,
      currentStopId: currentStopId,
      currentStopName: currentStopName,
      boardingSequence: boardingSequence,
      destinationSequence: destinationSequence,
      vehicleTimestamp: (json['vehicle_ts'] as num?)?.toInt(),
      vehicleAgeSeconds: (json['vehicle_age_seconds'] as num?)?.toDouble(),
      tripStops: tripStops,
    );
  }
}


abstract interface class TrainLocationSource {
  Future<TrainLocation> fetch({
    required StepSeg step,
    bool forceRefresh = false,
  });
}


class RealtimeTrainLocationSource implements TrainLocationSource {
  const RealtimeTrainLocationSource();

  @override
  Future<TrainLocation> fetch({
    required StepSeg step,
    bool forceRefresh = false,
  }) async {
    if (step.kind != 'rail') {
      throw ArgumentError('TrainLocationSource requires rail step: ${step.kind}');
    }
    final fromName = step.fromName?.trim();
    final toName = step.toName?.trim();
    final arrivalTime = step.arrivalTime?.trim();
    if (fromName == null || fromName.isEmpty) {
      throw StateError('rail step is missing fromName: ${step.stepId}');
    }
    if (toName == null || toName.isEmpty) {
      throw StateError('rail step is missing toName: ${step.stepId}');
    }
    if (arrivalTime == null || arrivalTime.isEmpty) {
      throw StateError('rail step is missing arrivalTime: ${step.stepId}');
    }

    try {
      final json = await ApiClient.fetchTrainLocation(
        tripId: step.tripId,
        fromName: fromName,
        toName: toName,
        arrivalTime: arrivalTime,
        forceRefresh: forceRefresh,
      );
      return TrainLocation.fromJson(json);
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        throw TrainLocationNotAvailableException(code: error.code);
      }
      rethrow;
    }
  }
}

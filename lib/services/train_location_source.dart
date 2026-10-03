import '../core/api_client.dart';
import '../core/city_profile.dart';
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
  final String? stopNameEn;
  final String? arrivalTime;
  final String? departureTime;

  const TrainTripStop({
    required this.sequence,
    required this.stopId,
    required this.stopName,
    this.stopNameEn,
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
      stopNameEn: json['stop_name_en']?.toString(),
      arrivalTime: json['arrival_time']?.toString(),
      departureTime: json['departure_time']?.toString(),
    );
  }
}

class TrainLocation {
  final String tripId;
  final String routeId;
  final String tripHeadsign;
  final String? tripHeadsignEn;
  final String vehicleId;
  final int currentStopSequence;
  final String currentStatus;
  final String currentStopId;
  final String currentStopName;
  final String? currentStopNameEn;
  final int boardingSequence;
  final int destinationSequence;
  final int? vehicleTimestamp;
  final double? vehicleAgeSeconds;
  final List<TrainTripStop> tripStops;

  const TrainLocation({
    required this.tripId,
    required this.routeId,
    required this.tripHeadsign,
    this.tripHeadsignEn,
    required this.vehicleId,
    required this.currentStopSequence,
    required this.currentStatus,
    required this.currentStopId,
    required this.currentStopName,
    this.currentStopNameEn,
    required this.boardingSequence,
    required this.destinationSequence,
    this.vehicleTimestamp,
    this.vehicleAgeSeconds,
    required this.tripStops,
  });

  factory TrainLocation.fromJson(Map<String, dynamic> json) {
    final tripId = json['trip_id']?.toString();
    final routeId = json['route_id']?.toString();
    final tripHeadsign = json['trip_headsign']?.toString().trim();
    final tripHeadsignEn = json['trip_headsign_en']?.toString().trim();
    final vehicleId = json['vehicle_id']?.toString();
    final currentStopSequence = (json['current_stop_sequence'] as num?)?.toInt();
    final currentStatus = json['current_status']?.toString();
    final currentStopId = json['current_stop_id']?.toString();
    final currentStopName = json['current_stop_name']?.toString();
    final currentStopNameEn = json['current_stop_name_en']?.toString();
    final boardingSequence = (json['boarding_sequence'] as num?)?.toInt();
    final destinationSequence = (json['destination_sequence'] as num?)?.toInt();
    final rawTripStops = json['trip_stops'];

    if (tripId == null || tripId.isEmpty) {
      throw const FormatException('train location is missing trip_id');
    }
    if (routeId == null || routeId.isEmpty) {
      throw const FormatException('train location is missing route_id');
    }
    if (tripHeadsign == null || tripHeadsign.isEmpty) {
      throw const FormatException('train location is missing trip_headsign');
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
      tripHeadsign: tripHeadsign,
      tripHeadsignEn: tripHeadsignEn,
      vehicleId: vehicleId,
      currentStopSequence: currentStopSequence,
      currentStatus: currentStatus,
      currentStopId: currentStopId,
      currentStopName: currentStopName,
      currentStopNameEn: currentStopNameEn,
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
  final CityProfile? cityProfile;

  const RealtimeTrainLocationSource({this.cityProfile});

  @override
  Future<TrainLocation> fetch({
    required StepSeg step,
    bool forceRefresh = false,
  }) async {
    final profile = cityProfile ?? configuredCityProfile;
    if (!profile.capabilities.realtime.vehiclePosition) {
      throw TrainLocationNotAvailableException(
        code: 'realtime_vehicle_position_unsupported:${profile.key}',
      );
    }
    if (step.kind != 'rail') {
      throw ArgumentError('TrainLocationSource requires rail step: ${step.kind}');
    }
    final tripId = step.tripId?.trim();
    if (tripId == null || tripId.isEmpty) {
      throw StateError('rail step is missing tripId: ${step.stepId}');
    }
    if (step.stops.length < 2) {
      throw StateError(
        'rail step is missing boarding/destination stops: ${step.stepId}',
      );
    }
    final fromStopId = step.stops.first.stopId?.trim();
    final toStopId = step.stops.last.stopId?.trim();
    if (fromStopId == null || fromStopId.isEmpty) {
      throw StateError(
        'rail step boarding stop is missing stopId: ${step.stepId}',
      );
    }
    if (toStopId == null || toStopId.isEmpty) {
      throw StateError(
        'rail step destination stop is missing stopId: ${step.stepId}',
      );
    }

    try {
      final json = await ApiClient.fetchTrainLocation(
        tripId: tripId,
        fromStopId: fromStopId,
        toStopId: toStopId,
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

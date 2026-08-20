import '../core/api_client.dart';
import '../core/city_profile.dart';

class BusLocationNotAvailableException implements Exception {
  final String? code;

  const BusLocationNotAvailableException({this.code});

  @override
  String toString() => code ?? 'bus_location_not_available';
}

class BusStopSchedule {
  final int sequence;
  final String stopId;
  final String stopName;
  final int arrivalMinute;
  final int departureMinute;
  final String arrivalTime;
  final String departureTime;

  const BusStopSchedule({
    required this.sequence,
    required this.stopId,
    required this.stopName,
    required this.arrivalMinute,
    required this.departureMinute,
    required this.arrivalTime,
    required this.departureTime,
  });

  factory BusStopSchedule.fromJson(Map<String, dynamic> json) {
    return BusStopSchedule(
      sequence: (json['sequence'] as num).toInt(),
      stopId: json['stop_id'].toString(),
      stopName: json['stop_name'].toString(),
      arrivalMinute: (json['arrival_minute'] as num).toInt(),
      departureMinute: (json['departure_minute'] as num).toInt(),
      arrivalTime: json['arrival_time'].toString(),
      departureTime: json['departure_time'].toString(),
    );
  }
}

class BusLocation {
  final String vehicleId;
  final String fromStopId;
  final String routeId;
  final String tripId;
  final List<String> tripStopIds;
  final String? rawStopId;
  final String? rawStopName;
  final int? fromStopSequence;
  final int? observedStopSequence;
  final String? currentStatus;
  final int? feedTimestamp;
  final int? vehicleTimestamp;
  final int? realtimeFetchedTimestamp;
  final String? serverNow;
  final double? snapshotAgeSeconds;
  final double? feedAgeSeconds;
  final double? vehicleAgeSeconds;
  final List<BusStopSchedule> tripStopSchedule;

  const BusLocation({
    required this.vehicleId,
    required this.fromStopId,
    required this.routeId,
    required this.tripId,
    this.tripStopIds = const [],
    this.rawStopId,
    this.rawStopName,
    this.fromStopSequence,
    this.observedStopSequence,
    this.currentStatus,
    this.feedTimestamp,
    this.vehicleTimestamp,
    this.realtimeFetchedTimestamp,
    this.serverNow,
    this.snapshotAgeSeconds,
    this.feedAgeSeconds,
    this.vehicleAgeSeconds,
    this.tripStopSchedule = const [],
  });

  factory BusLocation.fromJson(
    Map<String, dynamic> json, {
    required String routeId,
    required String tripId,
  }) {
    final vehicleId = (json['vehicle_id'] ?? json['odpt:bus'])?.toString();
    final fromStopId = json['odpt:fromBusstopPole']?.toString();
    final responseTripId = json['trip_id']?.toString();
    final tripStopIds = (json['trip_stop_ids'] as List<dynamic>? ?? const [])
        .map((value) => value.toString())
        .toList(growable: false);
    final tripStopSchedule =
        (json['trip_stop_schedule'] as List<dynamic>? ?? const [])
            .map(
              (value) => BusStopSchedule.fromJson(
                Map<String, dynamic>.from(value as Map),
              ),
            )
            .toList(growable: false);
    if (vehicleId == null || vehicleId.isEmpty) {
      throw const FormatException('bus location is missing vehicle_id');
    }
    if (fromStopId == null || fromStopId.isEmpty) {
      throw const FormatException(
        'bus location is missing odpt:fromBusstopPole',
      );
    }
    if (responseTripId != tripId) {
      throw FormatException(
        'bus location trip_id mismatch: expected=$tripId actual=$responseTripId',
      );
    }
    return BusLocation(
      vehicleId: vehicleId,
      fromStopId: fromStopId,
      routeId: routeId,
      tripId: tripId,
      tripStopIds: tripStopIds,
      rawStopId: json['raw_stop_id']?.toString(),
      rawStopName: json['raw_stop_name']?.toString(),
      fromStopSequence: (json['from_stop_sequence'] as num?)?.toInt(),
      observedStopSequence: (json['observed_stop_sequence'] as num?)?.toInt(),
      currentStatus: json['current_status']?.toString(),
      feedTimestamp: (json['feed_ts'] as num?)?.toInt(),
      vehicleTimestamp: (json['vehicle_ts'] as num?)?.toInt(),
      realtimeFetchedTimestamp: (json['realtime_fetched_ts'] as num?)?.toInt(),
      serverNow: json['server_now']?.toString(),
      snapshotAgeSeconds: (json['snapshot_age_seconds'] as num?)?.toDouble(),
      feedAgeSeconds: (json['feed_age_seconds'] as num?)?.toDouble(),
      vehicleAgeSeconds: (json['vehicle_age_seconds'] as num?)?.toDouble(),
      tripStopSchedule: tripStopSchedule,
    );
  }
}

abstract interface class BusLocationSource {
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? vehicleId,
    bool forceRefresh = false,
  });
}

class RealtimeBusLocationSource implements BusLocationSource {
  final CityProfile? cityProfile;

  const RealtimeBusLocationSource({this.cityProfile});

  @override
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? vehicleId,
    bool forceRefresh = false,
  }) async {
    final profile = cityProfile ?? configuredCityProfile;
    if (!profile.capabilities.realtime.vehiclePosition) {
      throw BusLocationNotAvailableException(
        code: 'realtime_vehicle_position_unsupported:${profile.key}',
      );
    }

    try {
      final json = await ApiClient.fetchBusLocation(
        routeId: routeId,
        tripId: tripId,
        vehicleId: vehicleId,
        forceRefresh: forceRefresh,
      );
      return BusLocation.fromJson(json, routeId: routeId, tripId: tripId);
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        throw BusLocationNotAvailableException(code: error.code);
      }
      rethrow;
    }
  }
}

/// Deterministic source for home and unit testing. Calling [advance] is the
/// programmatic equivalent of pressing a "next stop" button.
class FakeBusLocationSource implements BusLocationSource {
  final List<BusLocation> locations;
  int _index = 0;

  FakeBusLocationSource(this.locations) {
    if (locations.isEmpty) {
      throw ArgumentError.value(locations, 'locations', 'must not be empty');
    }
  }

  int get index => _index;
  bool get canAdvance => _index < locations.length - 1;

  void advance() {
    if (canAdvance) _index++;
  }

  void reset() {
    _index = 0;
  }

  @override
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? vehicleId,
    bool forceRefresh = false,
  }) async {
    final location = locations[_index];
    if (location.routeId != routeId || location.tripId != tripId) {
      throw StateError('FakeBus route/trip mismatch: $routeId/$tripId');
    }
    if (vehicleId != null && location.vehicleId != vehicleId) {
      throw StateError(
        'FakeBus vehicle mismatch: expected=$vehicleId '
        'actual=${location.vehicleId}',
      );
    }
    return location;
  }
}

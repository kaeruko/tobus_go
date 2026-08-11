import '../core/api_client.dart';

class BusLocation {
  final String vehicleId;
  final String fromStopId;
  final String routeId;
  final String tripId;
  final List<String> tripStopIds;

  const BusLocation({
    required this.vehicleId,
    required this.fromStopId,
    required this.routeId,
    required this.tripId,
    this.tripStopIds = const [],
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
    );
  }
}

abstract interface class BusLocationSource {
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? vehicleId,
  });
}

class RealtimeBusLocationSource implements BusLocationSource {
  const RealtimeBusLocationSource();

  @override
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? vehicleId,
  }) async {
    final json = await ApiClient.fetchBusLocation(
      routeId: routeId,
      tripId: tripId,
      vehicleId: vehicleId,
    );
    return BusLocation.fromJson(json, routeId: routeId, tripId: tripId);
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

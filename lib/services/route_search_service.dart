import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../core/api_client.dart';
import '../models/route_models.dart';

class RouteSearchRequest {
  final LatLng origin;
  final LatLng destination;
  final String originName;
  final String destinationName;
  final DateTime startTime;
  final String? preference;

  RouteSearchRequest({
    required this.origin,
    required this.destination,
    required String originName,
    required String destinationName,
    required this.startTime,
    this.preference,
  }) : originName = originName.trim(),
       destinationName = destinationName.trim() {
    _validatePoint(origin, 'origin');
    _validatePoint(destination, 'destination');
  }

  Map<String, dynamic> toApiBody() {
    // GTFS-RT timestamps are absolute/UTC while /route expects the local
    // service-day clock. Convert at the API boundary so normal searches and
    // realtime replans use the same local-time semantics.
    final localStartTime = startTime.toLocal();
    return {
      'alat': origin.latitude.toString(),
      'alon': origin.longitude.toString(),
      'blat': destination.latitude.toString(),
      'blon': destination.longitude.toString(),
      'pref': normalizeRoutePreferenceForApi(preference),
      'start_time':
          '${localStartTime.hour.toString().padLeft(2, '0')}:'
          '${localStartTime.minute.toString().padLeft(2, '0')}',
      'target_date_str':
          '${localStartTime.year.toString().padLeft(4, '0')}-'
          '${localStartTime.month.toString().padLeft(2, '0')}-'
          '${localStartTime.day.toString().padLeft(2, '0')}',
    };
  }

  static void _validatePoint(LatLng point, String label) {
    if (!point.latitude.isFinite || !point.longitude.isFinite) {
      throw ArgumentError.value(point, label, 'must be finite');
    }
  }
}

class RouteSearchResult {
  final List<Candidate> candidates;
  final RouteMeta meta;

  const RouteSearchResult({
    required this.candidates,
    required this.meta,
  });
}

abstract class RouteSearchService {
  Future<RouteSearchResult> search(RouteSearchRequest request);
}

class ApiRouteSearchService implements RouteSearchService {
  const ApiRouteSearchService();

  @override
  Future<RouteSearchResult> search(RouteSearchRequest request) async {
    final response = await ApiClient.post('/route', body: request.toApiBody());

    final rawCandidates = response['candidates'];
    if (rawCandidates is! List) {
      throw const FormatException('route response is missing candidates list');
    }
    final rawMeta = response['meta'];
    if (rawMeta is! Map) {
      throw const FormatException('route response is missing meta object');
    }

    final candidates = <Candidate>[];
    for (final rawCandidate in rawCandidates) {
      if (rawCandidate is! Map) {
        throw const FormatException('route candidate must be an object');
      }
      final map = Map<String, dynamic>.from(rawCandidate);
      if (map['destination_name'] == null ||
          map['destination_name'].toString().trim().isEmpty) {
        map['destination_name'] = request.destinationName;
      }
      if (map['origin_name'] == null ||
          map['origin_name'].toString().trim().isEmpty) {
        map['origin_name'] = request.originName;
      }
      candidates.add(Candidate.fromJson(map));
    }

    return RouteSearchResult(
      candidates: List.unmodifiable(candidates),
      meta: RouteMeta.fromJson(Map<String, dynamic>.from(rawMeta)),
    );
  }
}

String normalizeRoutePreferenceForApi(String? preference) {
  if (preference == 'shortTime') return 'time';
  if (preference == null || preference.isEmpty) return 'cost';
  return preference;
}

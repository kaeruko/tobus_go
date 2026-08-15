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
    final apiBody = request.toApiBody();
    final response = await ApiClient.post('/route', body: apiBody);

    var rawCandidates = response['candidates'];
    if (rawCandidates is! List) {
      throw const FormatException('route response is missing candidates list');
    }
    final rawMeta = response['meta'];
    if (rawMeta is! Map) {
      throw const FormatException('route response is missing meta object');
    }

    if (_containsRailCandidate(rawCandidates)) {
      final identityResponse = await ApiClient.post(
        '/train/resolve-route-identities',
        body: {
          'candidates': rawCandidates,
          'target_date_str': apiBody['target_date_str'],
        },
      );
      final resolvedCandidates = identityResponse['candidates'];
      if (resolvedCandidates is! List) {
        throw const FormatException(
          'train identity response is missing candidates list',
        );
      }
      final rejections = identityResponse['rejections'];
      if (rejections is! List) {
        throw const FormatException(
          'train identity response is missing rejections list',
        );
      }
      if (rawCandidates.isNotEmpty && resolvedCandidates.isEmpty) {
        throw StateError(
          _trainIdentityFailureMessage(rejections),
        );
      }
      rawCandidates = resolvedCandidates;
    }

    final candidates = <Candidate>[];
    for (final rawCandidate in rawCandidates) {
      if (rawCandidate is! Map) {
        throw const FormatException('route candidate must be an object');
      }
      final map = Map<String, dynamic>.from(rawCandidate);
      _validateResolvedRailIdentity(map);
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

  static bool _containsRailCandidate(List<dynamic> candidates) {
    for (final rawCandidate in candidates) {
      if (rawCandidate is! Map) {
        throw const FormatException('route candidate must be an object');
      }
      final steps = rawCandidate['steps'];
      if (steps is! List) {
        throw const FormatException('route candidate is missing steps list');
      }
      for (final step in steps) {
        if (step is! Map) {
          throw const FormatException('route step must be an object');
        }
        if (step['kind'] == 'rail') return true;
      }
    }
    return false;
  }

  static void _validateResolvedRailIdentity(Map<String, dynamic> candidate) {
    final steps = candidate['steps'];
    if (steps is! List) {
      throw const FormatException('route candidate is missing steps list');
    }
    for (final rawStep in steps) {
      if (rawStep is! Map) {
        throw const FormatException('route step must be an object');
      }
      if (rawStep['kind'] != 'rail') continue;
      final stepId = rawStep['step_id']?.toString() ?? '';
      final tripId = rawStep['trip_id']?.toString().trim() ?? '';
      final routeId = rawStep['route_id']?.toString().trim() ?? '';
      if (tripId.isEmpty) {
        throw FormatException(
          'rail route step is missing exact GTFS trip_id: $stepId',
        );
      }
      if (routeId.isEmpty) {
        throw FormatException(
          'rail route step is missing exact GTFS route_id: $stepId',
        );
      }
    }
  }

  static String _trainIdentityFailureMessage(List<dynamic> rejections) {
    if (rejections.isEmpty) {
      return '鉄道便をGTFS trip_idで確定できる経路候補がありません';
    }
    final details = <String>[];
    for (final rejection in rejections) {
      if (rejection is! Map) {
        throw const FormatException(
          'train identity rejection must be an object',
        );
      }
      final candidateId = rejection['candidate_id']?.toString() ?? '';
      final code = rejection['code']?.toString() ?? '';
      final message = rejection['message']?.toString() ?? '';
      if (code.isEmpty || message.isEmpty) {
        throw const FormatException(
          'train identity rejection is missing code/message',
        );
      }
      details.add(
        candidateId.isEmpty ? '$code: $message' : '$candidateId $code: $message',
      );
    }
    return '鉄道便をGTFS trip_idで確定できる経路候補がありません: '
        '${details.join(' / ')}';
  }
}

String normalizeRoutePreferenceForApi(String? preference) {
  if (preference == 'shortTime') return 'time';
  if (preference == null || preference.isEmpty) return 'cost';
  return preference;
}

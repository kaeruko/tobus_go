import 'dart:convert';

import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../constants.dart';
import '../core/api_client.dart';
import '../core/city_profile.dart';
import '../models/fare_models.dart';
import '../models/route_models.dart';
import '../models/transport_scope.dart';

class RouteSearchRequest {
  final LatLng origin;
  final LatLng destination;
  final String originName;
  final String destinationName;
  final String? originNameEn;
  final String? destinationNameEn;
  final DateTime startTime;
  final String? preference;
  final bool busOnly;
  final Set<String> transportScope;
  final String? farePolicyId;
  final bool acceptExperimentalTransferModel;

  RouteSearchRequest({
    required this.origin,
    required this.destination,
    required String originName,
    required String destinationName,
    String? originNameEn,
    String? destinationNameEn,
    required this.startTime,
    this.preference,
    this.busOnly = false,
    Set<String>? transportScope,
    this.farePolicyId,
    this.acceptExperimentalTransferModel = false,
  }) : transportScope = normalizeTransportScope(
         transportScope,
         busOnly: busOnly,
       ),
       originName = originName.trim(),
       destinationName = destinationName.trim(),
       originNameEn = _trimNullable(originNameEn),
       destinationNameEn = _trimNullable(destinationNameEn) {
    _validatePoint(origin, 'origin');
    _validatePoint(destination, 'destination');
  }

  Map<String, dynamic> toApiBody() {
    final localStartTime = startTime.toLocal();
    return {
      'alat': origin.latitude.toString(),
      'alon': origin.longitude.toString(),
      'blat': destination.latitude.toString(),
      'blon': destination.longitude.toString(),
      'pref': normalizeRoutePreferenceForApi(preference),
      'bus_only': busOnly,
      'transport_scope': transportScope.toList()..sort(),
      if (farePolicyId != null) 'fare_policy_id': farePolicyId,
      if (acceptExperimentalTransferModel ||
          farePolicyId == 'sendai_fureai_pass' ||
          farePolicyId == 'sendai_keiro_pass')
        'accept_experimental_transfer_model': acceptExperimentalTransferModel,
      'start_time':
          '${localStartTime.hour.toString().padLeft(2, '0')}:'
          '${localStartTime.minute.toString().padLeft(2, '0')}',
      'target_date_str':
          '${localStartTime.year.toString().padLeft(4, '0')}-'
          '${localStartTime.month.toString().padLeft(2, '0')}-'
          '${localStartTime.day.toString().padLeft(2, '0')}',
    };
  }

  static String? _trimNullable(String? value) {
    final normalized = value?.trim();
    return normalized == null || normalized.isEmpty ? null : normalized;
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
  final Map<String, FareQuote> fareByCandidateId;

  const RouteSearchResult({
    required this.candidates,
    required this.meta,
    required this.fareByCandidateId,
  });
}

abstract class RouteSearchService {
  Future<RouteSearchResult> search(RouteSearchRequest request);
}

class ApiRouteSearchService implements RouteSearchService {
  final String? cityKey;
  const ApiRouteSearchService({this.cityKey});
  String get _cityKey => cityKey ?? configuredCityKey;

  static final _inFlight = <String, Future<RouteSearchResult>>{};

  @override
  Future<RouteSearchResult> search(RouteSearchRequest request) async {
    final apiBody = request.toApiBody();
    if (_cityKey != 'tokyo') {
      // The new scope contract belongs to Tokyo. Other city backends retain
      // their existing bus_only wire behavior unchanged.
      apiBody.remove('transport_scope');
    }
    // Share only unfinished identical searches, including identity resolution.
    // Names affect the parsed result even though they are absent from /route.
    final key = jsonEncode([
      kApiBase,
      _cityKey,
      apiBody,
      request.originName,
      request.destinationName,
      request.originNameEn,
      request.destinationNameEn,
    ]);
    return _inFlight.putIfAbsent(
      key,
      () => _performSearch(request, apiBody).whenComplete(() {
        // A later explicit search must obtain a fresh realtime snapshot, and
        // a failed request must remain retryable.
        _inFlight.remove(key);
      }),
    );
  }

  Future<RouteSearchResult> _performSearch(
    RouteSearchRequest request,
    Map<String, dynamic> apiBody,
  ) async {
    final response = await ApiClient.post('/route', body: apiBody);

    var rawCandidates = response['candidates'];
    if (rawCandidates is! List) {
      throw const FormatException('route response is missing candidates list');
    }
    final rawMeta = response['meta'];
    if (rawMeta is! Map) {
      throw const FormatException('route response is missing meta object');
    }

    if (_cityKey == 'tokyo' && _containsRailCandidate(rawCandidates)) {
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
        throw StateError(_trainIdentityFailureMessage(rejections));
      }
      rawCandidates = resolvedCandidates;
    }

    final candidates = <Candidate>[];
    final fares = <String, FareQuote>{};
    final candidateIds = <String>{};
    for (final rawCandidate in rawCandidates) {
      if (rawCandidate is! Map) {
        throw const FormatException('route candidate must be an object');
      }
      final map = Map<String, dynamic>.from(rawCandidate);
      _validateResolvedBusIdentity(map);
      _validateResolvedRailIdentity(map);
      if (_cityKey == 'sendai') _validateSendaiPublishedRail(map);
      if (map['destination_name'] == null ||
          map['destination_name'].toString().trim().isEmpty) {
        map['destination_name'] = request.destinationName;
      }
      if (map['origin_name'] == null ||
          map['origin_name'].toString().trim().isEmpty) {
        map['origin_name'] = request.originName;
      }
      if (request.destinationNameEn != null) {
        map['destination_name_en'] = request.destinationNameEn;
      }
      if (request.originNameEn != null) {
        map['origin_name_en'] = request.originNameEn;
      }

      final candidate = Candidate.fromJson(map);
      if (candidate.id.isEmpty) {
        throw const FormatException('route candidate is missing id');
      }
      if (!candidateIds.add(candidate.id)) {
        throw FormatException('duplicate route candidate id: ${candidate.id}');
      }
      candidates.add(candidate);
      if (map['fare'] != null) {
        if (map['fare'] is! Map) {
          throw const FormatException('route fare must be an object');
        }
        fares[candidate.id] = FareQuote.fromJson(
          Map<String, dynamic>.from(map['fare']),
        );
      }
    }

    return RouteSearchResult(
      candidates: List.unmodifiable(candidates),
      meta: RouteMeta.fromJson(Map<String, dynamic>.from(rawMeta)),
      fareByCandidateId: Map.unmodifiable(fares),
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

  static void _validateResolvedBusIdentity(Map<String, dynamic> candidate) {
    final steps = candidate['steps'];
    if (steps is! List) {
      throw const FormatException('route candidate is missing steps list');
    }
    for (final rawStep in steps) {
      if (rawStep is! Map) {
        throw const FormatException('route step must be an object');
      }
      if (rawStep['kind'] != 'bus') continue;
      final stepId = rawStep['step_id']?.toString() ?? '';
      final tripId = rawStep['trip_id']?.toString().trim() ?? '';
      final routeId = rawStep['route_id']?.toString().trim() ?? '';
      if (tripId.isEmpty) {
        throw FormatException(
          'bus route step is missing exact GTFS trip_id: $stepId',
        );
      }
      if (routeId.isEmpty) {
        throw FormatException(
          'bus route step is missing exact GTFS route_id: $stepId',
        );
      }
    }
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
      final boardingMinutes = rawStep['boarding_minutes'];
      if (boardingMinutes is! num ||
          !boardingMinutes.isFinite ||
          boardingMinutes != boardingMinutes.roundToDouble() ||
          boardingMinutes < 0) {
        throw FormatException(
          'rail route step is missing valid boarding_minutes: $stepId',
        );
      }
      final stops = rawStep['stops'];
      if (stops is! List || stops.length < 2) {
        throw FormatException('rail route step is missing stop IDs: $stepId');
      }
      for (var index = 0; index < stops.length; index++) {
        final stop = stops[index];
        if (stop is! Map) {
          throw FormatException(
            'rail route step contains invalid stop: '
            'stepId=$stepId, index=$index',
          );
        }
        final stopId = (stop['id'] ?? stop['stop_id'])?.toString().trim();
        if (stopId == null || stopId.isEmpty) {
          throw FormatException(
            'rail route step stop is missing canonical stop ID: '
            'stepId=$stepId, index=$index',
          );
        }
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
        candidateId.isEmpty
            ? '$code: $message'
            : '$candidateId $code: $message',
      );
    }
    return '鉄道便をGTFS trip_idで確定できる経路候補がありません: '
        '${details.join(' / ')}';
  }

  static void _validateSendaiPublishedRail(Map<String, dynamic> candidate) {
    for (final step in candidate['steps'] as List) {
      if (step['kind'] != 'rail') continue;
      final details = step['planning_details'];
      if (!step['trip_id'].toString().startsWith('sendai_subway:') ||
          !step['route_id'].toString().startsWith('sendai_subway:') ||
          details is! Map ||
          details['departure'] is! Map ||
          details['arrival'] is! Map ||
          details['departure']['basis'] != 'published_departure_minute' ||
          details['arrival']['basis'] != 'published_clock_arrival_proxy' ||
          details['departure_provenance'] is! Map ||
          details['arrival_provenance'] is! Map) {
        throw FormatException(
          'Sendai rail lacks published departure / estimated arrival provenance: ${step['step_id']}',
        );
      }
    }
  }
}

String normalizeRoutePreferenceForApi(String? preference) {
  if (preference == 'shortTime') return 'time';
  if (preference == null || preference.isEmpty) return 'cost';
  return preference;
}

import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../logic/replan_anchor.dart';
import '../logic/replan_debug_log.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import 'route_search_service.dart';

class RouteReplanRequest {
  final ReplanAnchor anchor;
  final String activeStepId;
  final String originalCandidateId;
  final LatLng destination;
  final String destinationName;
  final String? preference;

  RouteReplanRequest({
    required this.anchor,
    required String activeStepId,
    required String originalCandidateId,
    required this.destination,
    required String destinationName,
    this.preference,
  }) : activeStepId = activeStepId.trim(),
       originalCandidateId = originalCandidateId.trim(),
       destinationName = destinationName.trim() {
    if (this.activeStepId.isEmpty) {
      throw ArgumentError.value(activeStepId, 'activeStepId', 'must not be empty');
    }
    if (this.originalCandidateId.isEmpty) {
      throw ArgumentError.value(originalCandidateId, 'originalCandidateId', 'must not be empty');
    }
    if (this.destinationName.isEmpty) {
      throw ArgumentError.value(destinationName, 'destinationName', 'must not be empty');
    }
    if (!destination.latitude.isFinite || !destination.longitude.isFinite) {
      throw ArgumentError.value(destination, 'destination', 'must be finite');
    }
  }
}

/// Returns true only when both requests describe the exact same replan state.
///
/// In particular, [ReplanAnchor.availableAt] is part of the identity. A newer
/// realtime ETA therefore invalidates a preview that was searched with the old
/// time even when the station/stop itself has not changed.
bool sameRouteReplanRequestState(
  RouteReplanRequest a,
  RouteReplanRequest b,
) {
  return a.activeStepId == b.activeStepId &&
      a.originalCandidateId == b.originalCandidateId &&
      a.destination == b.destination &&
      a.destinationName == b.destinationName &&
      a.preference == b.preference &&
      a.anchor.source == b.anchor.source &&
      a.anchor.routeStepId == b.anchor.routeStepId &&
      a.anchor.stopId == b.anchor.stopId &&
      a.anchor.placeName == b.anchor.placeName &&
      a.anchor.point == b.anchor.point &&
      a.anchor.availableAt.isAtSameMomentAs(b.anchor.availableAt);
}

class RouteReplanRequestBuilder {
  const RouteReplanRequestBuilder._();

  static RouteReplanRequest build({
    required Trip trip,
    required String activeStepId,
    required ReplanAnchor anchor,
  }) {
    final stepId = activeStepId.trim();
    if (stepId.isEmpty) {
      throw ArgumentError.value(activeStepId, 'activeStepId', 'must not be empty');
    }
    final anchorStepId = anchor.routeStepId;
    if (anchorStepId != null && anchorStepId != stepId) {
      throw StateError(
        '再探索起点が現在stepと一致しません: anchor=$anchorStepId, active=$stepId',
      );
    }

    final matches = <Candidate>[];
    for (final leg in trip.legs) {
      final candidate = leg.candidate;
      if (candidate.steps.any((step) => step.stepId == stepId)) {
        matches.add(candidate);
      }
    }
    if (matches.length != 1) {
      throw StateError(
        '再探索対象のstepをTrip内で一意に特定できません: stepId=$stepId, matches=${matches.length}',
      );
    }

    final candidate = matches.single;
    final destination = candidate.destinationCoords;
    if (destination == null) {
      throw StateError('再探索先の目的地座標がありません: candidate=${candidate.id}');
    }
    final destinationName = candidate.destinationName?.trim();
    if (destinationName == null || destinationName.isEmpty) {
      throw StateError('再探索先の目的地名がありません: candidate=${candidate.id}');
    }

    return RouteReplanRequest(
      anchor: anchor,
      activeStepId: stepId,
      originalCandidateId: candidate.id,
      destination: destination,
      destinationName: destinationName,
      preference: candidate.preference,
    );
  }
}

class RouteReplanner {
  final RouteSearchService _routeSearchService;

  const RouteReplanner(this._routeSearchService);

  Future<RouteSearchResult> replan(RouteReplanRequest request) async {
    ReplanDebugLog.emit('replan_search_start', {
      'activeStepId': request.activeStepId,
      'originalCandidateId': request.originalCandidateId,
      'destinationName': request.destinationName,
      'destinationLat': request.destination.latitude,
      'destinationLng': request.destination.longitude,
      'preference': request.preference,
      ...ReplanDebugLog.anchorFields(request.anchor),
    });

    try {
      final result = await _routeSearchService.search(
        RouteSearchRequest(
          origin: request.anchor.point,
          destination: request.destination,
          originName: request.anchor.placeName,
          destinationName: request.destinationName,
          startTime: request.anchor.availableAt,
          preference: request.preference,
        ),
      );
      ReplanDebugLog.emit('replan_search_success', {
        'activeStepId': request.activeStepId,
        'candidateCount': result.candidates.length,
        'candidateIds': result.candidates.map((candidate) => candidate.id).toList(),
        ...ReplanDebugLog.anchorFields(request.anchor),
      });
      return result;
    } catch (error) {
      ReplanDebugLog.emit('replan_search_error', {
        'activeStepId': request.activeStepId,
        'error': error.toString(),
        ...ReplanDebugLog.anchorFields(request.anchor),
      });
      rethrow;
    }
  }
}

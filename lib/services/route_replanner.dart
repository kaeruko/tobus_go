import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../logic/replan_anchor.dart';
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

  Future<RouteSearchResult> replan(RouteReplanRequest request) {
    return _routeSearchService.search(
      RouteSearchRequest(
        origin: request.anchor.point,
        destination: request.destination,
        originName: request.anchor.placeName,
        destinationName: request.destinationName,
        startTime: request.anchor.availableAt,
        preference: request.preference,
      ),
    );
  }
}

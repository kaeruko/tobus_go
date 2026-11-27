import '../models/route_models.dart';

/// Match the ordered transit itinerary, not its rank, trip IDs or clocks.
/// Each ride must have a known route ID and a complete ordered stop-ID
/// sequence. Missing or ambiguous identity is not a verified match.
/// Waiting and walking are recalculated by the route search.
Candidate? matchingRefreshedRoute(
  Candidate original,
  Iterable<Candidate> candidates,
) {
  final originalRides = original.steps.where((step) => step.isRide).toList();
  if (originalRides.isEmpty) return null;

  for (final candidate in candidates) {
    final rides = candidate.steps.where((step) => step.isRide).toList();
    if (rides.length != originalRides.length) continue;
    var matches = true;
    for (var i = 0; i < rides.length; i++) {
      if (!_sameRide(originalRides[i], rides[i])) {
        matches = false;
        break;
      }
    }
    if (matches) return candidate;
  }
  return null;
}

bool _sameRide(StepSeg a, StepSeg b) {
  final routeId = a.routeId;
  if (routeId == null ||
      routeId.trim().isEmpty ||
      routeId != b.routeId ||
      a.kind != b.kind ||
      a.operatorId != b.operatorId ||
      a.directionId != b.directionId ||
      a.departureStopId != b.departureStopId ||
      a.arrivalPoleId != b.arrivalPoleId ||
      a.stops.length < 2 ||
      a.stops.length != b.stops.length) {
    return false;
  }

  // Tokyo bus poles are explicit; ordered station IDs identify rail direction
  // even on existing rail responses without separate direction/pole fields.
  if (a.kind == 'bus' &&
      (a.departureStopId.trim().isEmpty || a.arrivalPoleId.trim().isEmpty)) {
    return false;
  }

  for (var i = 0; i < a.stops.length; i++) {
    final id = a.stops[i].stopId;
    if (id == null || id.trim().isEmpty || id != b.stops[i].stopId) {
      return false;
    }
  }
  return true;
}

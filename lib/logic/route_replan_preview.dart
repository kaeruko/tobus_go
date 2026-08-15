import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../services/route_replanner.dart';
import '../services/route_search_service.dart';

class RouteReplanPreview {
  final RouteReplanRequest request;
  final Candidate originalCandidate;
  final List<Candidate> newCandidates;
  final List<LatLng> originalFuturePoints;

  const RouteReplanPreview({
    required this.request,
    required this.originalCandidate,
    required this.newCandidates,
    required this.originalFuturePoints,
  });

  static RouteReplanPreview build({
    required Trip trip,
    required RouteReplanRequest request,
    required RouteSearchResult result,
  }) {
    final matches = <Candidate>[];
    for (final leg in trip.legs) {
      final candidate = leg.candidate;
      if (candidate.steps.any((step) => step.stepId == request.activeStepId)) {
        matches.add(candidate);
      }
    }
    if (matches.length != 1) {
      throw StateError(
        '比較対象の現在経路をTrip内で一意に特定できません: '
        'stepId=${request.activeStepId}, matches=${matches.length}',
      );
    }

    final original = matches.single;
    if (original.id != request.originalCandidateId) {
      throw StateError(
        '再探索リクエストのCandidateが現在経路と一致しません: '
        '${request.originalCandidateId} != ${original.id}',
      );
    }

    return RouteReplanPreview(
      request: request,
      originalCandidate: original,
      newCandidates: List.unmodifiable(result.candidates),
      originalFuturePoints: List.unmodifiable(
        _buildOriginalFuturePoints(original, request),
      ),
    );
  }

  List<LatLng> pointsForNewCandidate(Candidate candidate) {
    final detailed = candidate.points;
    if (detailed.isNotEmpty) {
      final points = <LatLng>[];
      _appendUnique(points, request.anchor.point);
      for (final point in detailed) {
        _appendUnique(points, point);
      }
      _appendUnique(points, request.destination);
      return List.unmodifiable(points);
    }

    final points = <LatLng>[];
    _appendUnique(points, request.anchor.point);
    for (final step in candidate.steps) {
      for (final stop in step.stops) {
        _appendUnique(points, stop.point);
      }
    }
    _appendUnique(points, request.destination);
    return List.unmodifiable(points);
  }

  String get originalArrivalLabel => arrivalLabel(originalCandidate);

  static String arrivalLabel(Candidate candidate) {
    final direct = candidate.arrivalTime?.trim();
    if (direct != null && direct.isNotEmpty) return direct;
    for (final step in candidate.steps.reversed) {
      final value = step.arrivalTime?.trim();
      if (value != null && value.isNotEmpty) return value;
    }
    return '時刻不明';
  }

  static String lineSummary(Candidate candidate) {
    final lines = candidate.lines
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList();
    if (lines.isNotEmpty) return lines.join(' → ');

    final rideTitles = <String>[];
    for (final step in candidate.steps) {
      if (!step.isRide) continue;
      final title = step.title.trim();
      if (title.isEmpty) continue;
      if (rideTitles.isEmpty || rideTitles.last != title) {
        rideTitles.add(title);
      }
    }
    return rideTitles.isEmpty ? '徒歩のみ' : rideTitles.join(' → ');
  }

  static String formatClock(DateTime dateTime) {
    final local = dateTime.toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }

  static List<LatLng> _buildOriginalFuturePoints(
    Candidate candidate,
    RouteReplanRequest request,
  ) {
    final activeIndex = candidate.steps.indexWhere(
      (step) => step.stepId == request.activeStepId,
    );
    if (activeIndex < 0) {
      throw StateError(
        '現在stepが比較対象Candidateにありません: ${request.activeStepId}',
      );
    }

    final points = <LatLng>[];
    _appendUnique(points, request.anchor.point);

    for (var stepIndex = activeIndex;
        stepIndex < candidate.steps.length;
        stepIndex++) {
      final step = candidate.steps[stepIndex];
      if (step.stops.isEmpty) continue;

      var stopStartIndex = 0;
      if (stepIndex == activeIndex &&
          step.isRide &&
          request.anchor.routeStepId == step.stepId) {
        stopStartIndex = _findAnchorStopIndex(step.stops, request);
        if (stopStartIndex < 0) {
          throw StateError(
            '再探索起点が現在の乗車stepの停車地点一覧にありません: '
            'stepId=${step.stepId}, anchor=${request.anchor.placeName}',
          );
        }
      }

      for (var stopIndex = stopStartIndex;
          stopIndex < step.stops.length;
          stopIndex++) {
        _appendUnique(points, step.stops[stopIndex].point);
      }
    }

    _appendUnique(points, request.destination);
    return points;
  }

  static int _findAnchorStopIndex(
    List<StopPoint> stops,
    RouteReplanRequest request,
  ) {
    final anchorStopId = request.anchor.stopId;
    if (anchorStopId != null && anchorStopId.isNotEmpty) {
      final byId = stops.indexWhere((stop) => stop.stopId == anchorStopId);
      if (byId >= 0) return byId;
    }

    final byPoint = stops.indexWhere(
      (stop) => _samePoint(stop.point, request.anchor.point),
    );
    if (byPoint >= 0) return byPoint;

    return stops.indexWhere(
      (stop) => stop.name.trim() == request.anchor.placeName.trim(),
    );
  }

  static void _appendUnique(List<LatLng> points, LatLng point) {
    if (points.isEmpty || !_samePoint(points.last, point)) {
      points.add(point);
    }
  }

  static bool _samePoint(LatLng a, LatLng b) {
    const epsilon = 0.0000001;
    return (a.latitude - b.latitude).abs() <= epsilon &&
        (a.longitude - b.longitude).abs() <= epsilon;
  }
}

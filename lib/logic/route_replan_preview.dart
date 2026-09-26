import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../models/route_models.dart';
import 'replan_debug_log.dart';
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

    final newCandidates = _removeDominatedCurrentRideReboards(
      original: original,
      request: request,
      candidates: result.candidates,
    );

    return RouteReplanPreview(
      request: request,
      originalCandidate: original,
      newCandidates: List.unmodifiable(newCandidates),
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

  static List<Candidate> _removeDominatedCurrentRideReboards({
    required Candidate original,
    required RouteReplanRequest request,
    required List<Candidate> candidates,
  }) {
    if (request.anchor.source != ReplanAnchorSource.currentTransitPlace &&
        request.anchor.source != ReplanAnchorSource.predictedNextTransitPlace) {
      return List<Candidate>.from(candidates);
    }

    final activeMatches = original.steps
        .where((step) => step.stepId == request.activeStepId)
        .toList(growable: false);
    if (activeMatches.length != 1) {
      throw StateError(
        '再探索中の乗車stepを現在経路で一意に特定できません: '
        'stepId=${request.activeStepId}, matches=${activeMatches.length}',
      );
    }
    final activeRide = activeMatches.single;
    if (!activeRide.isRide || activeRide.stops.length < 2) {
      return List<Candidate>.from(candidates);
    }

    final anchorIndex = _findAnchorStopIndex(activeRide.stops, request);
    if (anchorIndex < 0) {
      throw StateError(
        '再探索起点が現在乗車中の停車地点一覧にありません: '
        'stepId=${activeRide.stepId}, anchor=${request.anchor.placeName}',
      );
    }

    final kept = <Candidate>[];
    final filteredIds = <String>[];
    for (final candidate in candidates) {
      if (_isDominatedCurrentRideReboard(
        candidate: candidate,
        activeRide: activeRide,
        anchorIndex: anchorIndex,
        request: request,
      )) {
        filteredIds.add(candidate.id);
      } else {
        kept.add(candidate);
      }
    }

    if (filteredIds.isNotEmpty) {
      ReplanDebugLog.emit('replan_preview_dominated_reboard_filtered', {
        'activeStepId': request.activeStepId,
        'anchorPlace': request.anchor.placeName,
        'routeId': activeRide.routeId,
        'filteredCandidateIds': filteredIds,
      });
    }
    return kept;
  }

  static bool _isDominatedCurrentRideReboard({
    required Candidate candidate,
    required StepSeg activeRide,
    required int anchorIndex,
    required RouteReplanRequest request,
  }) {
    final firstRideIndex = candidate.steps.indexWhere((step) => step.isRide);
    if (firstRideIndex < 0) return false;

    for (var index = 0; index < firstRideIndex; index++) {
      final step = candidate.steps[index];
      if (step.kind != 'wait' || !_waitIsAtAnchor(step, request)) {
        return false;
      }
    }

    final reboard = candidate.steps[firstRideIndex];
    if (reboard.kind != activeRide.kind) return false;

    final activeRouteId = activeRide.routeId?.trim();
    final reboardRouteId = reboard.routeId?.trim();
    if (activeRouteId == null ||
        activeRouteId.isEmpty ||
        reboardRouteId == null ||
        reboardRouteId.isEmpty ||
        activeRouteId != reboardRouteId) {
      return false;
    }

    if (activeRide.title.trim() != reboard.title.trim()) {
      return false;
    }

    final activeDirection = activeRide.directionId?.trim();
    final reboardDirection = reboard.directionId?.trim();
    if (activeDirection != null &&
        activeDirection.isNotEmpty &&
        reboardDirection != null &&
        reboardDirection.isNotEmpty &&
        activeDirection != reboardDirection) {
      return false;
    }

    if (!_rideStartsAtAnchor(reboard, request)) {
      return false;
    }

    return _rideDestinationIsDownstream(
      activeRide: activeRide,
      reboard: reboard,
      anchorIndex: anchorIndex,
    );
  }

  static bool _waitIsAtAnchor(
    StepSeg step,
    RouteReplanRequest request,
  ) {
    final anchor = request.anchor.placeName.trim();
    final names = <String?>[
      step.fromName,
      step.toName,
      step.place,
    ];
    final present = names
        .whereType<String>()
        .map((name) => name.trim())
        .where((name) => name.isNotEmpty)
        .toList(growable: false);
    return present.isNotEmpty && present.every((name) => name == anchor);
  }

  static bool _rideStartsAtAnchor(
    StepSeg ride,
    RouteReplanRequest request,
  ) {
    if (ride.stops.isNotEmpty) {
      return _stopMatchesAnchor(ride.stops.first, request);
    }
    return ride.fromName?.trim() == request.anchor.placeName.trim();
  }

  static bool _rideDestinationIsDownstream({
    required StepSeg activeRide,
    required StepSeg reboard,
    required int anchorIndex,
  }) {
    final destinationStop = reboard.stops.isEmpty ? null : reboard.stops.last;
    final destinationName =
        destinationStop?.name.trim() ?? reboard.toName?.trim() ?? '';
    final destinationId = destinationStop?.stopId?.trim();

    if ((destinationId == null || destinationId.isEmpty) &&
        destinationName.isEmpty) {
      return false;
    }

    for (var index = anchorIndex + 1;
        index < activeRide.stops.length;
        index++) {
      final stop = activeRide.stops[index];
      final stopId = stop.stopId?.trim();
      if (destinationId != null &&
          destinationId.isNotEmpty &&
          stopId != null &&
          stopId.isNotEmpty) {
        if (destinationId == stopId) return true;
        continue;
      }
      if (destinationName.isNotEmpty &&
          stop.name.trim() == destinationName) {
        return true;
      }
    }
    return false;
  }

  static bool _stopMatchesAnchor(
    StopPoint stop,
    RouteReplanRequest request,
  ) {
    final anchorStopId = request.anchor.stopId?.trim();
    final stopId = stop.stopId?.trim();
    if (anchorStopId != null &&
        anchorStopId.isNotEmpty &&
        stopId != null &&
        stopId.isNotEmpty) {
      return anchorStopId == stopId;
    }
    if (stop.name.trim() == request.anchor.placeName.trim()) {
      return true;
    }
    return _samePoint(stop.point, request.anchor.point);
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

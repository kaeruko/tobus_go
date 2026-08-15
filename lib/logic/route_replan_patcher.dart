import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../services/route_replanner.dart';

class RouteReplanPatch {
  final int legIndex;
  final String expectedCandidateId;
  final String expectedActiveStepId;
  final List<Leg> legs;
  final List<ScheduleEntry> schedule;

  const RouteReplanPatch({
    required this.legIndex,
    required this.expectedCandidateId,
    required this.expectedActiveStepId,
    required this.legs,
    required this.schedule,
  });
}

/// Applies a selected replan candidate to the current route while preserving
/// the route history before the non-GPS [RouteReplanRequest.anchor].
///
/// This patcher intentionally changes only route-generated entries in the
/// active leg. Manual/group entries and every other leg are preserved exactly.
class RouteReplanPatcher {
  const RouteReplanPatcher._();

  static RouteReplanPatch build({
    required Trip trip,
    required RouteReplanRequest request,
    required Candidate selectedCandidate,
  }) {
    final position = _findActiveStep(trip, request);
    final oldLeg = trip.legs[position.legIndex];
    final oldCandidate = oldLeg.candidate;

    final retainedSteps = _retainedSteps(
      candidate: oldCandidate,
      activeStepIndex: position.stepIndex,
      request: request,
    );
    final combinedSteps = <StepSeg>[
      ...retainedSteps,
      ...selectedCandidate.steps,
    ];
    _requireUniqueStepIds(combinedSteps);

    final combinedCandidate = _buildCombinedCandidate(
      original: oldCandidate,
      selected: selectedCandidate,
      steps: combinedSteps,
    );
    final replacementLeg = Leg(
      direction: oldLeg.direction,
      status: oldLeg.status,
      candidate: combinedCandidate,
      confirmedAt: oldLeg.confirmedAt,
    );
    final legs = List<Leg>.from(trip.legs);
    legs[position.legIndex] = replacementLeg;

    final retainedStepIds = retainedSteps.map((step) => step.stepId).toSet();
    final schedule = _buildSchedule(
      trip: trip,
      targetLegIndex: position.legIndex,
      retainedStepIds: retainedStepIds,
      retainedActiveStep: retainedSteps
          .where((step) => step.stepId == request.activeStepId)
          .firstOrNull,
      request: request,
      selectedCandidate: selectedCandidate,
    );

    // Constructing Trip is a cheap invariant check: duplicate route step IDs or
    // other schema-level inconsistencies must fail before any Firestore write.
    Trip(
      schemaVersion: trip.schemaVersion,
      tripType: trip.tripType,
      id: trip.id,
      joinCode: trip.joinCode,
      leaderId: trip.leaderId,
      title: trip.title,
      travelPhase: trip.travelPhase,
      date: trip.date,
      plannedDepartureAt: trip.plannedDepartureAt,
      actualDepartureAt: trip.actualDepartureAt,
      legs: legs,
      schedule: schedule,
      participants: trip.participants,
      memberIds: trip.memberIds,
      completedLegIndex: trip.completedLegIndex,
      staffNotes: trip.staffNotes,
    );

    return RouteReplanPatch(
      legIndex: position.legIndex,
      expectedCandidateId: request.originalCandidateId,
      expectedActiveStepId: request.activeStepId,
      legs: List.unmodifiable(legs),
      schedule: List.unmodifiable(schedule),
    );
  }

  static _ActiveStepPosition _findActiveStep(
    Trip trip,
    RouteReplanRequest request,
  ) {
    final matches = <_ActiveStepPosition>[];
    for (var legIndex = 0; legIndex < trip.legs.length; legIndex++) {
      final candidate = trip.legs[legIndex].candidate;
      for (var stepIndex = 0; stepIndex < candidate.steps.length; stepIndex++) {
        if (candidate.steps[stepIndex].stepId == request.activeStepId) {
          matches.add(
            _ActiveStepPosition(legIndex: legIndex, stepIndex: stepIndex),
          );
        }
      }
    }
    if (matches.length != 1) {
      throw StateError(
        '再探索適用対象のstepをTrip内で一意に特定できません: '
        'stepId=${request.activeStepId}, matches=${matches.length}',
      );
    }
    final position = matches.single;
    final candidate = trip.legs[position.legIndex].candidate;
    if (candidate.id != request.originalCandidateId) {
      throw StateError(
        '再探索適用対象のCandidateが変化しています: '
        '${request.originalCandidateId} != ${candidate.id}',
      );
    }
    return position;
  }

  static List<StepSeg> _retainedSteps({
    required Candidate candidate,
    required int activeStepIndex,
    required RouteReplanRequest request,
  }) {
    final activeStep = candidate.steps[activeStepIndex];
    switch (request.anchor.source) {
      case ReplanAnchorSource.tripOrigin:
        if (activeStepIndex != 0) {
          throw StateError(
            'tripOriginからの再探索なのに現在stepが先頭ではありません: '
            'stepId=${activeStep.stepId}, index=$activeStepIndex',
          );
        }
        return const [];
      case ReplanAnchorSource.lastConfirmedTransitPlace:
        if (activeStep.isRide) {
          throw StateError(
            'lastConfirmedTransitPlace起点なのに現在stepが乗車区間です: '
            '${activeStep.stepId}',
          );
        }
        return List.unmodifiable(candidate.steps.take(activeStepIndex));
      case ReplanAnchorSource.currentTransitPlace:
      case ReplanAnchorSource.predictedNextTransitPlace:
        if (!activeStep.isRide) {
          throw StateError(
            '乗車中の再探索起点なのに現在stepが乗車区間ではありません: '
            '${activeStep.stepId}',
          );
        }
        if (request.anchor.routeStepId != activeStep.stepId) {
          throw StateError(
            '再探索起点のrouteStepIdが現在乗車stepと一致しません: '
            '${request.anchor.routeStepId} != ${activeStep.stepId}',
          );
        }
        final truncated = _truncateRideAtAnchor(activeStep, request);
        return List.unmodifiable([
          ...candidate.steps.take(activeStepIndex),
          truncated,
        ]);
    }
  }

  static StepSeg _truncateRideAtAnchor(
    StepSeg step,
    RouteReplanRequest request,
  ) {
    if (step.stops.isEmpty) {
      throw StateError('乗車区間に停車地点がないため途中経路を確定できません: ${step.stepId}');
    }
    final anchorIndex = _findAnchorStopIndex(step.stops, request);
    if (anchorIndex < 0) {
      throw StateError(
        '再探索起点が現在乗車stepの停車地点一覧にありません: '
        'stepId=${step.stepId}, anchor=${request.anchor.placeName}',
      );
    }

    final truncatedStops = <StopPoint>[];
    for (var index = 0; index <= anchorIndex; index++) {
      final stop = step.stops[index];
      truncatedStops.add(
        StopPoint(
          name: stop.name,
          point: stop.point,
          stopId: stop.stopId,
          isOrigin: index == 0,
          isDestination: index == anchorIndex,
        ),
      );
    }

    final arrivalAt = request.anchor.availableAt.toLocal();
    final arrivalClock = _formatClock(arrivalAt);
    final departureClock = step.departureTime?.trim();
    if (departureClock == null || departureClock.isEmpty) {
      throw StateError(
        '途中までの乗車履歴を確定するための乗車時刻がありません: ${step.stepId}',
      );
    }
    final minutes = _forwardClockMinutes(departureClock, arrivalClock);

    return StepSeg(
      stepId: step.stepId,
      kind: step.kind,
      title: step.title,
      fromName: step.fromName,
      toName: request.anchor.placeName,
      stops: List.unmodifiable(truncatedStops),
      minutes: minutes,
      meters: step.meters,
      fareYen: null,
      departureTime: step.departureTime,
      arrivalTime: arrivalClock,
      startLabel: step.startLabel,
      endLabel: step.endLabel,
      place: step.place,
      routeId: step.routeId,
      tripId: step.tripId,
      directionId: step.directionId,
      edges: step.edges,
      departureStopId: step.departureStopId,
      arrivalPoleId: request.anchor.stopId ?? '',
    );
  }

  static List<ScheduleEntry> _buildSchedule({
    required Trip trip,
    required int targetLegIndex,
    required Set<String> retainedStepIds,
    required StepSeg? retainedActiveStep,
    required RouteReplanRequest request,
    required Candidate selectedCandidate,
  }) {
    final retained = <ScheduleEntry>[];
    for (final entry in trip.schedule) {
      if (entry.legIndex != targetLegIndex ||
          entry.generatedBy == ScheduleEntrySource.manual) {
        retained.add(entry);
        continue;
      }
      final routeStepId = entry.routeStepId;
      if (routeStepId == null || !retainedStepIds.contains(routeStepId)) {
        continue;
      }
      if (routeStepId == request.activeStepId &&
          retainedActiveStep != null &&
          entry.routeRole == 'arrival') {
        retained.add(
          ScheduleEntry(
            id: entry.id,
            plannedAt: request.anchor.availableAt,
            label: '${_transportEmoji(retainedActiveStep.kind)}'
                '${retainedActiveStep.title} ${request.anchor.placeName}に着く',
            description: entry.description,
            itemKind: entry.itemKind,
            legIndex: entry.legIndex,
            generatedBy: entry.generatedBy,
            routeStepId: entry.routeStepId,
            routeRole: entry.routeRole,
          ),
        );
      } else {
        retained.add(entry);
      }
    }

    final suffix = createScheduleFromRoute(
      selectedCandidate,
      startDateTime: request.anchor.availableAt,
      legIndex: targetLegIndex,
    );
    retained.addAll(suffix);
    sortScheduleEntries(retained);
    return retained;
  }

  static Candidate _buildCombinedCandidate({
    required Candidate original,
    required Candidate selected,
    required List<StepSeg> steps,
  }) {
    final lines = <String>[];
    for (final step in steps) {
      if (!step.isRide) continue;
      final title = step.title.trim();
      if (title.isNotEmpty && !lines.contains(title)) {
        lines.add(title);
      }
    }
    for (final line in selected.lines) {
      final trimmed = line.trim();
      if (trimmed.isNotEmpty && !lines.contains(trimmed)) {
        lines.add(trimmed);
      }
    }

    final rides = steps.where((step) => step.isRide).length;
    final walks = steps.where((step) => step.kind == 'walk').length;
    final totalTime = steps.fold<int>(0, (sum, step) => sum + step.minutes);
    final points = <LatLng>[];
    for (final step in steps) {
      for (final stop in step.stops) {
        _appendUniquePoint(points, stop.point);
      }
    }
    for (final point in selected.points) {
      _appendUniquePoint(points, point);
    }

    return Candidate(
      id: '${original.id}::replan::${selected.id}',
      lines: List.unmodifiable(lines),
      rides: rides,
      walks: walks,
      boards: rides,
      transfers: rides > 0 ? rides - 1 : 0,
      total: selected.total,
      totalTime: totalTime,
      steps: List.unmodifiable(steps),
      points: List.unmodifiable(points),
      originName: original.originName,
      destinationName: original.destinationName ?? selected.destinationName,
      preference: original.preference ?? selected.preference,
      departureDate: original.departureDate,
      isFutureSuggestion: false,
      originCoords: original.originCoords,
      destinationCoords: original.destinationCoords ?? selected.destinationCoords,
      arrivalTime: selected.arrivalTime,
    );
  }

  static int _findAnchorStopIndex(
    List<StopPoint> stops,
    RouteReplanRequest request,
  ) {
    final stopId = request.anchor.stopId;
    if (stopId != null && stopId.isNotEmpty) {
      final byId = stops.indexWhere((stop) => stop.stopId == stopId);
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

  static int _forwardClockMinutes(String from, String to) {
    final fromMinutes = _parseClock(from);
    var toMinutes = _parseClock(to);
    while (toMinutes < fromMinutes) {
      toMinutes += 24 * 60;
    }
    return toMinutes - fromMinutes;
  }

  static int _parseClock(String value) {
    final parts = value.split(':');
    if (parts.length != 2) {
      throw FormatException('HH:mm形式ではありません: $value');
    }
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null || hour < 0 || minute < 0 || minute >= 60) {
      throw FormatException('時刻を解釈できません: $value');
    }
    return hour * 60 + minute;
  }

  static String _formatClock(DateTime value) {
    return '${value.hour.toString().padLeft(2, '0')}:'
        '${value.minute.toString().padLeft(2, '0')}';
  }

  static String _transportEmoji(String kind) {
    switch (kind) {
      case 'bus':
        return '🚌';
      case 'rail':
        return '🚇';
      default:
        throw StateError('乗車到着ラベルの未対応kindです: $kind');
    }
  }

  static void _requireUniqueStepIds(List<StepSeg> steps) {
    final ids = <String>{};
    for (final step in steps) {
      if (!ids.add(step.stepId)) {
        throw StateError('再探索適用後のroute step IDが重複しています: ${step.stepId}');
      }
    }
  }

  static void _appendUniquePoint(List<LatLng> points, LatLng point) {
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

class _ActiveStepPosition {
  final int legIndex;
  final int stepIndex;

  const _ActiveStepPosition({
    required this.legIndex,
    required this.stepIndex,
  });
}

extension _FirstOrNullExtension<T> on Iterable<T> {
  T? get firstOrNull {
    final iterator = this.iterator;
    if (!iterator.moveNext()) return null;
    return iterator.current;
  }
}

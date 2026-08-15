import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import 'replan_anchor.dart';

enum DelayImpactBasis {
  ridingPrediction,
  confirmedTransferPlace,
}

class DelayImpact {
  final int legIndex;
  final String currentStepId;
  final String currentRideTitle;
  final String currentAlightingPlaceName;
  final DateTime plannedArrivalAt;
  final DateTime predictedArrivalAt;
  final Duration delay;
  final String nextRideStepId;
  final String nextRideTitle;
  final DateTime nextDepartureAt;
  final int transferWalkMinutes;
  final DateTime earliestTransferReadyAt;
  final bool nextTransferFeasible;
  final Duration missedBy;
  final DelayImpactBasis basis;

  const DelayImpact({
    required this.legIndex,
    required this.currentStepId,
    required this.currentRideTitle,
    required this.currentAlightingPlaceName,
    required this.plannedArrivalAt,
    required this.predictedArrivalAt,
    required this.delay,
    required this.nextRideStepId,
    required this.nextRideTitle,
    required this.nextDepartureAt,
    required this.transferWalkMinutes,
    required this.earliestTransferReadyAt,
    required this.nextTransferFeasible,
    required this.missedBy,
    this.basis = DelayImpactBasis.ridingPrediction,
  });

  bool get requiresReplan => !nextTransferFeasible;
}

/// Evaluates whether the next planned transit boarding is still reachable.
///
/// While riding, the basis is the conservative realtime estimate for the
/// planned alighting point. After alighting, GPS is still not used: the last
/// confirmed transit place plus the full explicit transfer-walk duration is
/// used. This intentionally does not pretend to know how far through a walk the
/// traveler has progressed.
///
/// No arbitrary transfer buffer is added. Planned wait steps are slack, not a
/// minimum transfer requirement. Missing or ambiguous route/schedule facts fail
/// instead of being guessed.
class DelayImpactAnalyzer {
  const DelayImpactAnalyzer._();

  static DelayImpact? analyze({
    required Trip trip,
    required RidingTransitObservation observation,
  }) {
    final active = _findStep(trip, observation.stepId);
    final candidate = trip.legs[active.legIndex].candidate;
    final currentStep = candidate.steps[active.stepIndex];
    if (!currentStep.isRide) {
      throw StateError(
        'RidingTransitObservationが乗車step以外を参照しています: '
        'stepId=${observation.stepId}, kind=${currentStep.kind}',
      );
    }

    final nextRideIndex = _findNextRideIndex(
      candidate.steps,
      active.stepIndex + 1,
    );
    if (nextRideIndex == null) {
      return null;
    }

    final predictedArrivalAt = observation.predictedDestinationAvailableAt;
    if (predictedArrivalAt == null) {
      throw StateError(
        '次の乗換えを判定するための降車地点到着見込みがありません: '
        'stepId=${observation.stepId}',
      );
    }

    return _buildImpact(
      trip: trip,
      legIndex: active.legIndex,
      previousRideIndex: active.stepIndex,
      nextRideIndex: nextRideIndex,
      transferBaseAt: predictedArrivalAt,
      basis: DelayImpactBasis.ridingPrediction,
    );
  }

  /// Continues transfer-risk analysis after the previous ride is confirmed as
  /// reached and the active schedule has moved to arrival/walk/wait, or while
  /// the next ride is explicitly still in the approaching phase.
  ///
  /// [availableAt] is normally the current clock time. Since no GPS is used,
  /// every explicit walk step between the last confirmed ride and the next ride
  /// is counted in full even if the user may already be part-way through it.
  static DelayImpact? analyzeFromConfirmedTransferPlace({
    required Trip trip,
    required ScheduleEntry activeEntry,
    required ReplanTransitPlace confirmedPlace,
    required DateTime availableAt,
  }) {
    if (activeEntry.generatedBy != ScheduleEntrySource.route) {
      return null;
    }
    final activeStepId = activeEntry.routeStepId?.trim();
    if (activeStepId == null || activeStepId.isEmpty) {
      return null;
    }

    final active = _findStep(trip, activeStepId);
    final candidate = trip.legs[active.legIndex].candidate;
    final activeStep = candidate.steps[active.stepIndex];

    late final int previousRideIndex;
    late final int nextRideIndex;

    if (activeStep.isRide) {
      final isArrivalEntry =
          activeEntry.itemKind == ScheduleEntryKind.arrival ||
          activeEntry.routeRole == 'arrival';
      final isRideEntry =
          activeEntry.itemKind == ScheduleEntryKind.ride ||
          activeEntry.routeRole == 'ride';

      if (isArrivalEntry) {
        previousRideIndex = active.stepIndex;
        final next = _findNextRideIndex(
          candidate.steps,
          active.stepIndex + 1,
        );
        if (next == null) return null;
        nextRideIndex = next;
      } else if (isRideEntry) {
        final previous = _findPreviousRideIndex(
          candidate.steps,
          active.stepIndex - 1,
        );
        if (previous == null) return null;
        previousRideIndex = previous;
        nextRideIndex = active.stepIndex;
      } else {
        throw StateError(
          '乗車stepを参照する乗換え判定entryのroleが不正です: '
          'entry=${activeEntry.id}, kind=${activeEntry.itemKind.name}, '
          'role=${activeEntry.routeRole}',
        );
      }
    } else {
      final previous = _findPreviousRideIndex(
        candidate.steps,
        active.stepIndex - 1,
      );
      final next = _findNextRideIndex(
        candidate.steps,
        active.stepIndex + 1,
      );
      if (previous == null || next == null) return null;
      previousRideIndex = previous;
      nextRideIndex = next;
    }

    final previousRide = candidate.steps[previousRideIndex];
    _validateConfirmedPlace(
      previousRide: previousRide,
      confirmedPlace: confirmedPlace,
    );

    return _buildImpact(
      trip: trip,
      legIndex: active.legIndex,
      previousRideIndex: previousRideIndex,
      nextRideIndex: nextRideIndex,
      transferBaseAt: availableAt,
      basis: DelayImpactBasis.confirmedTransferPlace,
    );
  }

  static DelayImpact _buildImpact({
    required Trip trip,
    required int legIndex,
    required int previousRideIndex,
    required int nextRideIndex,
    required DateTime transferBaseAt,
    required DelayImpactBasis basis,
  }) {
    final candidate = trip.legs[legIndex].candidate;
    if (previousRideIndex < 0 ||
        nextRideIndex <= previousRideIndex ||
        nextRideIndex >= candidate.steps.length) {
      throw StateError(
        '乗換え判定step indexが不正です: '
        'previous=$previousRideIndex, next=$nextRideIndex, '
        'steps=${candidate.steps.length}',
      );
    }

    final currentStep = candidate.steps[previousRideIndex];
    final nextRide = candidate.steps[nextRideIndex];
    if (!currentStep.isRide || !nextRide.isRide) {
      throw StateError(
        '乗換え判定の両端が乗車stepではありません: '
        '${currentStep.kind} -> ${nextRide.kind}',
      );
    }

    final currentArrivalEntry = _uniqueScheduleEntry(
      trip.schedule,
      legIndex: legIndex,
      routeStepId: currentStep.stepId,
      routeRole: 'arrival',
    );
    final nextRideEntry = _uniqueScheduleEntry(
      trip.schedule,
      legIndex: legIndex,
      routeStepId: nextRide.stepId,
      routeRole: 'ride',
    );

    final transferWalkMinutes = _transferWalkMinutes(
      candidate.steps,
      previousRideIndex: previousRideIndex,
      nextRideIndex: nextRideIndex,
    );

    final plannedTransferReadyAt = currentArrivalEntry.plannedAt.add(
      Duration(minutes: transferWalkMinutes),
    );
    if (plannedTransferReadyAt.isAfter(nextRideEntry.plannedAt)) {
      throw StateError(
        '元経路の時点で乗換えが成立していません: '
        'stepId=${currentStep.stepId}, '
        'plannedReady=${plannedTransferReadyAt.toIso8601String()}, '
        'nextDeparture=${nextRideEntry.plannedAt.toIso8601String()}',
      );
    }

    final earliestTransferReadyAt = transferBaseAt.add(
      Duration(minutes: transferWalkMinutes),
    );
    final feasible = !earliestTransferReadyAt.isAfter(nextRideEntry.plannedAt);
    final missedBy = feasible
        ? Duration.zero
        : earliestTransferReadyAt.difference(nextRideEntry.plannedAt);

    final currentTitle = currentStep.title.trim();
    final currentAlighting = currentStep.toName?.trim();
    final nextTitle = nextRide.title.trim();
    if (currentTitle.isEmpty) {
      throw StateError('現在乗車stepの表示名がありません: ${currentStep.stepId}');
    }
    if (currentAlighting == null || currentAlighting.isEmpty) {
      throw StateError('現在乗車stepの降車地点名がありません: ${currentStep.stepId}');
    }
    if (nextTitle.isEmpty) {
      throw StateError('次乗車stepの表示名がありません: ${nextRide.stepId}');
    }

    return DelayImpact(
      legIndex: legIndex,
      currentStepId: currentStep.stepId,
      currentRideTitle: currentTitle,
      currentAlightingPlaceName: currentAlighting,
      plannedArrivalAt: currentArrivalEntry.plannedAt,
      predictedArrivalAt: transferBaseAt,
      delay: transferBaseAt.difference(currentArrivalEntry.plannedAt),
      nextRideStepId: nextRide.stepId,
      nextRideTitle: nextTitle,
      nextDepartureAt: nextRideEntry.plannedAt,
      transferWalkMinutes: transferWalkMinutes,
      earliestTransferReadyAt: earliestTransferReadyAt,
      nextTransferFeasible: feasible,
      missedBy: missedBy,
      basis: basis,
    );
  }

  static int _transferWalkMinutes(
    List<StepSeg> steps, {
    required int previousRideIndex,
    required int nextRideIndex,
  }) {
    var minutes = 0;
    for (var index = previousRideIndex + 1; index < nextRideIndex; index++) {
      final step = steps[index];
      if (step.kind == 'walk') {
        if (step.minutes < 0) {
          throw StateError(
            '乗換え徒歩時間が負です: stepId=${step.stepId}, minutes=${step.minutes}',
          );
        }
        minutes += step.minutes;
        continue;
      }
      if (step.kind == 'wait') {
        continue;
      }
      throw StateError(
        '現在乗車と次乗車の間に未対応stepがあります: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }
    return minutes;
  }

  static void _validateConfirmedPlace({
    required StepSeg previousRide,
    required ReplanTransitPlace confirmedPlace,
  }) {
    final destinationName = previousRide.toName?.trim();
    if (destinationName == null || destinationName.isEmpty) {
      throw StateError(
        '直前乗車stepの降車地点名がありません: ${previousRide.stepId}',
      );
    }
    if (destinationName != confirmedPlace.name.trim()) {
      throw StateError(
        '最後に確定した交通地点が直前の降車地点と一致しません: '
        '$destinationName != ${confirmedPlace.name}',
      );
    }

    if (previousRide.stops.isNotEmpty) {
      final destinationStopId = previousRide.stops.last.stopId?.trim();
      final confirmedStopId = confirmedPlace.stopId?.trim();
      if (destinationStopId != null &&
          destinationStopId.isNotEmpty &&
          confirmedStopId != null &&
          confirmedStopId.isNotEmpty &&
          destinationStopId != confirmedStopId) {
        throw StateError(
          '最後に確定した交通地点IDが直前の降車地点と一致しません: '
          '$destinationStopId != $confirmedStopId',
        );
      }
    }
  }

  static _StepPosition _findStep(Trip trip, String stepId) {
    final matches = <_StepPosition>[];
    for (var legIndex = 0; legIndex < trip.legs.length; legIndex++) {
      final steps = trip.legs[legIndex].candidate.steps;
      for (var stepIndex = 0; stepIndex < steps.length; stepIndex++) {
        if (steps[stepIndex].stepId == stepId) {
          matches.add(_StepPosition(legIndex: legIndex, stepIndex: stepIndex));
        }
      }
    }
    if (matches.length != 1) {
      throw StateError(
        'DelayImpact対象stepをTrip内で一意に特定できません: '
        'stepId=$stepId, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static int? _findNextRideIndex(List<StepSeg> steps, int startIndex) {
    for (var index = startIndex; index < steps.length; index++) {
      if (steps[index].isRide) return index;
    }
    return null;
  }

  static int? _findPreviousRideIndex(List<StepSeg> steps, int startIndex) {
    for (var index = startIndex; index >= 0; index--) {
      if (steps[index].isRide) return index;
    }
    return null;
  }

  static ScheduleEntry _uniqueScheduleEntry(
    List<ScheduleEntry> entries, {
    required int legIndex,
    required String routeStepId,
    required String routeRole,
  }) {
    final matches = entries
        .where(
          (entry) =>
              entry.legIndex == legIndex &&
              entry.generatedBy == ScheduleEntrySource.route &&
              entry.routeStepId == routeStepId &&
              entry.routeRole == routeRole,
        )
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '乗換え判定に必要な予定を一意に特定できません: '
        'legIndex=$legIndex, stepId=$routeStepId, role=$routeRole, '
        'matches=${matches.length}',
      );
    }
    return matches.single;
  }
}

class _StepPosition {
  final int legIndex;
  final int stepIndex;

  const _StepPosition({
    required this.legIndex,
    required this.stepIndex,
  });
}

import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import 'replan_anchor.dart';

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
  });

  bool get requiresReplan => !nextTransferFeasible;
}

/// Evaluates whether the next planned transit boarding is still reachable from
/// the conservative realtime estimate for the ride the traveler is on now.
///
/// No arbitrary transfer buffer is added here. The minimum transfer cost is the
/// explicit walk duration already present in the route candidate. Planned wait
/// steps are slack, so they are intentionally not added to the minimum required
/// time. If the route/schedule cannot identify the transfer exactly, analysis
/// fails instead of guessing.
class DelayImpactAnalyzer {
  const DelayImpactAnalyzer._();

  static DelayImpact? analyze({
    required Trip trip,
    required RidingTransitObservation observation,
  }) {
    final active = _findActiveRide(trip, observation.stepId);
    final candidate = trip.legs[active.legIndex].candidate;
    final currentStep = candidate.steps[active.stepIndex];

    final nextRideIndex = _findNextRideIndex(
      candidate.steps,
      active.stepIndex + 1,
    );
    if (nextRideIndex == null) {
      return null;
    }
    final nextRide = candidate.steps[nextRideIndex];

    final predictedArrivalAt = observation.predictedDestinationAvailableAt;
    if (predictedArrivalAt == null) {
      throw StateError(
        '次の乗換えを判定するための降車地点到着見込みがありません: '
        'stepId=${observation.stepId}',
      );
    }

    final currentArrivalEntry = _uniqueScheduleEntry(
      trip.schedule,
      legIndex: active.legIndex,
      routeStepId: currentStep.stepId,
      routeRole: 'arrival',
    );
    final nextRideEntry = _uniqueScheduleEntry(
      trip.schedule,
      legIndex: active.legIndex,
      routeStepId: nextRide.stepId,
      routeRole: 'ride',
    );

    var transferWalkMinutes = 0;
    for (var index = active.stepIndex + 1; index < nextRideIndex; index++) {
      final step = candidate.steps[index];
      if (step.kind == 'walk') {
        if (step.minutes < 0) {
          throw StateError(
            '乗換え徒歩時間が負です: stepId=${step.stepId}, minutes=${step.minutes}',
          );
        }
        transferWalkMinutes += step.minutes;
        continue;
      }
      if (step.kind == 'wait') {
        // Scheduled waiting is slack, not a minimum transfer requirement.
        continue;
      }
      throw StateError(
        '現在乗車と次乗車の間に未対応stepがあります: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }

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

    final earliestTransferReadyAt = predictedArrivalAt.add(
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
      legIndex: active.legIndex,
      currentStepId: currentStep.stepId,
      currentRideTitle: currentTitle,
      currentAlightingPlaceName: currentAlighting,
      plannedArrivalAt: currentArrivalEntry.plannedAt,
      predictedArrivalAt: predictedArrivalAt,
      delay: predictedArrivalAt.difference(currentArrivalEntry.plannedAt),
      nextRideStepId: nextRide.stepId,
      nextRideTitle: nextTitle,
      nextDepartureAt: nextRideEntry.plannedAt,
      transferWalkMinutes: transferWalkMinutes,
      earliestTransferReadyAt: earliestTransferReadyAt,
      nextTransferFeasible: feasible,
      missedBy: missedBy,
    );
  }

  static _ActiveRidePosition _findActiveRide(Trip trip, String stepId) {
    final matches = <_ActiveRidePosition>[];
    for (var legIndex = 0; legIndex < trip.legs.length; legIndex++) {
      final steps = trip.legs[legIndex].candidate.steps;
      for (var stepIndex = 0; stepIndex < steps.length; stepIndex++) {
        if (steps[stepIndex].stepId == stepId) {
          if (!steps[stepIndex].isRide) {
            throw StateError(
              'RidingTransitObservationが乗車step以外を参照しています: '
              'stepId=$stepId, kind=${steps[stepIndex].kind}',
            );
          }
          matches.add(
            _ActiveRidePosition(legIndex: legIndex, stepIndex: stepIndex),
          );
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

class _ActiveRidePosition {
  final int legIndex;
  final int stepIndex;

  const _ActiveRidePosition({
    required this.legIndex,
    required this.stepIndex,
  });
}

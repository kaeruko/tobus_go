import '../models/group_models.dart';
import '../models/trip_models.dart';
import 'replan_anchor.dart';

enum GroupArrivalEstimateBasis {
  routeSchedule,
  finalRideRealtime,
}

class GroupArrivalEstimate {
  final int legIndex;
  final DateTime plannedArrivalAt;
  final DateTime expectedArrivalAt;
  final GroupArrivalEstimateBasis basis;

  const GroupArrivalEstimate({
    required this.legIndex,
    required this.plannedArrivalAt,
    required this.expectedArrivalAt,
    required this.basis,
  });
}

class GroupScheduleImpact {
  final GroupArrivalEstimate arrival;
  final ScheduleEntry affectedEntry;
  final Duration overrun;

  const GroupScheduleImpact({
    required this.arrival,
    required this.affectedEntry,
    required this.overrun,
  });
}

/// Detects a group-only schedule conflict without moving any schedule entry.
///
/// The baseline source is either the current route-generated goal time or, when
/// the traveler is already on the final ride of the leg, a conservative
/// realtime estimate for that ride. User GPS is never consulted.
class GroupScheduleImpactAnalyzer {
  const GroupScheduleImpactAnalyzer._();

  static GroupArrivalEstimate estimateFromRouteSchedule({
    required Trip trip,
    required int legIndex,
  }) {
    _requireGroupTrip(trip);
    _requireLegIndex(trip, legIndex);
    _uniqueRouteGoal(trip, legIndex);
    final canonicalRoute = _canonicalRouteSchedule(trip, legIndex);
    final canonicalGoal = _uniqueRouteGoalFromEntries(
      canonicalRoute,
      legIndex: legIndex,
      context: 'Candidateから再生成したroute schedule',
    );
    return GroupArrivalEstimate(
      legIndex: legIndex,
      plannedArrivalAt: canonicalGoal.plannedAt,
      expectedArrivalAt: canonicalGoal.plannedAt,
      basis: GroupArrivalEstimateBasis.routeSchedule,
    );
  }

  /// Returns a realtime destination estimate only when [observation] belongs to
  /// the final ride in its leg. If a later ride still exists, the downstream
  /// timetable can absorb or alter the delay, so this method deliberately
  /// returns null instead of projecting the current delay through that service.
  static GroupArrivalEstimate? estimateFromFinalRideRealtime({
    required Trip trip,
    required RidingTransitObservation observation,
  }) {
    _requireGroupTrip(trip);
    final position = _findStep(trip, observation.stepId);
    final candidate = trip.legs[position.legIndex].candidate;
    final step = candidate.steps[position.stepIndex];
    if (!step.isRide) {
      throw StateError(
        'グループ到着見込みのRealtime観測が乗車step以外を参照しています: '
        'stepId=${observation.stepId}, kind=${step.kind}',
      );
    }

    for (var index = position.stepIndex + 1;
        index < candidate.steps.length;
        index++) {
      if (candidate.steps[index].isRide) {
        return null;
      }
    }

    final predictedRideArrival = observation.predictedDestinationAvailableAt;
    if (predictedRideArrival == null) {
      return null;
    }

    _uniqueRouteEntry(
      trip,
      legIndex: position.legIndex,
      routeStepId: step.stepId,
      routeRole: 'arrival',
    );
    _uniqueRouteGoal(trip, position.legIndex);

    final canonicalRoute = _canonicalRouteSchedule(
      trip,
      position.legIndex,
    );
    final canonicalRideArrival = _uniqueRouteEntryFromEntries(
      canonicalRoute,
      legIndex: position.legIndex,
      routeStepId: step.stepId,
      routeRole: 'arrival',
      context: 'Candidateから再生成したroute schedule',
    );
    final canonicalGoal = _uniqueRouteGoalFromEntries(
      canonicalRoute,
      legIndex: position.legIndex,
      context: 'Candidateから再生成したroute schedule',
    );
    final plannedRemaining = canonicalGoal.plannedAt.difference(
      canonicalRideArrival.plannedAt,
    );
    if (plannedRemaining.isNegative) {
      throw StateError(
        '最終乗車の固定到着時刻より経路ゴールが前です: '
        'stepId=${step.stepId}, '
        'rideArrival=${canonicalRideArrival.plannedAt.toIso8601String()}, '
        'goal=${canonicalGoal.plannedAt.toIso8601String()}',
      );
    }

    return GroupArrivalEstimate(
      legIndex: position.legIndex,
      plannedArrivalAt: canonicalGoal.plannedAt,
      expectedArrivalAt: predictedRideArrival.add(plannedRemaining),
      basis: GroupArrivalEstimateBasis.finalRideRealtime,
    );
  }

  /// Finds the first manual event in this leg that the expected destination
  /// arrival would overrun. A missed event remains visible while the same leg is
  /// active; hiding it merely because its clock time passed would conceal the
  /// conflict exactly when the group is late.
  static GroupScheduleImpact? findFirstManualConflict({
    required Trip trip,
    required GroupArrivalEstimate arrival,
  }) {
    _requireGroupTrip(trip);
    _requireLegIndex(trip, arrival.legIndex);

    final candidates = trip.schedule
        .where(
          (entry) =>
              entry.legIndex == arrival.legIndex &&
              entry.generatedBy == ScheduleEntrySource.manual &&
              arrival.expectedArrivalAt.isAfter(entry.plannedAt),
        )
        .toList(growable: false)
      ..sort((a, b) {
        final byTime = a.plannedAt.compareTo(b.plannedAt);
        if (byTime != 0) return byTime;
        return a.id.compareTo(b.id);
      });

    if (candidates.isEmpty) return null;
    final affected = candidates.first;
    return GroupScheduleImpact(
      arrival: arrival,
      affectedEntry: affected,
      overrun: arrival.expectedArrivalAt.difference(affected.plannedAt),
    );
  }

  static List<ScheduleEntry> _canonicalRouteSchedule(
    Trip trip,
    int legIndex,
  ) {
    _requireLegIndex(trip, legIndex);
    final candidate = trip.legs[legIndex].candidate;
    final departureAt = candidate.departureDate;
    if (departureAt == null) {
      throw StateError(
        'グループ到着見込みの固定route時刻に必要なdepartureDateがありません: '
        'legIndex=$legIndex, candidateId=${candidate.id}',
      );
    }
    return createScheduleFromRoute(
      candidate,
      startDateTime: departureAt,
      legIndex: legIndex,
      shiftToStart: false,
    );
  }

  static ScheduleEntry _uniqueRouteGoalFromEntries(
    List<ScheduleEntry> entries, {
    required int legIndex,
    required String context,
  }) {
    final matches = entries
        .where(
          (entry) =>
              entry.legIndex == legIndex &&
              entry.generatedBy == ScheduleEntrySource.route &&
              entry.itemKind == ScheduleEntryKind.goal,
        )
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        '$context のroute goalを一意に特定できません: '
        'legIndex=$legIndex, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static ScheduleEntry _uniqueRouteEntryFromEntries(
    List<ScheduleEntry> entries, {
    required int legIndex,
    required String routeStepId,
    required String routeRole,
    required String context,
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
        '$context のroute entryを一意に特定できません: '
        'legIndex=$legIndex, stepId=$routeStepId, role=$routeRole, '
        'matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static void _requireGroupTrip(Trip trip) {
    if (trip.tripType != TripType.group) {
      throw StateError('グループ予定への到着影響はgroup Tripだけです: ${trip.id}');
    }
  }

  static void _requireLegIndex(Trip trip, int legIndex) {
    if (legIndex < 0 || legIndex >= trip.legs.length) {
      throw StateError(
        'グループ予定影響のlegIndexが不正です: '
        'legIndex=$legIndex, legs=${trip.legs.length}',
      );
    }
  }

  static ScheduleEntry _uniqueRouteGoal(Trip trip, int legIndex) {
    final matches = trip.schedule
        .where(
          (entry) =>
              entry.legIndex == legIndex &&
              entry.generatedBy == ScheduleEntrySource.route &&
              entry.itemKind == ScheduleEntryKind.goal,
        )
        .toList(growable: false);
    if (matches.length != 1) {
      throw StateError(
        'グループ到着予定のroute goalを一意に特定できません: '
        'legIndex=$legIndex, matches=${matches.length}',
      );
    }
    return matches.single;
  }

  static ScheduleEntry _uniqueRouteEntry(
    Trip trip, {
    required int legIndex,
    required String routeStepId,
    required String routeRole,
  }) {
    final matches = trip.schedule
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
        'グループ到着見込みに必要なroute entryを一意に特定できません: '
        'legIndex=$legIndex, stepId=$routeStepId, role=$routeRole, '
        'matches=${matches.length}',
      );
    }
    return matches.single;
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
        'グループ到着見込み対象stepを一意に特定できません: '
        'stepId=$stepId, matches=${matches.length}',
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

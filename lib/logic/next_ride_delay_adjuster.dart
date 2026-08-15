import 'delay_impact_analyzer.dart';
import 'next_ride_realtime.dart';

class NextRideAdjustedDelayImpact {
  final DelayImpact impact;
  final DateTime scheduledNextDepartureAt;
  final NextRideRealtimeDeparture realtime;

  const NextRideAdjustedDelayImpact({
    required this.impact,
    required this.scheduledNextDepartureAt,
    required this.realtime,
  });
}

class NextRideDelayAdjuster {
  const NextRideDelayAdjuster._();

  static NextRideAdjustedDelayImpact apply({
    required DelayImpact base,
    required NextRideRealtimeDeparture realtime,
  }) {
    if (base.nextRideStepId != realtime.stepId) {
      throw StateError(
        '次便RealtimeのstepIdが乗換え判定と一致しません: '
        '${base.nextRideStepId} != ${realtime.stepId}',
      );
    }

    final scheduledDepartureAt = base.nextDepartureAt;
    final effectiveDepartureAt = realtime.effectiveDepartureAt;

    if (realtime.status ==
        NextRideRealtimeDepartureStatus.passedBoardingPlace) {
      final missedBy = base.earliestTransferReadyAt.isAfter(realtime.observedAt)
          ? base.earliestTransferReadyAt.difference(realtime.observedAt)
          : Duration.zero;
      return NextRideAdjustedDelayImpact(
        impact: _copy(
          base,
          nextDepartureAt: realtime.observedAt,
          nextTransferFeasible: false,
          missedBy: missedBy,
        ),
        scheduledNextDepartureAt: scheduledDepartureAt,
        realtime: realtime,
      );
    }

    if (effectiveDepartureAt == null) {
      throw StateError(
        '通過済み以外の次便Realtimeに有効出発時刻がありません: '
        'stepId=${realtime.stepId}, status=${realtime.status.name}',
      );
    }

    final feasible =
        !base.earliestTransferReadyAt.isAfter(effectiveDepartureAt);
    final missedBy = feasible
        ? Duration.zero
        : base.earliestTransferReadyAt.difference(effectiveDepartureAt);

    return NextRideAdjustedDelayImpact(
      impact: _copy(
        base,
        nextDepartureAt: effectiveDepartureAt,
        nextTransferFeasible: feasible,
        missedBy: missedBy,
      ),
      scheduledNextDepartureAt: scheduledDepartureAt,
      realtime: realtime,
    );
  }

  static DelayImpact _copy(
    DelayImpact source, {
    required DateTime nextDepartureAt,
    required bool nextTransferFeasible,
    required Duration missedBy,
  }) {
    return DelayImpact(
      legIndex: source.legIndex,
      currentStepId: source.currentStepId,
      currentRideTitle: source.currentRideTitle,
      currentAlightingPlaceName: source.currentAlightingPlaceName,
      plannedArrivalAt: source.plannedArrivalAt,
      predictedArrivalAt: source.predictedArrivalAt,
      delay: source.delay,
      nextRideStepId: source.nextRideStepId,
      nextRideTitle: source.nextRideTitle,
      nextDepartureAt: nextDepartureAt,
      transferWalkMinutes: source.transferWalkMinutes,
      earliestTransferReadyAt: source.earliestTransferReadyAt,
      nextTransferFeasible: nextTransferFeasible,
      missedBy: missedBy,
      basis: source.basis,
    );
  }
}

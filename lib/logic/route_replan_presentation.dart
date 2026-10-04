import '../constants.dart';
import 'delay_impact_analyzer.dart';
import 'next_ride_realtime.dart';
import 'replan_debug_log.dart';

/// Shared presentation policy for route-replan actions in solo/group UIs.
///
/// Route review is offered only when the current route facts show that the
/// planned transfer is no longer feasible. A positive delay by itself is not
/// actionable while the next transfer is still expected to succeed.
/// Observation lag is allowed both while riding and after alighting. A next
/// service confirmed past the boarding place is always actionable.
class RouteReplanPresentation {
  final bool showAction;
  final bool showWarning;

  const RouteReplanPresentation({
    required this.showAction,
    required this.showWarning,
  });

  factory RouteReplanPresentation.fromDelayImpact(
    DelayImpact? impact, {
    NextRideRealtimeDeparture? nextRideRealtime,
  }) {
    if (impact != null &&
        nextRideRealtime != null &&
        impact.nextRideStepId != nextRideRealtime.stepId) {
      throw StateError(
        '警告表示の次便Realtimeが乗換え判定と一致しません: '
        '${impact.nextRideStepId} != ${nextRideRealtime.stepId}',
      );
    }

    final nextRidePassedBoardingPlace =
        impact != null &&
        nextRideRealtime?.status ==
            NextRideRealtimeDepartureStatus.passedBoardingPlace;
    final suppressedByRealtimeGrace =
        impact != null &&
        impact.requiresReplan &&
        !nextRidePassedBoardingPlace &&
        impact.missedBy <= kRealtimeTransferWarningGrace;
    final showWarning =
        impact != null &&
        (nextRidePassedBoardingPlace ||
            (impact.requiresReplan && !suppressedByRealtimeGrace));
    final showAction = showWarning;

    ReplanDebugLog.emit('replan_presentation', {
      'impactNull': impact == null,
      'showAction': showAction,
      'showWarning': showWarning,
      'currentStepId': impact?.currentStepId,
      'currentAlightingPlace': impact?.currentAlightingPlaceName,
      'plannedArrivalAt': impact?.plannedArrivalAt.toIso8601String(),
      'predictedArrivalAt': impact?.predictedArrivalAt.toIso8601String(),
      'delaySeconds': impact?.delay.inSeconds,
      'nextRideStepId': impact?.nextRideStepId,
      'nextDepartureAt': impact?.nextDepartureAt.toIso8601String(),
      'transferWalkMinutes': impact?.transferWalkMinutes,
      'transferBoardingMinutes': impact?.transferBoardingMinutes,
      'transferRequiredMinutes': impact?.transferRequiredMinutes,
      'earliestTransferReadyAt':
          impact?.earliestTransferReadyAt.toIso8601String(),
      'nextTransferFeasible': impact?.nextTransferFeasible,
      'missedBySeconds': impact?.missedBy.inSeconds,
      'warningGraceSeconds': kRealtimeTransferWarningGrace.inSeconds,
      'suppressedByRealtimeGrace': suppressedByRealtimeGrace,
      'nextRideRealtimeStatus': nextRideRealtime?.status.name,
      'nextRidePassedBoardingPlace': nextRidePassedBoardingPlace,
      'basis': impact?.basis.name,
    });

    return RouteReplanPresentation(
      showAction: showAction,
      showWarning: showWarning,
    );
  }
}

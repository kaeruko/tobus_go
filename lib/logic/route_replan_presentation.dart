import 'delay_impact_analyzer.dart';
import 'replan_debug_log.dart';

/// Shared presentation policy for route-replan actions in solo/group UIs.
///
/// Route review is offered only when the current route facts show that the
/// planned transfer is no longer feasible. A positive delay by itself is not
/// actionable while the next transfer is still expected to succeed.
class RouteReplanPresentation {
  final bool showAction;
  final bool showWarning;

  const RouteReplanPresentation({
    required this.showAction,
    required this.showWarning,
  });

  factory RouteReplanPresentation.fromDelayImpact(DelayImpact? impact) {
    final showWarning = impact?.requiresReplan == true;
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
      'earliestTransferReadyAt':
          impact?.earliestTransferReadyAt.toIso8601String(),
      'nextTransferFeasible': impact?.nextTransferFeasible,
      'missedBySeconds': impact?.missedBy.inSeconds,
      'basis': impact?.basis.name,
    });

    return RouteReplanPresentation(
      showAction: showAction,
      showWarning: showWarning,
    );
  }
}

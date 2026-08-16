import 'delay_impact_analyzer.dart';
import 'replan_debug_log.dart';

/// Shared presentation policy for route-replan actions in solo/group UIs.
///
/// Route review is offered only when the current route facts show a positive
/// delay. A missed/unsafe transfer is always treated as actionable.
class RouteReplanPresentation {
  final bool showAction;
  final bool showWarning;

  const RouteReplanPresentation({
    required this.showAction,
    required this.showWarning,
  });

  factory RouteReplanPresentation.fromDelayImpact(DelayImpact? impact) {
    final showWarning = impact?.requiresReplan == true;
    final hasPositiveDelay = impact != null && impact.delay > Duration.zero;
    final showAction = showWarning || hasPositiveDelay;

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

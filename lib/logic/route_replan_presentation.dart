import 'delay_impact_analyzer.dart';

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
    return RouteReplanPresentation(
      showAction: showWarning || hasPositiveDelay,
      showWarning: showWarning,
    );
  }
}

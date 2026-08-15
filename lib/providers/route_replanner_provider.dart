import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/route_replanner.dart';
import 'member_mode_provider.dart';
import 'replan_anchor_provider.dart';
import 'route_search_provider.dart';
import 'trip_provider.dart';

final routeReplannerProvider = Provider<RouteReplanner>((ref) {
  return RouteReplanner(ref.watch(routeSearchServiceProvider));
});

/// Builds the route-replan request that should be executed only when the user
/// asks to review the route. Reading this provider never starts a network call.
final currentRouteReplanRequestProvider =
    Provider.autoDispose<RouteReplanRequest?>((ref) {
      final tripAsync = ref.watch(tripStreamProvider);
      final uiAsync = ref.watch(memberUiStateProvider);
      final anchor = ref.watch(replanAnchorProvider);

      if (!tripAsync.hasValue || !uiAsync.hasValue) {
        return null;
      }
      final trip = tripAsync.value;
      final uiState = uiAsync.value;
      if (trip == null || uiState == null || anchor == null) {
        return null;
      }

      final activeStepId = uiState.resolvedEntry?.routeStepId;
      if (activeStepId == null) {
        return null;
      }

      return RouteReplanRequestBuilder.build(
        trip: trip,
        activeStepId: activeStepId,
        anchor: anchor,
      );
    }, dependencies: [
      tripStreamProvider,
      memberUiStateProvider,
      replanAnchorProvider,
    ]);

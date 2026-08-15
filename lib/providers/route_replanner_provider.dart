import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/route_replanner.dart';
import 'member_mode_provider.dart';
import 'replan_anchor_provider.dart';
import 'route_search_provider.dart';
import 'trip_provider.dart';

final routeReplannerProvider = Provider<RouteReplanner>((ref) {
  return RouteReplanner(ref.watch(routeSearchServiceProvider));
});

/// A user-facing reason why route replan must be paused right now.
///
/// Once onboard has been confirmed, a temporary realtime feed loss must not
/// silently turn the previous station/bus stop into the current replan origin.
/// GPS is not used as a fallback.
final routeReplanBlockedReasonProvider = Provider.autoDispose<String?>((ref) {
  final realtime = ref.watch(memberModeControllerProvider);
  final memory = realtime.replanTransitMemory;
  if (memory.ridingTransit == null && memory.knownOnboardStepId != null) {
    return '乗車中の駅・停留所をRealtimeで確認できないため、いまは経路を見直せません。位置情報の更新を待って、もう一度お試しください。';
  }
  return null;
}, dependencies: [memberModeControllerProvider]);

/// Builds the route-replan request that should be executed only when the user
/// asks to review the route. Reading this provider never starts a network call.
final currentRouteReplanRequestProvider =
    Provider.autoDispose<RouteReplanRequest?>((ref) {
      final tripAsync = ref.watch(tripStreamProvider);
      final uiAsync = ref.watch(memberUiStateProvider);
      final blockedReason = ref.watch(routeReplanBlockedReasonProvider);
      final anchor = ref.watch(replanAnchorProvider);

      if (blockedReason != null) {
        return null;
      }
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
      memberModeControllerProvider,
      routeReplanBlockedReasonProvider,
      replanAnchorProvider,
    ]);

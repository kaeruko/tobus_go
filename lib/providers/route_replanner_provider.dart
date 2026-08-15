import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/route_replanner.dart';
import 'member_mode_provider.dart';
import 'replan_anchor_provider.dart';
import 'replan_transit_persistence_provider.dart';
import 'route_search_provider.dart';
import 'trip_provider.dart';

final routeReplannerProvider = Provider<RouteReplanner>((ref) {
  return RouteReplanner(ref.watch(routeSearchServiceProvider));
});

/// A user-facing reason why route replan must be paused right now.
///
/// Restart restoration is fail-safe: while local transit history is loading or
/// invalid, route search stays disabled. A restored onboard marker also blocks
/// until fresh realtime identifies the current station/stop.
final routeReplanBlockedReasonProvider = Provider.autoDispose<String?>((ref) {
  final effective = ref.watch(effectiveReplanTransitMemoryProvider);
  if (effective.restoring) {
    return '前回の乗車履歴を確認しています。確認が終わるまで経路を見直せません。';
  }
  if (effective.restoreError != null) {
    return '保存済みの乗車履歴を安全に復元できないため、いまは経路を見直せません: ${effective.restoreError}';
  }
  final memory = effective.memory;
  if (memory != null &&
      memory.ridingTransit == null &&
      memory.knownOnboardStepId != null) {
    return '乗車中の駅・停留所をRealtimeで確認できないため、いまは経路を見直せません。Realtimeの更新を待って、もう一度お試しください。';
  }
  return null;
}, dependencies: [
  memberModeControllerProvider,
  effectiveReplanTransitMemoryProvider,
]);

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

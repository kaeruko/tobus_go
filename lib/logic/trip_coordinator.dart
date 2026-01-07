import 'package:flutter/material.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart'; // StepSeg
import 'trip_navigator.dart';

class ResolvedScheduleState {
  final ScheduleEntry? activeEntry;
  final ScheduleEntry? resolvedEntry;
  final List<ScheduleEntry> windowEntries;
  final int completedCount;
  final String activeLabel;
  final String resolutionReason;

  const ResolvedScheduleState({
    required this.activeEntry,
    required this.resolvedEntry,
    required this.windowEntries,
    required this.completedCount,
    required this.activeLabel,
    required this.resolutionReason,
  });
}

class TripCoordinator {
  static ScheduleEntry _ensureResolvedEntryHasRouteStepIndex({
    required ScheduleEntry resolvedEntry,
    required void Function(String) addReason,
  }) {
    if (resolvedEntry.routeStepIndex != null) {
      return resolvedEntry;
    }

    addReason("missing_route_step_index");
    assert(() {
      debugPrint(
        "[TripCoordinator] Resolved entry missing routeStepIndex: "
        "id=${resolvedEntry.id} label=${resolvedEntry.label}",
      );
      return false;
    }());
    return resolvedEntry;
  }

  static bool _realtimeSaysRideStarted({
    required StepSeg step,
    required String? realtimeBusLocationId,
  }) {
    if (!step.isRide) return false;
    if (realtimeBusLocationId == null) return false;
    if (step.stops.isEmpty) return false;

    final boardingStopId = step.stops.first.stopId;
    final isAtBoarding = boardingStopId != null && realtimeBusLocationId == boardingStopId;
    final isInSegment = step.stops.any((s) => s.stopId == realtimeBusLocationId);

    return isAtBoarding || isInSegment;
  }

  static StepSeg? _stepForEntry(RouteState? routeState, ScheduleEntry entry) {
    if (routeState == null) return null;
    final idx = entry.routeStepIndex;
    if (idx == null) return null;
    if (idx < 0) return null;
    if (idx >= routeState.steps.length) return null;
    return routeState.steps[idx];
  }

  static ResolvedScheduleState resolveScheduleState({
    required List<ScheduleEntry> scheduleEntries,
    required DateTime now,
    RouteState? routeState,
    String? realtimeBusLocationId,
    int prevCount = 1,
    int nextCount = 3,
  }) {
    final scheduleSorted = [...scheduleEntries];
    sortScheduleEntries(scheduleSorted);

    int activeIndex = _resolveActiveIndex(scheduleSorted, now);
    String activeLabel = 'いま';

    if (activeIndex == -1 && scheduleSorted.isNotEmpty) {
      final first = scheduleSorted.first;
      final diff = first.plannedAt.difference(now);
      activeLabel = diff.inMinutes > 20 ? 'そのうち' : 'つぎ';
    }

    final active = (activeIndex >= 0 && activeIndex < scheduleSorted.length)
        ? scheduleSorted[activeIndex]
        : null;

    final completedCount = activeIndex >= 0 ? activeIndex : 0;

    final start = activeIndex >= 0 ? (activeIndex - prevCount) : 0;
    final safeStart = start < 0 ? 0 : start;
    final end = activeIndex >= 0 ? (activeIndex + nextCount) : nextCount;
    final safeEnd = end >= scheduleSorted.length ? scheduleSorted.length - 1 : end;
    final windowEntries = (activeIndex >= 0 || scheduleSorted.isNotEmpty) && safeStart <= safeEnd
        ? scheduleSorted.sublist(safeStart, safeEnd + 1)
        : <ScheduleEntry>[];

    final resolutionReasons = <String>[];
    void addReason(String reason) {
      resolutionReasons.add(reason);
    }

    ScheduleEntry? resolved = active;
    if (active == null) {
      addReason("no_active_entry");
      return ResolvedScheduleState(
        activeEntry: null,
        resolvedEntry: null,
        windowEntries: windowEntries,
        completedCount: completedCount,
        activeLabel: activeLabel,
        resolutionReason: resolutionReasons.join(" | "),
      );
    }

    addReason("active_entry");

    // [New Logic] Prevent premature "Arrival" if getting off
    // If the time-based resolver says "Arrival", but we have realtime info saying the bus is NOT at the destination,
    // we should revert to "Ride" (meaning we are still on the bus or waiting for it).
    if (resolved.itemKind == ScheduleEntryKind.arrival && realtimeBusLocationId != null) {
      // Find the destination stop ID for this arrival entry (if possible)
      // We can look at the StepSeg associated with this arrival entry.
      // Actually, 'Arrival' entry usually corresponds to the ALIGHTING action.
      // The associated step in 'routeState' should be the Alight step or the Ride step?
      // Usually Arrival is linked to the Ride step (same leg).
      // Let's check if the realtime ID matches the destination.
      
      // For Arrival, the step might be the Ride step (stops list) or the Alight node?
      // In ScheduleEntry, routeStepIndex usually points to the Ride segment if it's "Ride".
      // For "Arrival", it might point to the same ride segment or the next?
      // Let's assume we need to find the "Ride" entry for this leg to be safe.
      
      ScheduleEntry? rideEntry;
      for (final e in scheduleSorted) {
        if (e.legIndex == resolved.legIndex && e.itemKind == ScheduleEntryKind.ride) {
          rideEntry = e;
          break;
        }
      }

      if (rideEntry != null) {
         final rideStep = _stepForEntry(routeState, rideEntry);
         if (rideStep != null && rideStep.stops.isNotEmpty) {
            final destStopId = rideStep.stops.last.stopId;
            // If the bus is NOT at the destination yet, force "Ride"
            if (destStopId != null && realtimeBusLocationId != destStopId) {
               resolved = rideEntry;
               addReason("premature_arrival_revert");
               debugPrint("[TripCoordinator] Premature Arrival detected. Bus at $realtimeBusLocationId != Dest $destStopId. Reverting to Ride.");
            }
         }
      }
    }

    resolved = _ensureResolvedEntryHasRouteStepIndex(
      resolvedEntry: resolved,
      addReason: addReason,
    );

    final resolvedCompletedCount = _resolveCompletedCount(
      baseCompletedCount: completedCount,
      activeEntry: active,
      resolvedEntry: resolved,
      windowEntries: windowEntries,
    );

    return ResolvedScheduleState(
      activeEntry: active,
      resolvedEntry: resolved,
      windowEntries: windowEntries,
      completedCount: resolvedCompletedCount,
      activeLabel: activeLabel,
      resolutionReason: resolutionReasons.join(" | "),
    );
  }

  static int _resolveCompletedCount({
    required int baseCompletedCount,
    required ScheduleEntry? activeEntry,
    required ScheduleEntry? resolvedEntry,
    required List<ScheduleEntry> windowEntries,
  }) {
    if (activeEntry == null || resolvedEntry == null) {
      return baseCompletedCount;
    }

    if (resolvedEntry.id == activeEntry.id) {
      return baseCompletedCount;
    }

    final activePos = windowEntries.indexWhere((entry) => entry.id == activeEntry.id);
    final resolvedPos = windowEntries.indexWhere((entry) => entry.id == resolvedEntry.id);
    if (activePos == -1 || resolvedPos == -1) {
      return baseCompletedCount;
    }

    final adjusted = baseCompletedCount + (resolvedPos - activePos);
    return adjusted < 0 ? 0 : adjusted;
  }

  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required RouteState? routeState,
    required DateTime now,
    String? realtimeBusLocationId,
    ResolvedScheduleState? resolvedState,
  }) {
    // -------------------------------------------------------------
    // 1. ツアー全体のステータスチェック
    // -------------------------------------------------------------
    // ツアーが終了または中止されている場合は、専用の画面を表示
    if (trip.status == TripStatus.completed) {
      return NavigationState(
        mainText: "終了",
        subText: "お疲れ様でした",
        color: Colors.grey,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "お出かけ終了",
        isMoving: false,
      );
    }
    if (trip.status == TripStatus.cancelled) {
      return NavigationState(
        mainText: "中止",
        subText: "グループは解散されました",
        color: Colors.red,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "中止",
        isMoving: false,
      );
    }

    // 現在のバス停番号（または0）
    final stopIndex = routeState?.nextStopIndex ?? 0;

    if (resolvedState == null || resolvedState.resolvedEntry == null) {
      // 何もない場合は待機状態
      return NavigationState.idle();
    }

    final resolved = resolvedState.resolvedEntry!;
    debugPrint("[TripCoordinator] active=${resolvedState.activeEntry?.label} kind=${resolvedState.activeEntry?.itemKind} rt=${resolvedState.activeEntry?.routeStepIndex} realtime=$realtimeBusLocationId");
    debugPrint("[TripCoordinator] resolved=${resolved.label} kind=${resolved.itemKind} rt=${resolved.routeStepIndex}");
    debugPrint("[TripCoordinator] reason=${resolvedState.resolutionReason}");

    final diff = resolved.plannedAt.difference(now);

    // -------------------------------------------------------------
    // 5. 長時間待機 (20分以上未来) の表示
    // -------------------------------------------------------------
    // かなり先の予定の場合は、詳細なナビではなく「あと◯時間」表示にする
    if (diff.inMinutes > 20) {
      return NavigationState.waitingLong(entry: resolved, diff: diff);
    }

    // -------------------------------------------------------------
    // 6. 最終的なナビゲーション状態の生成
    // -------------------------------------------------------------
    // 決定した resolved エントリーに基づいて、画面表示用オブジェクト(NavigationState)を作成
    final baseState = NavigationState.fromEntry(
      trip: trip,
      entry: resolved,
      step: _stepForEntry(routeState, resolved),
      stopIndex: stopIndex,
      currentStepIndex: routeState?.currentStepIndex ?? 0,
    );

    return baseState;
  }

  static int _resolveActiveIndex(List<ScheduleEntry> steps, DateTime now) {
    if (steps.isEmpty) return -1;

    int bestIndex = -1;
    double minScore = 99999.0;

    debugPrint('[TripCoordinator] Resolving active step at $now (steps=${steps.length})');

    for (int i = 0; i < steps.length; i++) {
      final step = steps[i];
      final diffMin = step.plannedAt.difference(now).inMinutes;

      bool isCandidate = false;

      if (step.itemKind == ScheduleEntryKind.ride) {
        if (diffMin <= 60 && diffMin > -120) {
          isCandidate = true;
        }
      } else {
        if (diffMin <= 60 && diffMin > -120) {
          isCandidate = true;
        }
      }

      debugPrint(
        '[TripCoordinator] Step $i (${step.label}): plannedAt=${step.plannedAt} '
        'diff=${diffMin}m kind=${step.itemKind} candidate=$isCandidate '
        'routeStepIndex=${step.routeStepIndex}',
      );

      if (isCandidate) {
        double score = diffMin.abs().toDouble();

        if (diffMin < 0) score += 0.5;

        if (step.itemKind == ScheduleEntryKind.ride && diffMin < 0) {
          if (i + 1 < steps.length) {
            final next = steps[i + 1];
            if (next.itemKind == ScheduleEntryKind.arrival) {
              final nextDiff = next.plannedAt.difference(now).inMinutes;
              if (nextDiff > 0) {
                score = 0.1;
              }
            }
          }
        }

        debugPrint('  -> Score: $score (best: $minScore)');

        if (score < minScore) {
          minScore = score;
          bestIndex = i;
          debugPrint('[TripCoordinator] New best -> index=$bestIndex score=$minScore label=${step.label}');
        }
      }
    }

    debugPrint('[TripCoordinator] Selected best index: $bestIndex');
    return bestIndex;
  }
}

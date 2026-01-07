import 'package:flutter/material.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart'; // StepSeg
import 'trip_navigator.dart';
import 'schedule_resolver.dart';

enum ScheduleDisplayHint {
  normal,
  rideSoon,
}

class ResolvedScheduleState {
  final ScheduleEntry? activeEntry;
  final ScheduleEntry resolvedEntry;
  final List<ScheduleEntry> windowEntries;
  final int completedCount;
  final String activeLabel;
  final ScheduleDisplayHint displayHint;
  final String resolutionReason;

  const ResolvedScheduleState({
    required this.activeEntry,
    required this.resolvedEntry,
    required this.windowEntries,
    required this.completedCount,
    required this.activeLabel,
    required this.displayHint,
    required this.resolutionReason,
  });
}

class TripCoordinator {
  static ScheduleEntry _ensureResolvedEntryHasRouteStepIndex({
    required ScheduleEntry resolvedEntry,
    required ScheduleResolveResult scheduleState,
    required void Function(String) addReason,
  }) {
    if (resolvedEntry.routeStepIndex != null) {
      return resolvedEntry;
    }

    final fallback = scheduleState.window.firstWhere((entry) => entry.routeStepIndex != null);
    if (fallback.id != resolvedEntry.id) {
      addReason("fallback_route_step_index");
    } else {
      addReason("missing_route_step_index");
    }
    return fallback;
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

  static ResolvedScheduleState? resolveScheduleState({
    required ScheduleResolveResult scheduleState,
    required RouteState? routeState,
    required DateTime now,
    String? realtimeBusLocationId,
  }) {
    final active = scheduleState.activeEntry;
    if (active == null) {
      return null;
    }

    final resolutionReasons = <String>[];
    void addReason(String reason) {
      resolutionReasons.add(reason);
    }

    addReason("active_entry");

    ScheduleEntry resolved = active;
    ScheduleDisplayHint displayHint = ScheduleDisplayHint.normal;

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
      for (final e in scheduleState.window) {
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
               displayHint = ScheduleDisplayHint.normal;
               addReason("premature_arrival_revert");
               debugPrint("[TripCoordinator] Premature Arrival detected. Bus at $realtimeBusLocationId != Dest $destStopId. Reverting to Ride.");
            }
         }
      }
    }

    resolved = _ensureResolvedEntryHasRouteStepIndex(
      resolvedEntry: resolved,
      scheduleState: scheduleState,
      addReason: addReason,
    );

    final completedCount = _resolveCompletedCount(
      scheduleState: scheduleState,
      resolvedEntry: resolved,
    );

    return ResolvedScheduleState(
      activeEntry: active,
      resolvedEntry: resolved,
      windowEntries: scheduleState.window,
      completedCount: completedCount,
      activeLabel: scheduleState.activeLabel,
      displayHint: displayHint,
      resolutionReason: resolutionReasons.join(" | "),
    );
  }

  static int _resolveCompletedCount({
    required ScheduleResolveResult scheduleState,
    required ScheduleEntry resolvedEntry,
  }) {
    final activeEntry = scheduleState.activeEntry;
    if (activeEntry == null) {
      return scheduleState.completedCount;
    }

    if (resolvedEntry.id == activeEntry.id) {
      return scheduleState.completedCount;
    }

    final window = scheduleState.window;
    final activePos = window.indexWhere((entry) => entry.id == activeEntry.id);
    final resolvedPos = window.indexWhere((entry) => entry.id == resolvedEntry.id);
    if (activePos == -1 || resolvedPos == -1) {
      return scheduleState.completedCount;
    }

    final adjusted = scheduleState.completedCount + (resolvedPos - activePos);
    return adjusted < 0 ? 0 : adjusted;
  }

  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required ScheduleResolveResult scheduleState,
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

    final resolvedScheduleState = resolvedState ??
        resolveScheduleState(
          scheduleState: scheduleState,
          routeState: routeState,
          now: now,
          realtimeBusLocationId: realtimeBusLocationId,
        );

    if (resolvedScheduleState == null) {
      // 何もない場合は待機状態
      return NavigationState.idle();
    }

    final resolved = resolvedScheduleState.resolvedEntry;
    final displayHint = resolvedScheduleState.displayHint;

    debugPrint("[TripCoordinator] active=${resolvedScheduleState.activeEntry?.label} kind=${resolvedScheduleState.activeEntry?.itemKind} rt=${resolvedScheduleState.activeEntry?.routeStepIndex} realtime=$realtimeBusLocationId");
    debugPrint("[TripCoordinator] resolved=${resolved.label} kind=${resolved.itemKind} rt=${resolved.routeStepIndex}");
    debugPrint("[TripCoordinator] displayHint=$displayHint reason=${resolvedScheduleState.resolutionReason}");

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

    if (displayHint == ScheduleDisplayHint.rideSoon && resolved.itemKind == ScheduleEntryKind.ride) {
      return NavigationState(
        mainText: "もうすぐ乗車",
        subText: "まもなく乗車します",
        color: baseState.color,
        currentStepIndex: baseState.currentStepIndex,
        nextStopIndex: baseState.nextStopIndex,
        statusLabel: "もうすぐ乗車",
        nextStopName: baseState.nextStopName,
        remainingStops: baseState.remainingStops,
        isMoving: baseState.isMoving,
        step: baseState.step,
      );
    }

    return baseState;
  }
}

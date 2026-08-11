import 'package:flutter/material.dart';

import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
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
  static void _validateStepReference(
    ScheduleEntry entry,
    void Function(String) addReason,
  ) {
    final needsRouteStep =
        entry.generatedBy == ScheduleEntrySource.route &&
        (entry.itemKind == ScheduleEntryKind.walk ||
            entry.itemKind == ScheduleEntryKind.ride ||
            entry.itemKind == ScheduleEntryKind.arrival ||
            entry.routeRole == 'wait_start');
    if (!needsRouteStep || entry.routeStepId != null) return;

    addReason('missing_route_step_id');
    throw StateError(
      '経路由来の予定にrouteStepIdがありません: '
      'id=${entry.id} label=${entry.label}',
    );
  }

  static StepSeg? _stepForEntry(RouteState? routeState, ScheduleEntry entry) {
    return routeState?.stepForId(entry.routeStepId);
  }

  static ResolvedScheduleState resolveScheduleState({
    required List<ScheduleEntry> scheduleEntries,
    required DateTime now,
    RouteState? routeState,
    int prevCount = 1,
    int nextCount = 3,
  }) {
    final scheduleSorted = [...scheduleEntries];
    sortScheduleEntries(scheduleSorted);

    final activeIndex = _resolveActiveIndex(scheduleSorted, now);
    var activeLabel = 'いま';
    if (activeIndex == -1 && scheduleSorted.isNotEmpty) {
      final diff = scheduleSorted.first.plannedAt.difference(now);
      activeLabel = diff.inMinutes > 20 ? 'そのうち' : 'つぎ';
    }

    final active = activeIndex >= 0 && activeIndex < scheduleSorted.length
        ? scheduleSorted[activeIndex]
        : null;
    final completedCount = activeIndex >= 0 ? activeIndex : 0;

    final start = activeIndex >= 0 ? activeIndex - prevCount : 0;
    final safeStart = start < 0 ? 0 : start;
    final end = activeIndex >= 0 ? activeIndex + nextCount : nextCount;
    final safeEnd = end >= scheduleSorted.length
        ? scheduleSorted.length - 1
        : end;
    final windowEntries =
        (activeIndex >= 0 || scheduleSorted.isNotEmpty) && safeStart <= safeEnd
        ? scheduleSorted.sublist(safeStart, safeEnd + 1)
        : <ScheduleEntry>[];

    final reasons = <String>[];
    void addReason(String reason) => reasons.add(reason);

    if (active == null) {
      addReason('no_active_entry');
      return ResolvedScheduleState(
        activeEntry: null,
        resolvedEntry: null,
        windowEntries: windowEntries,
        completedCount: completedCount,
        activeLabel: activeLabel,
        resolutionReason: reasons.join(' | '),
      );
    }

    var resolved = active;
    addReason('active_entry');

    final progress = routeState?.busProgress;
    if (resolved.itemKind == ScheduleEntryKind.arrival &&
        progress != null &&
        resolved.routeStepId == progress.stepId) {
      final rideEntry = scheduleSorted.cast<ScheduleEntry?>().firstWhere(
        (entry) =>
            entry?.legIndex == resolved.legIndex &&
            entry?.itemKind == ScheduleEntryKind.ride &&
            entry?.routeStepId == resolved.routeStepId,
        orElse: () => null,
      );
      final rideStep = rideEntry == null
          ? null
          : _stepForEntry(routeState, rideEntry);
      if (rideEntry != null &&
          rideStep != null &&
          rideStep.stops.isNotEmpty &&
          progress.phase != BusProgressPhase.arrived) {
        resolved = rideEntry;
        addReason('premature_arrival_revert_step_id');
      }
    }

    _validateStepReference(resolved, addReason);

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
      resolutionReason: reasons.join(' | '),
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
    if (resolvedEntry.id == activeEntry.id) return baseCompletedCount;

    final activePos = windowEntries.indexWhere(
      (entry) => entry.id == activeEntry.id,
    );
    final resolvedPos = windowEntries.indexWhere(
      (entry) => entry.id == resolvedEntry.id,
    );
    if (activePos == -1 || resolvedPos == -1) return baseCompletedCount;

    final adjusted = baseCompletedCount + (resolvedPos - activePos);
    return adjusted < 0 ? 0 : adjusted;
  }

  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required RouteState? routeState,
    required DateTime now,
    ResolvedScheduleState? resolvedState,
  }) {
    if (trip.status == TripStatus.completed) {
      return const NavigationState(
        mainText: '終了',
        subText: 'お疲れ様でした',
        color: Colors.grey,
        statusLabel: 'お出かけ終了',
        isMoving: false,
      );
    }
    if (trip.status == TripStatus.cancelled) {
      return const NavigationState(
        mainText: '中止',
        subText: 'グループは解散されました',
        color: Colors.red,
        statusLabel: '中止',
        isMoving: false,
      );
    }
    if (resolvedState == null || resolvedState.resolvedEntry == null) {
      return NavigationState.idle();
    }

    final resolved = resolvedState.resolvedEntry!;
    debugPrint(
      '[TripCoordinator] active=${resolvedState.activeEntry?.label} '
      'stepId=${resolvedState.activeEntry?.routeStepId}',
    );
    debugPrint(
      '[TripCoordinator] resolved=${resolved.label} '
      'stepId=${resolved.routeStepId} reason=${resolvedState.resolutionReason}',
    );

    final diff = resolved.plannedAt.difference(now);
    if (diff.inMinutes > 20) {
      return NavigationState.waitingLong(entry: resolved, diff: diff);
    }

    final step = _stepForEntry(routeState, resolved);
    final BusProgress? progress =
        routeState?.busProgress?.stepId == step?.stepId
        ? routeState?.busProgress
        : null;
    return NavigationState.fromEntry(
      entry: resolved,
      step: step,
      busProgress: progress,
    );
  }

  static int _resolveActiveIndex(List<ScheduleEntry> entries, DateTime now) {
    if (entries.isEmpty) return -1;
    var bestIndex = -1;
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].plannedAt.isAfter(now)) break;
      bestIndex = i;
    }
    return bestIndex;
  }
}

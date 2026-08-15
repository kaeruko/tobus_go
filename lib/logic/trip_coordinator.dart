import 'package:flutter/material.dart';

import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/rail_progress.dart';
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

class _RealtimeRideProgress {
  final String stepId;
  final bool arrived;

  const _RealtimeRideProgress({
    required this.stepId,
    required this.arrived,
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

  static _RealtimeRideProgress? _realtimeRideProgress(RouteState? routeState) {
    final bus = routeState?.busProgress;
    final rail = routeState?.railProgress;
    if (bus != null && rail != null) {
      throw StateError('busとrailのリアルタイム進捗が同時に存在しています');
    }
    if (bus != null) {
      return _RealtimeRideProgress(
        stepId: bus.stepId,
        arrived: bus.phase == BusProgressPhase.arrived,
      );
    }
    if (rail != null) {
      return _RealtimeRideProgress(
        stepId: rail.stepId,
        arrived: rail.phase == RailProgressPhase.arrived,
      );
    }
    return null;
  }

  static String _formatClock(DateTime time) {
    return '${time.hour}:${time.minute.toString().padLeft(2, '0')}';
  }

  static int _minutesUntil(DateTime target, DateTime now) {
    final seconds = target.difference(now).inSeconds;
    if (seconds <= 0) return 0;
    return (seconds + 59) ~/ 60;
  }

  static String _boardingSubText({
    required Trip trip,
    required ScheduleEntry rideEntry,
    required String rideTime,
    bool planned = false,
  }) {
    final stepId = rideEntry.routeStepId;
    if (stepId == null || stepId.isEmpty) {
      throw StateError(
        '乗車予定にrouteStepIdがありません: entryId=${rideEntry.id}',
      );
    }

    final rideStep = trip.stepsById[stepId];
    if (rideStep == null) {
      throw StateError(
        '乗車予定が存在しないrouteStepIdを参照しています: '
        'entryId=${rideEntry.id}, routeStepId=$stepId',
      );
    }
    if (!rideStep.isRide) {
      throw StateError(
        '乗車予定のrouteStepIdが乗車ステップではありません: '
        'entryId=${rideEntry.id}, routeStepId=$stepId, kind=${rideStep.kind}',
      );
    }

    final routeTitle = rideStep.title.trim();
    if (routeTitle.isEmpty) {
      throw StateError(
        '乗車ステップの路線・行先表示が空です: '
        'entryId=${rideEntry.id}, routeStepId=$stepId',
      );
    }

    return '$rideTime $routeTitle ${planned ? '乗車予定' : '乗車'}';
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

    final progress = _realtimeRideProgress(routeState);
    if (progress != null && !progress.arrived) {
      final trackedRideIndex = scheduleSorted.indexWhere(
        (entry) =>
            entry.itemKind == ScheduleEntryKind.ride &&
            entry.routeStepId == progress.stepId,
      );
      if (trackedRideIndex >= 0 && activeIndex > trackedRideIndex) {
        resolved = scheduleSorted[trackedRideIndex];
        addReason('realtime_incomplete_ride_revert_step_id');
      }
    }

    if (resolved.itemKind == ScheduleEntryKind.ride &&
        progress != null &&
        resolved.routeStepId == progress.stepId &&
        progress.arrived) {
      final arrivalEntry = scheduleSorted.cast<ScheduleEntry?>().firstWhere(
        (entry) =>
            entry?.legIndex == resolved.legIndex &&
            entry?.itemKind == ScheduleEntryKind.arrival &&
            entry?.routeStepId == resolved.routeStepId,
        orElse: () => null,
      );
      if (arrivalEntry != null) {
        resolved = arrivalEntry;
        addReason('realtime_arrival_advance_step_id');
      }
    }

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
          !progress.arrived) {
        resolved = rideEntry;
        addReason('premature_arrival_revert_step_id');
      }
    }

    _validateStepReference(resolved, addReason);

    final resolvedIndex = scheduleSorted.indexWhere(
      (entry) => entry.id == resolved.id,
    );
    final resolvedCompletedCount = resolvedIndex >= 0
        ? resolvedIndex
        : completedCount;
    final resolvedWindowEntries = resolvedIndex >= 0
        ? _windowAround(
            scheduleSorted,
            activeIndex: resolvedIndex,
            prevCount: prevCount,
            nextCount: nextCount,
          )
        : windowEntries;

    return ResolvedScheduleState(
      activeEntry: active,
      resolvedEntry: resolved,
      windowEntries: resolvedWindowEntries,
      completedCount: resolvedCompletedCount,
      activeLabel: activeLabel,
      resolutionReason: reasons.join(' | '),
    );
  }

  static List<ScheduleEntry> _windowAround(
    List<ScheduleEntry> entries, {
    required int activeIndex,
    required int prevCount,
    required int nextCount,
  }) {
    if (entries.isEmpty || activeIndex < 0 || activeIndex >= entries.length) {
      return const <ScheduleEntry>[];
    }
    final start = (activeIndex - prevCount).clamp(0, entries.length - 1);
    final end = (activeIndex + nextCount).clamp(0, entries.length - 1);
    return entries.sublist(start, end + 1);
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
    if (resolvedState == null) {
      return NavigationState.idle();
    }
    if (resolvedState.resolvedEntry == null) {
      if (resolvedState.windowEntries.isNotEmpty) {
        return NavigationState.waitingForDeparture(
          plannedAt: resolvedState.windowEntries.first.plannedAt,
        );
      }
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

    final step = _stepForEntry(routeState, resolved);

    if (resolved.routeRole == 'wait_start') {
      final nextRides =
          trip.schedule
              .where(
                (entry) =>
                    entry.legIndex == resolved.legIndex &&
                    entry.itemKind == ScheduleEntryKind.ride &&
                    !entry.plannedAt.isBefore(resolved.plannedAt),
              )
              .toList()
            ..sort((a, b) => a.plannedAt.compareTo(b.plannedAt));

      if (nextRides.isEmpty) {
        throw StateError('待機予定の後に乗車予定がありません: entryId=${resolved.id}');
      }

      final rideEntry = nextRides.first;
      final rideAt = rideEntry.plannedAt;
      final rideTime = _formatClock(rideAt);

      final departures =
          trip.schedule
              .where(
                (entry) =>
                    entry.legIndex == resolved.legIndex &&
                    entry.itemKind == ScheduleEntryKind.walk &&
                    !entry.plannedAt.isBefore(resolved.plannedAt) &&
                    !entry.plannedAt.isAfter(rideAt),
              )
              .toList()
            ..sort((a, b) => a.plannedAt.compareTo(b.plannedAt));

      if (departures.isNotEmpty) {
        final leaveAt = departures.first.plannedAt;
        final leaveTime = _formatClock(leaveAt);
        final remainingMinutes = _minutesUntil(leaveAt, now);

        return NavigationState(
          mainText: '$leaveTime 出発　あと$remainingMinutes分',
          subText: _boardingSubText(
            trip: trip,
            rideEntry: rideEntry,
            rideTime: rideTime,
          ),
          color: const Color(0xFFE1F5FE),
          statusLabel: '待機',
          currentStepId: resolved.routeStepId,
          isMoving: false,
          step: step,
        );
      }

      return NavigationState(
        mainText: resolved.label,
        subText: _boardingSubText(
          trip: trip,
          rideEntry: rideEntry,
          rideTime: rideTime,
          planned: true,
        ),
        color: const Color(0xFFE1F5FE),
        statusLabel: '待機',
        currentStepId: resolved.routeStepId,
        isMoving: false,
        step: step,
      );
    }

    if (resolved.itemKind == ScheduleEntryKind.walk && step != null) {
      final nextRides =
          trip.schedule
              .where(
                (entry) =>
                    entry.legIndex == resolved.legIndex &&
                    entry.itemKind == ScheduleEntryKind.ride &&
                    !entry.plannedAt.isBefore(resolved.plannedAt),
              )
              .toList()
            ..sort((a, b) => a.plannedAt.compareTo(b.plannedAt));

      if (nextRides.isNotEmpty) {
        final destination = step.to;
        if (destination == null || destination.isEmpty) {
          throw StateError(
            '乗車前の徒歩stepに目的地がありません: stepId=${step.stepId}',
          );
        }

        final rideEntry = nextRides.first;
        final rideAt = rideEntry.plannedAt;
        final rideTime = _formatClock(rideAt);
        final remainingMinutes = _minutesUntil(rideAt, now);

        return NavigationState(
          mainText: '$rideTime $destinationにむかう　あと$remainingMinutes分',
          subText: _boardingSubText(
            trip: trip,
            rideEntry: rideEntry,
            rideTime: rideTime,
          ),
          color: const Color(0xFF81D4FA),
          statusLabel: '移動中',
          nextStopName: destination,
          currentStepId: step.stepId,
          step: step,
        );
      }
    }

    final diff = resolved.plannedAt.difference(now);
    if (diff.inMinutes > 20) {
      return NavigationState.waitingLong(entry: resolved, diff: diff);
    }

    final BusProgress? busProgress =
        routeState?.busProgress?.stepId == step?.stepId
        ? routeState?.busProgress
        : null;
    final RailProgress? railProgress =
        routeState?.railProgress?.stepId == step?.stepId
        ? routeState?.railProgress
        : null;
    return NavigationState.fromEntry(
      entry: resolved,
      step: step,
      busProgress: busProgress,
      railProgress: railProgress,
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

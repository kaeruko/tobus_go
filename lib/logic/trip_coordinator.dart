import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart'; // StepSeg
import 'trip_navigator.dart';
import 'schedule_resolver.dart';

class TripCoordinator {
  static DateTime _parseTime(DateTime date, String timeStr) {
    final parts = timeStr.split(':');
    if (parts.length < 2) return date;
    final h = int.tryParse(parts[0]) ?? 0;
    final m = int.tryParse(parts[1]) ?? 0;
    return DateTime(date.year, date.month, date.day, h, m);
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

  static ScheduleEntry? _fallbackEntryBeforeRide({
    required ScheduleResolveResult scheduleState,
    required ScheduleEntry rideEntry,
  }) {
    if (scheduleState.window.isEmpty) return null;

    int ridePos = -1;
    for (int i = 0; i < scheduleState.window.length; i++) {
      if (scheduleState.window[i].id == rideEntry.id) {
        ridePos = i;
        break;
      }
    }
    if (ridePos <= 0) return null;

    for (int j = ridePos - 1; j >= 0; j--) {
      final e = scheduleState.window[j];

      if (e.itemKind == ScheduleEntryKind.walk) return e;

      if (e.itemKind == ScheduleEntryKind.event) {
        if (e.generatedBy == ScheduleEntrySource.route && e.routeRole == 'wait_start') {
          return e;
        }
      }

      if (e.itemKind == ScheduleEntryKind.meeting) return e;
    }
    return scheduleState.window.first;
  }

  static ScheduleEntry _resolveWalkToRideTransition({
    required ScheduleEntry entry,
    required ScheduleResolveResult scheduleState,
    required RouteState? routeState,
    required DateTime now,
    String? realtimeBusLocationId,
  }) {
    if (entry.itemKind != ScheduleEntryKind.walk) return entry;

    ScheduleEntry? upcomingRide;

    for (final candidate in scheduleState.window) {
      if (candidate.itemKind != ScheduleEntryKind.ride) continue;
      if (candidate.legIndex != entry.legIndex) continue;

      // Ensure we only consider rides that are scheduled after or at the walk.
      if (candidate.plannedAt.isBefore(entry.plannedAt)) continue;
      if (entry.routeStepIndex != null &&
          candidate.routeStepIndex != null &&
          candidate.routeStepIndex! < entry.routeStepIndex!) {
        continue;
      }

      upcomingRide = candidate;
      break;
    }

    if (upcomingRide == null) return entry;

    final rideStep = _stepForEntry(routeState, upcomingRide);
    final rideHasStarted = rideStep != null &&
        _realtimeSaysRideStarted(
          step: rideStep,
          realtimeBusLocationId: realtimeBusLocationId,
        );

    final timeUntilRide = upcomingRide.plannedAt.difference(now);
    final rideWindowOpen = timeUntilRide <= const Duration(minutes: 5);

    if (rideHasStarted || rideWindowOpen) {
      return upcomingRide;
    }

    return entry;
  }

  static NavigationState _navFromEntry({
    required Trip trip,
    required DateTime now,
    required ScheduleEntry entry,
    required RouteState? routeState,
    required int stopIndex,
  }) {
    final step = _stepForEntry(routeState, entry);

    if (entry.itemKind == ScheduleEntryKind.walk && step != null) {
      return NavigationState.navigating(
        step: step,
        stopIndex: stopIndex,
        statusLabel: "移動中",
      );
    }

    if (entry.itemKind == ScheduleEntryKind.ride && step != null) {
      return NavigationState.navigating(
        step: step,
        stopIndex: stopIndex,
        statusLabel: "乗車中",
      );
    }

    if (entry.itemKind == ScheduleEntryKind.meeting) {
      return NavigationState(
        mainText: entry.label,
        subText: entry.description.isNotEmpty ? entry.description : "集合場所へ向かいましょう",
        color: const Color(0xFFC8E6C9),
        currentStepIndex: routeState?.currentStepIndex ?? 0,
        nextStopIndex: stopIndex,
        statusLabel: "集合",
        isMoving: false,
      );
    }

    if (entry.itemKind == ScheduleEntryKind.arrival || entry.itemKind == ScheduleEntryKind.goal) {
      return NavigationState(
        mainText: entry.label,
        subText: entry.description.isNotEmpty ? entry.description : "到着しました",
        color: const Color(0xFFFFCC80),
        currentStepIndex: routeState?.currentStepIndex ?? 0,
        nextStopIndex: stopIndex,
        statusLabel: "到着",
        isMoving: false,
      );
    }

    return NavigationState(
      mainText: entry.label,
      subText: entry.description.isNotEmpty ? entry.description : "時間まで待機しましょう",
      color: const Color(0xFFE1F5FE),
      currentStepIndex: routeState?.currentStepIndex ?? 0,
      nextStopIndex: stopIndex,
      statusLabel: "待機",
      isMoving: false,
    );
  }

  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required ScheduleResolveResult scheduleState,
    required RouteState? routeState,
    required DateTime now,
    String? realtimeBusLocationId,
    LatLng? currentPos, // Start accepting currentPos
  }) {
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

    final stopIndex = routeState?.nextStopIndex ?? 0;

    final active = scheduleState.activeEntry;
    if (active == null) {
      return NavigationState.idle();
    }

    // ★ 徒歩から乗車への遷移は時刻とリアルタイム位置で判断
    ScheduleEntry resolved = _resolveWalkToRideTransition(
      entry: active,
      scheduleState: scheduleState,
      routeState: routeState,
      now: now,
      realtimeBusLocationId: realtimeBusLocationId,
    );

    if (resolved.itemKind == ScheduleEntryKind.ride) {
      final step = _stepForEntry(routeState, resolved);

      bool rideStarted = false;
      if (step != null) {
        rideStarted = _realtimeSaysRideStarted(
          step: step,
          realtimeBusLocationId: realtimeBusLocationId,
        );
      }

      if (!rideStarted) {
        final timeUntilRide = resolved.plannedAt.difference(now);
        const rideLeadWindow = Duration(minutes: 5);
        const fallbackLeadWindow = Duration(minutes: 2);

        if (timeUntilRide > rideLeadWindow) {
          final fallback = _fallbackEntryBeforeRide(
            scheduleState: scheduleState,
            rideEntry: resolved,
          );
          if (fallback != null) {
            resolved = fallback;
          }
        } else if (timeUntilRide > -fallbackLeadWindow) {
          // Small grace window before departure. Keep ride state once the departure window opens.
        }
      }
    }

    debugPrint("[TripCoordinator] active=${active.label} kind=${active.itemKind} rt=${active.routeStepIndex} realtime=$realtimeBusLocationId");
    debugPrint("[TripCoordinator] resolved=${resolved.label} kind=${resolved.itemKind} rt=${resolved.routeStepIndex}");

    if (resolved.itemKind == ScheduleEntryKind.walk ||
        resolved.itemKind == ScheduleEntryKind.ride) {
      return _navFromEntry(
        trip: trip,
        now: now,
        entry: resolved,
        routeState: routeState,
        stopIndex: stopIndex,
      );
    }

    final diff = resolved.plannedAt.difference(now);

    if (diff.inMinutes > 20) {
      final remainder = "あと ${diff.inHours}時間${diff.inMinutes % 60}分";
      return NavigationState(
        mainText: resolved.label,
        subText: "開始まで $remainder",
        color: Colors.white,
        currentStepIndex: routeState?.currentStepIndex ?? 0,
        nextStopIndex: stopIndex,
        statusLabel: "開始前",
        isMoving: false,
      );
    }

    return _navFromEntry(
      trip: trip,
      now: now,
      entry: resolved,
      routeState: routeState,
      stopIndex: stopIndex,
    );
  }
}

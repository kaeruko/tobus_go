import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart'; // StepSeg
import 'trip_navigator.dart';
import 'schedule_resolver.dart';

import 'package:geolocator/geolocator.dart'; // Add for distanceBetween

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

  static ScheduleEntry _applyGpsGateForWalk({
    required ScheduleEntry entry,
    required RouteState? routeState,
    required LatLng? currentPos,
  }) {
    if (entry.itemKind != ScheduleEntryKind.walk) return entry;
    if (routeState == null) return entry;
    if (currentPos == null) return entry;

    final idx = entry.routeStepIndex;
    if (idx == null || idx < 0 || idx >= routeState.steps.length) return entry;

    final walkStep = routeState.steps[idx];
    if (walkStep.kind != 'walk') return entry;

    // walk の到着地点は、直後の ride の最初の stop を使う
    // (Walk step may not have stops or destination geometry in this model)
    if (idx + 1 >= routeState.steps.length) return entry;
    final next = routeState.steps[idx + 1];
    
    // Check if next step is a ride/wait that has stops. 
    // Wait steps might happen before ride, but typically walk leads to a location.
    // If next step is wait/ride, try to get its first stop.
    if (next.stops.isEmpty) return entry;
    
    final destPoint = next.stops.first.point; 
    final distM = Geolocator.distanceBetween(
      currentPos.latitude,
      currentPos.longitude,
      destPoint.latitude,
      destPoint.longitude,
    );
    
    debugPrint("[TripCoordinator] Walk GPS Check: dist=${distM.toStringAsFixed(1)}m limit=80m dest=${next.stops.first.name}");

    // 80m 以内なら walk 終了とみなして次を表示
    if (distM <= 80.0) {
      // Return a dummy event entry that represents "Arrived" / "Wait" phase
      // This will force the UI to show the next logical thing or a wait state
      return ScheduleEntry(
        id: entry.id, // Keep same ID or make dummy
        plannedAt: entry.plannedAt,
        label: '到着済み', // UI will typically see this or fall through logic
        description: 'まもなく出発です',
        itemKind: ScheduleEntryKind.event, // Change to event/wait
        legIndex: entry.legIndex,
        generatedBy: entry.generatedBy,
        routeStepIndex: idx + 1, // Advance index ref if possible
        routeRole: 'walk_done_by_gps',
      );
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

    // ★ GPSゲートによるWalk早期終了判定
    ScheduleEntry resolved = _applyGpsGateForWalk(
      entry: active,
      routeState: routeState,
      currentPos: currentPos,
    );

    if (resolved.itemKind == ScheduleEntryKind.ride) {
      final step = _stepForEntry(routeState, active);

      bool rideStarted = false;
      if (step != null) {
        rideStarted = _realtimeSaysRideStarted(
          step: step,
          realtimeBusLocationId: realtimeBusLocationId,
        );
      }

      if (!rideStarted) {
        final fallback = _fallbackEntryBeforeRide(
          scheduleState: scheduleState,
          rideEntry: resolved,
        );
        if (fallback != null) {
          resolved = fallback;
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

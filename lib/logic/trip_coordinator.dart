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
        "[TripCoordinator] 解決されたエントリにrouteStepIndexがありません: "
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

    ScheduleEntry resolved = active;

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
            if (destStopId != null) {
                // Determine if we are past the destination
                int destIndex = -1;
                int currentBusIndex = -1;
                
                for(int i=0; i<rideStep.stops.length; i++) {
                   if (rideStep.stops[i].stopId == destStopId) destIndex = i;
                   if (rideStep.stops[i].stopId == realtimeBusLocationId) currentBusIndex = i;
                }

                bool isPast = false;
                if (destIndex != -1 && currentBusIndex != -1) {
                   isPast = currentBusIndex >= destIndex;
                }

                // If not equal AND not past (i.e. truly before), then revert.
                // If we are at destination or past it, allow Arrival.
                // If realtime ID is unknown (not in list), we can't judge, so we fallback to strict check?
                // The log said "Bus pole ... found in API but not in step stops". 
                // So currentBusIndex might be -1 even if it is physically past.
                // However, we can't easily know the order of unknown stops here without more data.
                // BUT, if the realtime ID is NOT found in the step, it might be an issue.
                // The user's specific case: BunkaSanchome is NOT in rideStep.stops (because rideStep stops usually include only stops utilized in the leg?).
                // Wait, rideStep usually contains ALL stops in the path leg.
                // If the bus jumped WAY past the destination to a stop NOT in the leg...
                // We assume strict adherence to only reverting if we are SURE we are BEFORE.
                // If we are unsure (bus index -1), we should probably NOT revert if the time says Arrival, 
                // because we might have overshot. 
                // So: Revert ONLY if we find both and current < dest.
                
                bool shouldRevert = false;
                if (realtimeBusLocationId != destStopId) {
                   // If we know both positions and current < dest, then we definitely haven't arrived.
                   if (destIndex != -1 && currentBusIndex != -1) {
                      if (currentBusIndex < destIndex) {
                         shouldRevert = true;
                      }
                   } else if (destIndex != -1 && currentBusIndex == -1) {
                       // Realtime bus is at a stop NOT in our list.
                       // It could be before (e.g. previous leg?) or after (next leg).
                       // If we assume the bus location provided is for the CURRENT route/trip...
                       // If it's not in our list, effectively we don't know where it is relative to us.
                       // However, preventing Arrival in this case causes the "stuck" bug if we overshot.
                       // The safest bet for UX is: If scheduled time says Arrival, and we can't prove we are BEFORE, let it be Arrival.
                       // So we do NOT revert if currentBusIndex == -1.
                       shouldRevert = false;
                   } else {
                       // Strict equality check fallback if indexes failed (shouldn't happen if match)
                       // If we are here, realtimeId != destId.
                       // and we didn't find indexes. 
                       // Check logic again.
                       shouldRevert = true; 
                       // Wait, if currentBusIndex == -1 (unknown loc), we set to false above?
                       // Let's simplify.
                   }
                }
                
                // Refined logic:
                // Revert to ride IF:
                // 1. We assume we are NOT arrived yet (Strict)
                // 2. BUT we allow if we are Past.
                
                if (realtimeBusLocationId != destStopId) {
                   if (destIndex != -1 && currentBusIndex != -1) {
                      if (currentBusIndex < destIndex) {
                         // Clearly before destination
                         debugPrint("[TripCoordinator] バス位置判定: 目的地より手前 ($currentBusIndex < $destIndex)");
                         resolved = rideEntry;
                         addReason("premature_arrival_revert_index");
                      } else {
                         debugPrint("[TripCoordinator] バス位置判定: 目的地通過済み ($currentBusIndex >= $destIndex)");
                      }
                   } else {
                      // One of them is not in the list.
                      // Case A: Realtime bus is at a stop NOT in this segment.
                      // If it's an "unknown" stop, it might be way past.
                      // If strict check was 'true' before, it caused the bug.
                      // So we relax it: Only revert if we are CONFIDENT we are before.
                      // Meaning: if we don't know the bus index, we assume the schedule is correct (Arrival).
                      debugPrint("[TripCoordinator] バス位置判定: 位置関係不明のため、時刻表の到着判定を優先します (Realtime=$realtimeBusLocationId, Dest=$destStopId)");
                   }
                }
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
    debugPrint("[TripCoordinator] アクティブ=${resolvedState.activeEntry?.label} 種類=${resolvedState.activeEntry?.itemKind} rt=${resolvedState.activeEntry?.routeStepIndex} リアルタイム=$realtimeBusLocationId");
    debugPrint("[TripCoordinator] 解決済み=${resolved.label} 種類=${resolved.itemKind} rt=${resolved.routeStepIndex}");
    debugPrint("[TripCoordinator] 理由=${resolvedState.resolutionReason}");

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
    debugPrint('[TripCoordinator] アクティブステップを解決中 $now (ステップ数=${steps.length})');

    // Simple Time-Range Logic:
    // Select the latest step that has already "started" (plannedAt <= now).
    for (int i = 0; i < steps.length; i++) {
      if (steps[i].plannedAt.isBefore(now) || steps[i].plannedAt.isAtSameMomentAs(now)) {
        bestIndex = i;
      } else {
        // Step is in the future. Since steps are sorted, all subsequent steps are also in future.
        break;
      }
    }
    
    debugPrint('[TripCoordinator] 選択された最良インデックス(TimeRange): $bestIndex');
    return bestIndex;
  }
}

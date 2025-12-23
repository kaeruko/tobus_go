// lib/logic/schedule_resolver.dart
import 'package:flutter/foundation.dart';
import '../core/app_clock.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';

class ScheduleResolveResult {
  final int activeIndex;
  final String activeLabel;
  final int completedCount;
  final List<ScheduleEntry> window;
  final ScheduleEntry? activeEntry;

  const ScheduleResolveResult({
    required this.activeIndex,
    required this.activeLabel,
    required this.completedCount,
    required this.window,
    required this.activeEntry,
  });
}

class ScheduleResolver {
  static ScheduleResolveResult resolve({
    required List<ScheduleEntry> scheduleSorted,
    required DateTime now,
    Trip? trip,
    int? currentStepIndex,
    int? nextStopIndex,
    int prevCount = 1,
    int nextCount = 3,
    Duration nextThreshold = const Duration(minutes: 20),
  }) {
    int active = -1;
    String label = 'いま';

    // 0. If progress is available, use it to determine active index
    if (trip != null && currentStepIndex != null && currentStepIndex >= 0) {
      active = _findActiveIndexByProgress(scheduleSorted, trip, currentStepIndex, nextStopIndex);
    }
    
    // Fallback to time-based if progress didn't find a match or wasn't provided
    if (active == -1) {
      // 1. Determine Active Index (Time-based determination)
      final lastPastIndex = scheduleSorted.lastIndexWhere((e) => e.plannedAt.isBefore(now) || e.plannedAt.isAtSameMomentAs(now));

      if (lastPastIndex >= 0) {
        active = lastPastIndex;
        label = 'いま';
      } else {
        // Nothing has started yet. All future.
        if (scheduleSorted.isNotEmpty) {
          active = 0;
          final diff = scheduleSorted[0].plannedAt.difference(now);
          if (diff > nextThreshold) {
             label = 'そのうち';
          } else {
             label = 'つぎ';
          }
        }
      }
    }

    final activeEntry = (active >= 0 && active < scheduleSorted.length) ? scheduleSorted[active] : null;
    
    // Refine Label for future case or specific cases if needed (only if we didn't force it via progress?)
    // Actually, 'Now' label is usually fine for progress-based match too.
    if (activeEntry != null) {
      if (activeEntry.plannedAt.isAfter(now)) {
        // Future case but might be active due to progress
        // If determined by progress, we might want to keep 'Now' or 'Running'.
        // But if time says future, let's keep check.
        final diff = activeEntry.plannedAt.difference(now);
        if (diff > nextThreshold) {
           // careful: if we are physically there (progress matched), but schedule says 1 hour later,
           // we should probably trust progress = 'Now'.
           // _findActiveIndexByProgress returns a match only if we are in that step.
           // So if we found it via progress, we basically override label to 'Running' or 'Now'.
        } else {
           // label = 'つぎ'; // Time based 'Next'
        }
      }
    }

    // If active was determined by progress, let's enforce 'Now' (or similar)
    if (active != -1 && trip != null && currentStepIndex != null) {
      label = 'いま';
    }

    // 2. Completed Count
    final completedCount = (active >= 0) ? active : (scheduleSorted.isEmpty ? 0 : 0);

    // 3. Window Calculation
    final start = active >= 0 ? (active - prevCount) : 0;
    final safeStart = start < 0 ? 0 : start;

    final end = active >= 0 ? (active + nextCount) : (nextCount);
    final safeEnd = end >= scheduleSorted.length ? scheduleSorted.length - 1 : end;

    final window = (active >= 0 || scheduleSorted.isNotEmpty) 
        && safeStart <= safeEnd 
        ? scheduleSorted.sublist(safeStart, safeEnd + 1) 
        : <ScheduleEntry>[];

    return ScheduleResolveResult(
      activeIndex: active,
      activeLabel: label,
      completedCount: completedCount,
      window: window,
      activeEntry: activeEntry,
    );
  }

  /// Map route steps to schedule entries and find which entry corresponds to currentStepIndex
  static int _findActiveIndexByProgress(
    List<ScheduleEntry> schedule, 
    Trip trip, 
    int currentStepIndex,
    int? nextStopIndex,
  ) {
    debugPrint('[ScheduleResolver] currentStepIndex: $currentStepIndex, nextStopIndex: $nextStopIndex');

    // 1. Flatten all steps to match TripNavigator logic
    var allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();

    // ★追加: ステップが空（ルート未生成など）の場合は「完了」ではなく「判定不能(-1)」を返す
    // 以前は 0 >= 0 で完了扱いになっていた
    if (allSteps.isEmpty) {
      return -1;
    }

    if (currentStepIndex >= allSteps.length) {
      debugPrint('[ScheduleResolver] Completed route. Step $currentStepIndex >= ${allSteps.length}');
      // Completed route? return the last schedule item (Goal/Arrival)
      return schedule.length - 1; 
    }

    // 2. Iterate schedule and map to steps using routeStepIndex
    for (int i = 0; i < schedule.length; i++) {
      final entry = schedule[i];
      
      // ★重要: 現在アクティブなLeg (activeLegIndex) に属するエントリーのみを対象とする
      // これにより、物理的に同じ場所にいても「帰り」の予定が先にアクティブになるのを防ぐ
      if (entry.legIndex != trip.activeLegIndex) {
        continue;
      }

      // Only check entries that have a route step assigned
      if (entry.routeStepIndex != null) {
        if (entry.routeStepIndex == currentStepIndex) {
          // Match found by index. Now refine by role.
          debugPrint('[ScheduleResolver] Found potential match at index $i (Role: ${entry.routeRole}) for Step $currentStepIndex');
          
          if (entry.routeRole == 'walk') {
            // Walk step always matches the Walk entry
            return i;
          } else if (entry.routeRole == 'ride') {
             // Ride entry. 
             // 以前は remainingStops <= 1 の時に Arrival に切り替えていたが、
             // それだと「次到着します」の赤いナビ画面（Ride状態）が表示されず、
             // いきなり「到着しました」のスケジュール画面（Arrival状態）になってしまう。
             // そのため、ここは最後まで Ride として判定し、TripNavigator 側で「到着」を出すようにする。
             debugPrint('[ScheduleResolver] Ride entry matched. Keeping independent of remaining stops to show Navigation UI.');
             return i;
          } else if (entry.routeRole == 'arrival') {
             // Arrival entry.
             // Ride が終わって Step が進んだらここに来るはずだが、
             // 同じ StepIndex で複数の Entry (Ride, Arrival) がある場合、
             // 上の Ride で return しているのでここは基本通らない。
             // ただし、もし Ride エントリがない場合はここでマッチする。
             return i;
          }
        }
      }
    }

    return -1;
  }

  static List<ScheduleEntry> sortCopy(List<ScheduleEntry> entries) {
    final copy = [...entries];
    sortScheduleEntries(copy);
    return copy;
  }
}

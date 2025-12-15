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
    int prevCount = 1,
    int nextCount = 3,
    Duration nextThreshold = const Duration(minutes: 20),
  }) {
    int active = -1;
    String label = 'いま';

    // 0. If progress is available, use it to determine active index
    if (trip != null && currentStepIndex != null && currentStepIndex >= 0) {
      active = _findActiveIndexByProgress(scheduleSorted, trip, currentStepIndex);
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
    int currentStepIndex
  ) {
    debugPrint('[ScheduleResolver] currentStepIndex: $currentStepIndex');

    // 1. Flatten all steps to match TripNavigator logic
    var allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    if (currentStepIndex >= allSteps.length) {
      debugPrint('[ScheduleResolver] Completed route. Step $currentStepIndex >= ${allSteps.length}');
      // Completed route? return the last schedule item (Goal/Arrival)
      return schedule.length - 1; 
    }

    // 2. Iterate schedule and map to steps
    // Since schedule entries are more granular or sometimes aggregated (though usually 1-to-1 or 2-to-1 for ride),
    // we need to be careful.
    //
    // Schedule Generation Logic (from GroupModels):
    // - Walk (>3min): 1 Entry (Walk) -> consumes 'walk' step.
    // - Walk (<=3min): No Entry -> consumes 'walk' step.
    // - Ride: 2 Entries (Ride + Arrival) -> consumes 'transit' step.
    //
    // We strictly simulate the generation process to assign step indices to schedule entries.
    
    int stepCursor = 0;
    
    // We build a map of entryIndex -> stepIndex (or range)
    // Actually we just need to find the first entry that covers currentStepIndex.
    
    for (int i = 0; i < schedule.length; i++) {
      final entry = schedule[i];
      
      // Only Route-generated entries consume steps
      if (entry.generatedBy != ScheduleEntrySource.route) {
        continue;
      }
      
      if (stepCursor >= allSteps.length) break;
      final step = allSteps[stepCursor];
      debugPrint('[ScheduleResolver] Checking Entry $i: ${entry.label} (${entry.itemKind}) vs Step $stepCursor (${step.kind})');

      // Logic must match createScheduleFromRoute exactly-ish
      if (entry.itemKind == ScheduleEntryKind.walk) {
        // This corresponds to a walk step
        if (step.kind == 'walk') {
          // Found matching walk step
          if (stepCursor == currentStepIndex) {
            debugPrint('[ScheduleResolver] MATCH! Entry $i is active (Walk)');
            return i;
          }
          stepCursor++;
        } else {
          // Mismatch in sequence? (Schedule says walk, route says ride?)
          debugPrint('[ScheduleResolver] Mismatch! Schedule=Walk, Step=${step.kind}');
          // Should not happen if data is consistent.
          // Adjust cursor to find next walk? No, just continue or break?
          // Let's assume strict consistency for now.
        }
      } else if (entry.itemKind == ScheduleEntryKind.ride) {
        // This corresponds to a transit step (start)
        if (step.kind != 'walk') {
          // Ride + Arrival pair both cover this step
          // If we are in this step, we return the Ride entry (i)
          if (stepCursor == currentStepIndex) {
            debugPrint('[ScheduleResolver] MATCH! Entry $i is active (Ride)');
            return i;
          }
          // logic continues to next entry (Arrival) ...
          // IMPORTANT: The step is NOT consumed yet, Arrival needs to see it too.
        } else {
           debugPrint('[ScheduleResolver] Mismatch! Schedule=Ride, Step=Walk');
        }
      } else if (entry.itemKind == ScheduleEntryKind.arrival) {
        // This corresponds to a transit step (end)
        if (step.kind != 'walk') {
          if (stepCursor == currentStepIndex) {
            // We are still in the transit step.
            // But we already returned 'Ride' in the previous iteration if it existed?
            // Wait, if we returned in Ride, we wouldn't be here.
            
            // However! 'Ride' corresponds to 'Navigating to next stop'.
            // 'Arrival' corresponds to 'Getting off'.
            // TripNavigator doesn't distinguish nicely, it just gives 'currentStepIndex'.
            // But it gives 'remainingStops'.
            // If we wanted to be precise: 
            //   if remainingStops <= 1 -> return Arrival entry
            //   else -> return Ride entry
            // But we don't have remainingStops passed in yet.
            // For now, let's map 'Transit Step' -> 'Ride Entry'.
            // So if we fell through to Arrival (because Ride wasn't there? or we already passed Ride?),
            // Actually, in the loop:
            // i=Ride, matches step -> return i.
            // So we never reach Arrival for the same step unless we didn't return.
            // So Arrival will only be 'active' if we increment stepCursor? 
            // No, Arrival consumes the step.
            debugPrint('[ScheduleResolver] Arrival check. Step matches.');
            stepCursor++;
          }
        }
      } else if (entry.itemKind == ScheduleEntryKind.goal) {
          // Goal matches end of everything?
      } else {
        // Departure, Meeting, etc do not consume steps.
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

// lib/logic/schedule_resolver.dart
import '../core/app_clock.dart';
import '../models/group_models.dart';

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
    int prevCount = 1,
    int nextCount = 3,
    Duration nextThreshold = const Duration(minutes: 20),
  }) {
    // 1. Determine Active Index (Time-based determination)
    // "Active" = The entry that is currently in progress or the next one if none started.
    // Logic: Find the last entry where plannedAt <= now.
    // If found, that entry is "Now" (Active).
    // If not found (all future), the first entry is "Next" (Active).
    
    int active = -1;
    String label = 'いま';

    final lastPastIndex = scheduleSorted.lastIndexWhere((e) => e.plannedAt.isBefore(now) || e.plannedAt.isAtSameMomentAs(now));

    if (lastPastIndex >= 0) {
      // Something has started.
      // However, if the last entry is past, it remains active until the trip is possibly explicitly ended?
      // Or simply, the last past entry is the one we are "in".
      active = lastPastIndex;
      label = 'いま';
    } else {
      // Nothing has started yet. All future.
      if (scheduleSorted.isNotEmpty) {
        active = 0;
        final diff = scheduleSorted[0].plannedAt.difference(now);
        if (diff > nextThreshold) {
           label = 'そのうち'; // Or '開始前'
        } else {
           label = 'つぎ';
        }
      } else {
        // Empty schedule
        active = -1; // No active
      }
    }

    final activeEntry = (active >= 0 && active < scheduleSorted.length) ? scheduleSorted[active] : null;
    
    // Refine Label for future case or specific cases if needed
    if (activeEntry != null) {
      if (activeEntry.plannedAt.isAfter(now)) {
        // Future case
        final diff = activeEntry.plannedAt.difference(now);
        if (diff > nextThreshold) {
          label = '開始前';
        } else {
          label = 'つぎ';
        }
      }
    }

    // 2. Completed Count
    // Everything strictly before the active index is treated as completed.
    // If activeIndex is 0, completed is 0.
    // If activeIndex is 2, items 0 and 1 are completed (count = 2).
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

  static List<ScheduleEntry> sortCopy(List<ScheduleEntry> entries) {
    final copy = [...entries];
    sortScheduleEntries(copy);
    return copy;
  }
}

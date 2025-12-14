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
    final active = _effectiveActiveIndex(scheduleSorted, now);
    final activeEntry = active >= 0 && active < scheduleSorted.length ? scheduleSorted[active] : null;

    var label = 'いま';
    if (activeEntry != null) {
      final diff = activeEntry.plannedAt.difference(now);
      if (diff > nextThreshold) {
        label = 'つぎ';
      }
    }

    final completedCount = active >= 0 ? active : scheduleSorted.length;

    final start = active >= 0 ? (active - prevCount) : (scheduleSorted.length - prevCount - 1);
    final safeStart = start < 0 ? 0 : start;

    final end = active >= 0 ? (active + nextCount) : (scheduleSorted.length - 1);
    final safeEnd = end >= scheduleSorted.length ? scheduleSorted.length - 1 : end;

    final window = safeStart <= safeEnd ? scheduleSorted.sublist(safeStart, safeEnd + 1) : <ScheduleEntry>[];

    return ScheduleResolveResult(
      activeIndex: active,
      activeLabel: label,
      completedCount: completedCount,
      window: window,
      activeEntry: activeEntry,
    );
  }

  static int _effectiveActiveIndex(List<ScheduleEntry> scheduleSorted, DateTime now) {
    final idx = scheduleSorted.indexWhere((e) => !e.isCompleted);
    if (idx < 0) return -1;

    if (idx + 1 < scheduleSorted.length) {
      final current = scheduleSorted[idx];
      final next = scheduleSorted[idx + 1];

      if (current.itemKind == ScheduleEntryKind.meeting) {
        if (now.isAfter(next.plannedAt)) {
          return idx + 1;
        }
      }
    }

    return idx;
  }

  static List<ScheduleEntry> sortCopy(List<ScheduleEntry> entries) {
    final copy = [...entries];
    sortScheduleEntries(copy);
    return copy;
  }
}

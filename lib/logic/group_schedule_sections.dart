import '../models/group_models.dart';

class OnsiteScheduleWindow {
  final DateTime start;
  final DateTime end;

  const OnsiteScheduleWindow({
    required this.start,
    required this.end,
  });

  bool contains(DateTime value) {
    return !value.isBefore(start) && value.isBefore(end);
  }

  DateTime get midpoint {
    final span = end.difference(start);
    if (span <= Duration.zero) {
      throw StateError(
        '現地予定の時間帯が不正です: start=$start, end=$end',
      );
    }
    return start.add(Duration(seconds: span.inSeconds ~/ 2));
  }
}

class GroupScheduleRouteSection {
  final int legIndex;
  final List<ScheduleEntry> entries;

  const GroupScheduleRouteSection({
    required this.legIndex,
    required this.entries,
  });
}

class GroupScheduleSections {
  final List<ScheduleEntry> outboundRoute;
  final List<ScheduleEntry> onsiteEntries;
  final List<ScheduleEntry> inboundRoute;
  final List<GroupScheduleRouteSection> additionalRoutes;

  const GroupScheduleSections({
    required this.outboundRoute,
    required this.onsiteEntries,
    required this.inboundRoute,
    required this.additionalRoutes,
  });

  factory GroupScheduleSections.fromEntries(List<ScheduleEntry> entries) {
    final outbound = <ScheduleEntry>[];
    final inbound = <ScheduleEntry>[];
    final onsite = <ScheduleEntry>[];
    final additional = <int, List<ScheduleEntry>>{};

    for (final entry in entries) {
      if (entry.generatedBy == ScheduleEntrySource.manual) {
        onsite.add(entry);
        continue;
      }

      switch (entry.legIndex) {
        case 0:
          outbound.add(entry);
          break;
        case 1:
          inbound.add(entry);
          break;
        default:
          if (entry.legIndex < 0) {
            throw StateError(
              'route生成予定のlegIndexが不正です: '
              'entryId=${entry.id}, legIndex=${entry.legIndex}',
            );
          }
          additional.putIfAbsent(entry.legIndex, () => []).add(entry);
      }
    }

    _sortByTime(outbound);
    _sortByTime(inbound);
    _sortByTime(onsite);

    final additionalSections = additional.entries
        .map((entry) {
          final routeEntries = List<ScheduleEntry>.from(entry.value);
          _sortByTime(routeEntries);
          return GroupScheduleRouteSection(
            legIndex: entry.key,
            entries: routeEntries,
          );
        })
        .toList(growable: false)
      ..sort((a, b) => a.legIndex.compareTo(b.legIndex));

    return GroupScheduleSections(
      outboundRoute: List.unmodifiable(outbound),
      onsiteEntries: List.unmodifiable(onsite),
      inboundRoute: List.unmodifiable(inbound),
      additionalRoutes: List.unmodifiable(additionalSections),
    );
  }

  OnsiteScheduleWindow requireOnsiteWindow() {
    if (outboundRoute.isEmpty) {
      throw StateError('現地予定の開始を決める往路予定がありません');
    }
    if (inboundRoute.isEmpty) {
      throw StateError('現地予定の終了を決める復路予定がありません');
    }

    final start = outboundRoute.last.plannedAt;
    final end = inboundRoute.first.plannedAt;
    if (!end.isAfter(start)) {
      throw StateError(
        '現地予定の時間帯がありません: '
        'outboundEnd=$start, inboundStart=$end',
      );
    }
    return OnsiteScheduleWindow(start: start, end: end);
  }

  static void _sortByTime(List<ScheduleEntry> entries) {
    final indexed = entries.asMap().entries.toList();
    indexed.sort((a, b) {
      final time = a.value.plannedAt.compareTo(b.value.plannedAt);
      if (time != 0) return time;
      return a.key.compareTo(b.key);
    });
    for (var i = 0; i < indexed.length; i++) {
      entries[i] = indexed[i].value;
    }
  }
}

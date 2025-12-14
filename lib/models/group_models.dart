// lib/models/group_models.dart

import 'package:cloud_firestore/cloud_firestore.dart';
import 'leg_models.dart';
import 'route_models.dart';

enum ScheduleEntryKind {
  meeting,
  departure,
  ride,
  walk,
  arrival,
  goal,
  event,
}

enum ScheduleEntrySource {
  route,
  manual,
}

class ScheduleEntry {
  final DateTime plannedAt;
  final String label;
  final String description;
  final ScheduleEntryKind itemKind;
  final int legIndex;
  final ScheduleEntrySource generatedBy;
  bool isCompleted;
  final bool locked;

  ScheduleEntry({
    required this.plannedAt,
    required this.label,
    this.description = '',
    this.itemKind = ScheduleEntryKind.event,
    this.legIndex = 0,
    this.generatedBy = ScheduleEntrySource.manual,
    this.locked = false,
    this.isCompleted = false,
  });

  factory ScheduleEntry.fromJson(Map<String, dynamic> json) {
    return ScheduleEntry(
      plannedAt: (json['plannedAt'] as Timestamp).toDate(),
      label: json['label'] as String? ?? '',
      description: json['description'] as String? ?? '',
      itemKind: ScheduleEntryKind.values.firstWhere(
        (e) => e.name == (json['itemKind'] as String?),
        orElse: () => ScheduleEntryKind.event,
      ),
      legIndex: json['legIndex'] as int? ?? 0,
      generatedBy: ScheduleEntrySource.values.firstWhere(
        (e) => e.name == (json['generatedBy'] as String?),
        orElse: () => ScheduleEntrySource.manual,
      ),
      locked: json['locked'] as bool? ?? false,
      isCompleted: json['isCompleted'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'plannedAt': Timestamp.fromDate(plannedAt),
      'label': label,
      'description': description,
      'itemKind': itemKind.name,
      'legIndex': legIndex,
      'generatedBy': generatedBy.name,
      'locked': locked,
      'isCompleted': isCompleted,
    };
  }
}

/// Sort entries by leg then time using DateTime.
void sortScheduleEntries(List<ScheduleEntry> entries) {
  entries.sort((a, b) {
    if (a.legIndex != b.legIndex) {
      return a.legIndex.compareTo(b.legIndex);
    }
    return a.plannedAt.compareTo(b.plannedAt);
  });
}

/// Normalize a sequence of HH:mm strings so that times after midnight roll into the next day.
List<DateTime> normalizeCrossDay(DateTime baseDate, List<String?> clocks) {
  final results = <DateTime>[];
  var cursor = DateTime(baseDate.year, baseDate.month, baseDate.day, 0, 0);

  for (final clock in clocks) {
    if (clock == null || !clock.contains(':')) {
      results.add(cursor);
      continue;
    }
    final parts = clock.split(':');
    final hour = int.tryParse(parts[0]) ?? 0;
    final minute = int.tryParse(parts[1]) ?? 0;
    var candidate = DateTime(cursor.year, cursor.month, cursor.day, hour, minute);
    if (results.isNotEmpty && candidate.isBefore(results.last)) {
      candidate = candidate.add(const Duration(days: 1));
    }
    cursor = candidate;
    results.add(candidate);
  }

  return results;
}

List<ScheduleEntry> createScheduleFromRoute(
  Candidate route, {
  DateTime? startDateTime,
  String? labelPrefix,
  int legIndex = 0,
}) {
  final list = <ScheduleEntry>[];
  final prefix = (labelPrefix != null && labelPrefix.isNotEmpty)
      ? '$labelPrefix '
      : '';

  final departureBase = startDateTime ?? route.departureDate ?? DateTime.now();
  final stepClocks = route.steps
      .expand((s) => [s.departureTime, s.arrivalTime])
      .cast<String?>()
      .toList();
  final normalizedTimes = normalizeCrossDay(departureBase, stepClocks);
  var timeCursorIndex = 0;

  list.add(
    ScheduleEntry(
      plannedAt: departureBase,
      label: '${prefix}出発',
      description: 'みんな揃っているか確認しましょう',
      itemKind: ScheduleEntryKind.departure,
      legIndex: legIndex,
      generatedBy: ScheduleEntrySource.route,
    ),
  );

  for (final step in route.steps) {
    if (step.kind == 'walk') {
      if ((step.minutes ?? 0) > 3) {
        final departAt = normalizedTimes[timeCursorIndex];
        timeCursorIndex += 2; // walk has dep/arr pairs
        list.add(
          ScheduleEntry(
            plannedAt: departAt,
            label: '${prefix}歩く (${step.minutes}分)',
            description: step.from ?? '',
            itemKind: ScheduleEntryKind.walk,
            legIndex: legIndex,
            generatedBy: ScheduleEntrySource.route,
          ),
        );
      } else {
        timeCursorIndex += 2;
      }
    } else {
      final departAt = normalizedTimes[timeCursorIndex];
      final arriveAt = normalizedTimes[timeCursorIndex + 1];
      timeCursorIndex += 2;

      list.add(
        ScheduleEntry(
          plannedAt: departAt,
          label: '${prefix}${step.title} に乗る',
          description: '${step.from ?? ''} から',
          itemKind: ScheduleEntryKind.ride,
          legIndex: legIndex,
          generatedBy: ScheduleEntrySource.route,
        ),
      );

      list.add(
        ScheduleEntry(
          plannedAt: arriveAt,
          label: '${prefix}${step.to ?? ''} に着く',
          description: step.edges > 0 ? '${step.edges}駅' : '',
          itemKind: ScheduleEntryKind.arrival,
          legIndex: legIndex,
          generatedBy: ScheduleEntrySource.route,
        ),
      );
    }
  }

  if (route.steps.isNotEmpty) {
    list.add(
      ScheduleEntry(
        plannedAt: normalizedTimes.isNotEmpty
            ? normalizedTimes.last
            : departureBase,
        label: '${prefix}目的地 到着',
        description: 'お疲れ様でした!',
        itemKind: ScheduleEntryKind.goal,
        legIndex: legIndex,
        generatedBy: ScheduleEntrySource.route,
      ),
    );
  }

  return list;
}

List<ScheduleEntry> createScheduleFromLegs(List<Leg> legs) {
  final List<ScheduleEntry> schedule = [];

  Leg? outbound;
  Leg? inbound;

  for (final leg in legs) {
    if (leg.direction == LegDirection.outbound) {
      outbound = leg;
    } else if (leg.direction == LegDirection.inbound) {
      inbound = leg;
    }
  }

  if (outbound != null) {
    schedule.addAll(
      createScheduleFromRoute(
        outbound.candidate,
        startDateTime: outbound.candidate.departureDate,
        labelPrefix: '行き',
        legIndex: 0,
      ),
    );
  }

  if (inbound != null) {
    final inboundStartDate = inbound.candidate.departureDate ??
        (outbound?.candidate.departureDate?.add(Duration(minutes: outbound.candidate.totalTime)) ??
            DateTime.now());

    if (outbound != null) {
      schedule.add(
        ScheduleEntry(
          plannedAt: inboundStartDate,
          label: '帰りの集合',
          description: '帰りの経路を開始する前に人数を確認しましょう',
          itemKind: ScheduleEntryKind.meeting,
          legIndex: 1,
          generatedBy: ScheduleEntrySource.route,
        ),
      );
    }

    schedule.addAll(
      createScheduleFromRoute(
        inbound.candidate,
        startDateTime: inboundStartDate,
        labelPrefix: '帰り',
        legIndex: 1,
      ),
    );
  }

  for (final leg in legs) {
    if (leg == outbound || leg == inbound) continue;
    final prefix = _labelForLeg(leg.direction);
    final startDateTime = leg.candidate.departureDate ?? DateTime.now();
    schedule.addAll(
      createScheduleFromRoute(
        leg.candidate,
        startDateTime: startDateTime,
        labelPrefix: prefix,
        legIndex: 0,
      ),
    );
  }

  sortScheduleEntries(schedule);
  return schedule;
}

String _labelForLeg(LegDirection direction) {
  switch (direction) {
    case LegDirection.outbound:
      return '行き';
    case LegDirection.inbound:
      return '帰り';
    case LegDirection.other:
      return '移動';
    case LegDirection.unknown:
      return '経路';
  }
}

String formatClock(DateTime dt) {
  return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
}

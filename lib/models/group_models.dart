// lib/models/group_models.dart
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:uuid/uuid.dart';
import '../core/app_clock.dart';
import 'leg_models.dart';
import 'route_models.dart';
import 'trip_models.dart';

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
  final String id;
  final DateTime plannedAt;
  final String label;
  final String description;
  final ScheduleEntryKind itemKind;
  final int legIndex;
  final ScheduleEntrySource generatedBy;
  final bool locked;

  final int? routeStepIndex;
  final String? routeRole;

  ScheduleEntry({
    String? id,
    required this.plannedAt,
    required this.label,
    this.description = '',
    this.itemKind = ScheduleEntryKind.event,
    this.legIndex = 0,
    this.generatedBy = ScheduleEntrySource.manual,
    this.locked = false,
    this.routeStepIndex,
    this.routeRole,
  }) : id = id ?? const Uuid().v4();

  factory ScheduleEntry.fromJson(Map<String, dynamic> json) {
    final plannedAt = (json['plannedAt'] as Timestamp).toDate();
    final label = json['label'] as String? ?? '';
    
    // Generate deterministic ID for legacy data to ensure UI stability
    final fallbackId = '${plannedAt.millisecondsSinceEpoch}_${label.hashCode}';

    return ScheduleEntry(
      id: json['id'] as String? ?? fallbackId,
      plannedAt: plannedAt,
      label: label,
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
      routeStepIndex: json['routeStepIndex'] as int?,
      routeRole: json['routeRole'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'plannedAt': Timestamp.fromDate(plannedAt),
      'label': label,
      'description': description,
      'itemKind': itemKind.name,
      'legIndex': legIndex,
      'generatedBy': generatedBy.name,
      'locked': locked,
      'routeStepIndex': routeStepIndex,
      'routeRole': routeRole,
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
  bool includeMeeting = false,
  String meetingLabel = '集合',
  String meetingDescription = '出発前に集合しましょう',
  Duration meetingLeadTime = const Duration(minutes: 10),
  Duration departureLeadTime = Duration.zero,
  DateTime? meetingAt,
  int baseStepIndex = 0, // ★追加: ステップ番号のオフセット
  bool shiftToStart = false, // ★追加: 開始時刻に合わせて予定全体をスライドさせるか
}) {
  final list = <ScheduleEntry>[];
  final prefix = (labelPrefix != null && labelPrefix.isNotEmpty)
      ? '$labelPrefix '
      : '';

  var departureBase = startDateTime ?? route.departureDate ?? appClock.now();
  final stepClocks = route.steps
      .expand((s) => [s.departureTime, s.arrivalTime])
      .cast<String?>()
      .toList();
  var normalizedTimes = normalizeCrossDay(departureBase, stepClocks);

  // Back-fill missing times if the start is missing (e.g. initial walk)
  final firstValidIndex = stepClocks.indexWhere((s) => s != null && s.contains(':'));
  if (firstValidIndex > 0) {
    for (var k = firstValidIndex - 1; k >= 0; k--) {
      // k+1 is always valid boundary because we start < firstValidIndex <= length
      if (k % 2 != 0) {
        // Arrival time (index k) -> Match next departure time (index k+1)
        normalizedTimes[k] = normalizedTimes[k + 1];
      } else {
        // Departure time (index k) -> Arrival time (index k+1) - duration
        final step = route.steps[k ~/ 2];
        final duration = step.minutes ?? 0;
        normalizedTimes[k] = normalizedTimes[k + 1].subtract(Duration(minutes: duration));
      }
    }
  }

  // ★追加: 開始時刻に合わせてスライドさせる処理
  if (shiftToStart && normalizedTimes.isNotEmpty) {
    final firstPlanned = normalizedTimes.first;
    final diff = departureBase.difference(firstPlanned);
    if (diff != Duration.zero) {
      normalizedTimes = normalizedTimes.map((t) => t.add(diff)).toList();
    }
  }

  final firstStepDeparture =
      normalizedTimes.isNotEmpty ? normalizedTimes.first : departureBase;
  final departureAt = firstStepDeparture.subtract(departureLeadTime);
  var timeCursorIndex = 0;

  if (includeMeeting) {
    final meetingTitle = prefix.isNotEmpty ? '$prefix$meetingLabel' : meetingLabel;
    final plannedMeeting = meetingAt ?? departureAt.subtract(meetingLeadTime);
    list.add(
      ScheduleEntry(
        plannedAt: plannedMeeting.isAfter(departureAt) ? departureAt : plannedMeeting,
        label: meetingTitle,
        description: meetingDescription,
        itemKind: ScheduleEntryKind.meeting,
        legIndex: legIndex,
        generatedBy: ScheduleEntrySource.route,
      ),
    );
  }

  list.add(
    ScheduleEntry(
      plannedAt: departureAt,
      label: '${prefix}出発',
      description: 'みんな揃っているか確認しましょう',
      itemKind: ScheduleEntryKind.departure,
      legIndex: legIndex,
      generatedBy: ScheduleEntrySource.route,
    ),
  );

  var stepIndex = baseStepIndex; // ★変更: 0からではなくオフセットから開始
  for (final step in route.steps) {
    if (step.kind == 'walk') {
      if ((step.minutes ?? 0) > 3) {
        final departAt = normalizedTimes[timeCursorIndex];
        timeCursorIndex += 2; // walk has dep/arr pairs
        list.add(
          ScheduleEntry(
            plannedAt: departAt,
            label: '${prefix}${step.from ?? ''}まで歩く (${step.minutes}分)',
            description: '',
            itemKind: ScheduleEntryKind.walk,
            legIndex: legIndex,
            generatedBy: ScheduleEntrySource.route,
            routeStepIndex: stepIndex,
            routeRole: 'walk',
          ),
        );
      } else {
        timeCursorIndex += 2;
      }
    } else {
      final departAt = normalizedTimes[timeCursorIndex];
      final arriveAt = normalizedTimes[timeCursorIndex + 1];
      timeCursorIndex += 2;

      final transportIcon = _emojiForKind(step.kind);

      list.add(
        ScheduleEntry(
          plannedAt: departAt,
          label: '$transportIcon$prefix${step.title} ${step.from ?? ''}に乗る',
          description: '',
          itemKind: ScheduleEntryKind.ride,
          legIndex: legIndex,
          generatedBy: ScheduleEntrySource.route,
          routeStepIndex: stepIndex,
          routeRole: 'ride',
        ),
      );

      list.add(
        ScheduleEntry(
          plannedAt: arriveAt,
          label: '$transportIcon$prefix${step.title} ${step.to ?? ''}に着く',
          description: '',
          itemKind: ScheduleEntryKind.arrival,
          legIndex: legIndex,
          generatedBy: ScheduleEntrySource.route,
          routeStepIndex: stepIndex,
          routeRole: 'arrival',
        ),
      );
    }
    stepIndex++;
  }

  if (route.steps.isNotEmpty) {
    // 目的地名を取得 (例: "銀座駅")
    String goalLabel = '目的地';
    if (route.destinationName != null && route.destinationName!.isNotEmpty) {
      goalLabel = route.destinationName!.split(' ').last; 
    }

    list.add(
      ScheduleEntry(
        plannedAt: normalizedTimes.isNotEmpty
            ? normalizedTimes.last
            : departureBase,
        label: '${prefix}$goalLabel 到着',
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

  // Calculate base step indices for each leg to ensure global uniqueness matching TripNavigator
  int currentStepBase = 0;
  final Map<Leg, int> legBaseIndices = {};
  for (final leg in legs) {
    legBaseIndices[leg] = currentStepBase;
    currentStepBase += leg.candidate.steps.length;
  }


  if (outbound != null) {
    schedule.addAll(
      createScheduleFromRoute(
        outbound.candidate,
        startDateTime: outbound.candidate.departureDate,
        labelPrefix: '➡️',
        legIndex: 0,
        includeMeeting: true,
        meetingLabel: '${Trip.extractSimpleName(outbound.candidate.originName ?? '')}集合',
        meetingDescription: 'みんな揃っているか確認しましょう',
        baseStepIndex: legBaseIndices[outbound] ?? 0, // Pass offset
      ),
    );
  }

  if (inbound != null) {
    final inboundStartDate = inbound.candidate.departureDate ??
        (outbound?.candidate.departureDate?.add(Duration(minutes: outbound.candidate.totalTime)) ??
            appClock.now());

    final inboundStepClocks = inbound.candidate.steps
        .expand((s) => [s.departureTime, s.arrivalTime])
        .cast<String?>()
        .toList();

    final inboundNormalizedTimes = normalizeCrossDay(
      inboundStartDate,
      inboundStepClocks,
    );

    // Back-fill missing times for inbound leg as well
    final inboundFirstValidIndex = inboundStepClocks.indexWhere((s) => s != null && s.contains(':'));
    if (inboundFirstValidIndex > 0) {
      for (var k = inboundFirstValidIndex - 1; k >= 0; k--) {
        if (k % 2 != 0) {
          inboundNormalizedTimes[k] = inboundNormalizedTimes[k + 1];
        } else {
          final step = inbound.candidate.steps[k ~/ 2];
          final duration = step.minutes ?? 0;
          inboundNormalizedTimes[k] = inboundNormalizedTimes[k + 1].subtract(Duration(minutes: duration));
        }
      }
    }

    final inboundFirstDeparture = inboundNormalizedTimes.isNotEmpty
        ? inboundNormalizedTimes.first
        : inboundStartDate;
    final inboundDepartureAt =
        inboundFirstDeparture.subtract(const Duration(minutes: 10));

    schedule.addAll(
      createScheduleFromRoute(
        inbound.candidate,
        startDateTime: inboundStartDate,
        labelPrefix: '⬅️',
        legIndex: 1,
        includeMeeting: true,
        meetingLabel: '帰りの集合',
        meetingDescription: '帰りの経路を開始する前に人数を確認しましょう',
        departureLeadTime: const Duration(minutes: 10),
        meetingAt: _roundDownToHalfHour(inboundDepartureAt.subtract(const Duration(minutes: 15))),
        baseStepIndex: legBaseIndices[inbound] ?? 0, // Pass offset
      ),
    );
  }

  for (final leg in legs) {
    if (leg == outbound || leg == inbound) continue;
    final prefix = _labelForLeg(leg.direction);
    final startDateTime = leg.candidate.departureDate ?? appClock.now();
    schedule.addAll(
      createScheduleFromRoute(
        leg.candidate,
        startDateTime: startDateTime,
        labelPrefix: prefix,
        legIndex: 0,
        baseStepIndex: legBaseIndices[leg] ?? 0, // Pass offset
      ),
    );
  }

  sortScheduleEntries(schedule);
  return schedule;
}

String _emojiForKind(String kind) {
  if (kind == 'bus') return '🚌';
  if (kind == 'subway' || kind == 'train') return '🚞';
  return '🚐'; // default/other
}

String _labelForLeg(LegDirection direction) {
  switch (direction) {
    case LegDirection.outbound:
      return '➡️';
    case LegDirection.inbound:
      return '⬅️';
    case LegDirection.other:
      return '移動';
    case LegDirection.unknown:
      return '経路';
  }
}

String formatClock(DateTime dt) {
  return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
}

DateTime _roundDownToHalfHour(DateTime dt) {
  final minute = dt.minute;
  final roundedMinute = minute >= 30 ? 30 : 0;
  return DateTime(dt.year, dt.month, dt.day, dt.hour, roundedMinute);
}

// lib/models/group_models.dart
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:uuid/uuid.dart';
import '../core/app_clock.dart';
import 'leg_models.dart';
import 'route_models.dart';
import '../utils/string_utils.dart';

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
  final String? routeStepId;
  final String? routeRole;

  ScheduleEntry({
    String? id,
    required this.plannedAt,
    required this.label,
    this.description = '',
    this.itemKind = ScheduleEntryKind.event,
    this.legIndex = 0,
    this.generatedBy = ScheduleEntrySource.manual,
    this.routeStepId,
    this.routeRole,
  }) : id = id ?? const Uuid().v4();

  factory ScheduleEntry.fromJson(Map<String, dynamic> json) {
    final plannedAt = (json['plannedAt'] as Timestamp).toDate();
    final label = json['label'] as String;

    return ScheduleEntry(
      id: json['id'] as String,
      plannedAt: plannedAt,
      label: label,
      description: json['description'] as String? ?? '', // Optional field check remains for safety
      itemKind: ScheduleEntryKind.values.byName(json['itemKind'] as String), // orElse removed
      legIndex: json['legIndex'] as int, // Default removed
      generatedBy: ScheduleEntrySource.values.byName(json['generatedBy'] as String), // orElse removed
      routeStepId: json['routeStepId'] as String?,
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
      'routeStepId': routeStepId,
      'routeRole': routeRole,
    };
  }
}

/// Sort entries by leg then time using DateTime.
void sortScheduleEntries(List<ScheduleEntry> entries) {
  final indexed = entries.asMap().entries.toList();
  indexed.sort((a, b) {
    final aEntry = a.value;
    final bEntry = b.value;
    if (aEntry.legIndex != bEntry.legIndex) {
      return aEntry.legIndex.compareTo(bEntry.legIndex);
    }
    final timeDiff = aEntry.plannedAt.compareTo(bEntry.plannedAt);
    if (timeDiff != 0) {
      return timeDiff;
    }
    return a.key.compareTo(b.key);
  });
  for (var i = 0; i < indexed.length; i++) {
    entries[i] = indexed[i].value;
  }
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
  // 最初が「徒歩 → 待ち → 乗車」なら、
  // 待ち時間を家で過ごして、乗車時刻から徒歩を逆算する。
  final hasLeadingWait =
      route.steps.length >= 3 &&
      route.steps[0].kind == 'walk' &&
      route.steps[1].kind == 'wait' &&
      (route.steps[2].kind == 'bus' || route.steps[2].kind == 'rail');

  if (hasLeadingWait) {
    final walk = route.steps[0];
    final wait = route.steps[1];
    final ride = route.steps[2];

    if (walk.minutes <= 0) {
      throw StateError(
        '先頭徒歩区間の所要時間が不正です: ${walk.minutes}',
      );
    }

    if (wait.arrivalTime == null ||
        !wait.arrivalTime!.contains(':') ||
        ride.departureTime == null ||
        !ride.departureTime!.contains(':')) {
      throw StateError(
        '待ち時間を徒歩開始時刻へ繰り込むための時刻情報がありません。'
        ' wait.arrivalTime=${wait.arrivalTime},'
        ' ride.departureTime=${ride.departureTime}',
      );
    }

    // indexes:
    // 0 = walk departure
    // 1 = walk arrival
    // 2 = wait start
    // 3 = wait end
    // 4 = ride departure
    final boardingAt = normalizedTimes[4];

    if (normalizedTimes[3] != boardingAt) {
      throw StateError(
        '待ち終了時刻と乗車時刻が一致しません。'
        ' waitEnd=${normalizedTimes[3]}, boardingAt=$boardingAt',
      );
    }

    final leaveAt =
        boardingAt.subtract(Duration(minutes: walk.minutes));

    // 徒歩を乗車時刻に合わせて後ろへずらす
    normalizedTimes[0] = leaveAt;
    normalizedTimes[1] = boardingAt;

    // 待ち時間を0分にする
    normalizedTimes[2] = boardingAt;
    normalizedTimes[3] = boardingAt;
  }


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

  // ★Fallback: 時刻が取得できない場合はアンカーから積み上げ
  final bool isTimeValid = normalizedTimes.isNotEmpty;
  DateTime cursorTime = departureBase;

  // ★Shift: 開始時刻に合わせてスライド (時刻が有効な場合のみ)
  if (isTimeValid && shiftToStart && normalizedTimes.isNotEmpty) {
    final firstPlanned = normalizedTimes.first;
    final diff = departureBase.difference(firstPlanned);
    if (diff != Duration.zero) {
      normalizedTimes = normalizedTimes.map((t) => t.add(diff)).toList();
    }
  }

  final firstStepDeparture =
      isTimeValid ? normalizedTimes.first : departureBase;
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
        routeStepId: null,
      ),
    );
  }

  // NOTE: 出発(ScheduleEntryKind.departure)は削除されました

  for (int i = 0; i < route.steps.length; i++) {
    final step = route.steps[i];
    
    if (step.kind == 'walk') {
      DateTime departAt;
      if (isTimeValid) {
        departAt = normalizedTimes[timeCursorIndex];
        timeCursorIndex += 2; // walk has dep/arr pairs
      } else {
        departAt = cursorTime;
        cursorTime = cursorTime.add(Duration(minutes: step.minutes ?? 0));
      }

      // ★Label: 目的地優先のラベル生成
      String walkLabel;
      final isFirstStep = (i == 0);
      
      // 優先順位: to > place > from
      if (step.to != null && step.to!.isNotEmpty) {
        walkLabel = isFirstStep 
            ? '${step.to}まで歩く' // 最初のステップなら「〜まで歩く」を強調
            : '${step.to}まで歩く';
      } else if (step.place != null && step.place!.isNotEmpty) {
         walkLabel = '${step.place}まで歩く';
      } else {
         walkLabel = '${step.from ?? ''}から歩く';
      }
      
      // 分数表示
      final minutes = step.minutes ?? 0;
      final durationStr = minutes > 0 ? ' ($minutes分)' : '';

      list.add(
        ScheduleEntry(
          plannedAt: departAt,
          label: '$prefix$walkLabel$durationStr',
          description: '',
          itemKind: ScheduleEntryKind.walk,
          legIndex: legIndex,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: step.stepId,
          routeRole: 'walk',
        ),
      );
    } else if (step.kind == 'wait') {
      DateTime startAt;
      DateTime endAt;
      int durationMinutes = 0;

      if (isTimeValid) {
        startAt = normalizedTimes[timeCursorIndex];
        endAt = normalizedTimes[timeCursorIndex + 1];
        timeCursorIndex += 2;
        durationMinutes = endAt.difference(startAt).inMinutes;

        if (durationMinutes == 0) {
          continue;
        }

        if (durationMinutes < 0) {
          throw StateError(
            '待ち時間が負になりました: $durationMinutes分',
          );
        }


      } else {
        startAt = cursorTime;
        durationMinutes = step.minutes ?? 0; // waitステップ自体に分数がなければ0
        endAt = startAt.add(Duration(minutes: durationMinutes));
        cursorTime = endAt;
      }

      // Wait (Duration)
      final waitLabel = step.startLabel != null
              ? '$prefix${step.startLabel} ${step.place ?? ''}'
              : '${prefix}待ち時間';
      
      final durationStr = durationMinutes > 0 ? ' ($durationMinutes分)' : '';

      list.add(
        ScheduleEntry(
          plannedAt: startAt,
          label: '$waitLabel$durationStr',
          description: '',
          itemKind: ScheduleEntryKind.event,
          legIndex: legIndex,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: step.stepId,
          routeRole: 'wait_start',
        ),
      );
      // NOTE: Wait End Entry removed.
      
    } else {
      DateTime departAt;
      DateTime arriveAt;
      
      if (isTimeValid) {
        departAt = normalizedTimes[timeCursorIndex];
        arriveAt = normalizedTimes[timeCursorIndex + 1];
        timeCursorIndex += 2;
      } else {
        departAt = cursorTime;
        cursorTime = cursorTime.add(Duration(minutes: step.minutes ?? 0));
        arriveAt = cursorTime; // Ride duration handling if separate step minutes vs arrival time? 
        // For fallback, assuming step.minutes covers the ride.
      }

      final transportIcon = _emojiForKind(step.kind);

      list.add(
        ScheduleEntry(
          plannedAt: departAt,
          label: '$transportIcon$prefix${step.title} ${step.from ?? ''}に乗る',
          description: '',
          itemKind: ScheduleEntryKind.ride,
          legIndex: legIndex,
          generatedBy: ScheduleEntrySource.route,
          routeStepId: step.stepId,
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
          routeStepId: step.stepId,
          routeRole: 'arrival',
        ),
      );
    }
  }

  if (route.steps.isNotEmpty) {
    // 目的地名を取得 (例: "銀座駅")
    String goalLabel = '目的地';
    if (route.destinationName != null && route.destinationName!.isNotEmpty) {
      goalLabel = route.destinationName!.split(' ').last; 
    }

    DateTime goalTime;
    if (isTimeValid) {
      goalTime = normalizedTimes.isNotEmpty ? normalizedTimes.last : departureBase;
    } else {
      goalTime = cursorTime;
    }

    list.add(
      ScheduleEntry(
        plannedAt: goalTime,
        label: '${prefix}$goalLabel 到着',
        description: 'お疲れ様でした!',
        itemKind: ScheduleEntryKind.goal,
        legIndex: legIndex,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: null,
      ),
    );
  }

  return list;
}

List<ScheduleEntry> createScheduleFromLegs(
  List<Leg> legs, {
  DateTime? userSelectedStartTime,
  DateTime? userSelectedReturnTime,
}) {
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

  // Assign sequential leg indices for sorting
  int currentLegSortIndex = 0;
  final Map<Leg, int> legSortIndices = {};


  if (outbound != null) {
    legSortIndices[outbound] = currentLegSortIndex++; // Outbound = 0
    final startAt = userSelectedStartTime ?? outbound.candidate.departureDate ?? appClock.now();
    
    // Meeting is 10 mins before start
    // If we use shiftToStart: true, the route's relative timeline starts at 0.
    // We want the route start to align with `startAt`.
    
    // The previous logic was: departureAt = firstStepDeparture - departureLeadTime(0)
    // Now we want the first step (User Start) to match `startAt`.
    // And Meeting = startAt - 10 mins.
    
    schedule.addAll(
      createScheduleFromRoute(
        outbound.candidate,
        startDateTime: startAt,
        labelPrefix: '➡️',
        legIndex: legSortIndices[outbound]!,
        includeMeeting: true,
        meetingLabel: '${StringUtils.extractSimpleName(outbound.candidate.originName ?? '')}集合',
        meetingDescription: 'みんな揃っているか確認しましょう',
        meetingAt: startAt.subtract(const Duration(minutes: 10)), // Explicit meeting time
        shiftToStart: false, // Anchor to startAt
      ),
    );
  }

  if (inbound != null) {
    legSortIndices[inbound] = currentLegSortIndex++; // Inbound = 1 typically
    
    // Inbound Anchor Calculation:
    // Ideally calculated from Outbound Arrival + Stay Time, or User Return Time.
    // Using existing candidate departure info as source, but treating it as the anchor.
    // If we had a specific return anchor, we would use it here.
    // Since we don't have explicit "stay time" passed in here, we rely on candidate.departureDate
    // or calculate from outbound arrival if inbound is linked.
    
    DateTime inboundAnchor = userSelectedReturnTime ?? 
                             inbound.candidate.departureDate ?? 
                             appClock.now();

    if (outbound != null && inbound.candidate.departureDate == null && userSelectedReturnTime == null) {
        // Fallback if null
        inboundAnchor = (outbound.candidate.departureDate?.add(Duration(minutes: outbound.candidate.totalTime + 120)) ?? appClock.now());
    }

    // The return time selected by the user is the start of the first inbound
    // movement. Keep the meeting rule consistent with the outbound leg: meet
    // 10 minutes before that movement starts.
    final meetingAt = inboundAnchor.subtract(const Duration(minutes: 10));

    schedule.addAll(
      createScheduleFromRoute(
        inbound.candidate,
        startDateTime: inboundAnchor,
        labelPrefix: '⬅️',
        legIndex: legSortIndices[inbound]!,
        includeMeeting: true,
        meetingLabel: '帰りの集合',
        meetingDescription: '帰りの経路を開始する前に人数を確認しましょう',
        meetingAt: meetingAt,
        shiftToStart: true, // Anchor to inboundAnchor
      ),
    );
  }

  for (final leg in legs) {
    if (leg == outbound || leg == inbound) continue;
    legSortIndices[leg] = currentLegSortIndex++; // Other = 2+
    
    final prefix = _labelForLeg(leg.direction);
    final startDateTime = leg.candidate.departureDate ?? appClock.now();
    schedule.addAll(
      createScheduleFromRoute(
        leg.candidate,
        startDateTime: startDateTime,
        labelPrefix: prefix,
        legIndex: legSortIndices[leg]!,
        shiftToStart: true,
      ),
    );
  }

  sortScheduleEntries(schedule);
  return schedule;
}

String _emojiForKind(String kind) {
  if (kind == 'bus') return '🚌';
  if (kind == 'subway' || kind == 'train') return '🚞';
  if (kind == 'wait') return '⏳';
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

import '../models/group_models.dart';
import '../models/trip_models.dart';
import 'group_schedule_impact.dart';

class GroupScheduleShiftTarget {
  final String entryId;
  final String label;
  final DateTime expectedPlannedAt;
  final DateTime shiftedPlannedAt;

  const GroupScheduleShiftTarget({
    required this.entryId,
    required this.label,
    required this.expectedPlannedAt,
    required this.shiftedPlannedAt,
  });
}

class GroupScheduleShiftPlan {
  final int legIndex;
  final String affectedEntryId;
  final DateTime expectedArrivalAt;
  final Duration shift;
  final List<GroupScheduleShiftTarget> targets;

  const GroupScheduleShiftPlan({
    required this.legIndex,
    required this.affectedEntryId,
    required this.expectedArrivalAt,
    required this.shift,
    required this.targets,
  });

  int get shiftMinutes => shift.inMinutes;
}

/// Builds a group-only adjustment plan for manual schedule entries.
///
/// The plan intentionally never moves route-generated entries. It shifts only
/// manual entries in the affected leg whose planned time is at or after the
/// first conflicting manual entry. Other legs, including a separately planned
/// return route, remain untouched.
class GroupScheduleShiftPlanner {
  const GroupScheduleShiftPlanner._();

  static GroupScheduleShiftPlan build({
    required Trip trip,
    required GroupScheduleImpact impact,
  }) {
    if (trip.tripType != TripType.group) {
      throw StateError('グループ予定の調整はgroup Tripだけです: ${trip.id}');
    }
    if (trip.travelPhase != TravelPhase.active) {
      throw StateError(
        'グループ予定の調整は移動中だけです: phase=${trip.travelPhase.name}',
      );
    }
    if (impact.overrun <= Duration.zero) {
      throw StateError('予定調整量が正ではありません: ${impact.overrun}');
    }

    final affectedMatches = trip.schedule
        .where((entry) => entry.id == impact.affectedEntry.id)
        .toList(growable: false);
    if (affectedMatches.length != 1) {
      throw StateError(
        '調整対象予定をTrip内で一意に特定できません: '
        'id=${impact.affectedEntry.id}, matches=${affectedMatches.length}',
      );
    }
    final affected = affectedMatches.single;
    if (affected.generatedBy != ScheduleEntrySource.manual) {
      throw StateError(
        'グループ予定調整の起点がmanualではありません: id=${affected.id}',
      );
    }
    if (affected.legIndex != impact.arrival.legIndex) {
      throw StateError(
        '到着影響と調整対象予定のlegが一致しません: '
        '${impact.arrival.legIndex} != ${affected.legIndex}',
      );
    }
    if (!affected.plannedAt.isAtSameMomentAs(impact.affectedEntry.plannedAt)) {
      throw StateError(
        '到着影響の算出後に調整対象予定の時刻が変わっています: '
        'id=${affected.id}',
      );
    }

    final shiftMinutes = (impact.overrun.inSeconds + 59) ~/ 60;
    if (shiftMinutes <= 0) {
      throw StateError('分単位の予定調整量が正ではありません: $shiftMinutes');
    }
    final shift = Duration(minutes: shiftMinutes);

    final manualEntries = trip.schedule
        .where(
          (entry) =>
              entry.legIndex == affected.legIndex &&
              entry.generatedBy == ScheduleEntrySource.manual &&
              !entry.plannedAt.isBefore(affected.plannedAt),
        )
        .toList(growable: false)
      ..sort((a, b) {
        final byTime = a.plannedAt.compareTo(b.plannedAt);
        if (byTime != 0) return byTime;
        return a.id.compareTo(b.id);
      });

    if (manualEntries.isEmpty ||
        !manualEntries.any((entry) => entry.id == affected.id)) {
      throw StateError('調整対象のmanual予定が見つかりません: ${affected.id}');
    }

    final targets = manualEntries
        .map(
          (entry) => GroupScheduleShiftTarget(
            entryId: entry.id,
            label: entry.label,
            expectedPlannedAt: entry.plannedAt,
            shiftedPlannedAt: entry.plannedAt.add(shift),
          ),
        )
        .toList(growable: false);

    return GroupScheduleShiftPlan(
      legIndex: affected.legIndex,
      affectedEntryId: affected.id,
      expectedArrivalAt: impact.arrival.expectedArrivalAt,
      shift: shift,
      targets: List.unmodifiable(targets),
    );
  }
}

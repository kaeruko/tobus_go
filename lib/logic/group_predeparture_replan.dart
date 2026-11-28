import '../models/group_models.dart';
import '../models/trip_models.dart';
import 'replan_anchor.dart';
import 'replan_transit_memory.dart';

/// The saved origin is safe only before the active group's first movement.
/// Missing realtime after boarding must never reactivate this path.
class GroupPredepartureReplan {
  const GroupPredepartureReplan._();

  static bool eligible({
    required Trip trip,
    required ScheduleEntry? resolvedEntry,
    required ReplanTransitMemory memory,
    required DateTime now,
  }) {
    if (trip.tripType != TripType.group ||
        trip.travelPhase != TravelPhase.active) return false;
    final legIndex = trip.activeLegIndex;
    if (legIndex < 0 || legIndex >= trip.legs.length) return false;
    final movements = trip.schedule.where((entry) =>
        entry.legIndex == legIndex &&
        (entry.itemKind == ScheduleEntryKind.walk ||
            entry.itemKind == ScheduleEntryKind.ride)).toList();
    if (movements.isEmpty) return false;
    final firstMovementAt = movements.map((e) => e.plannedAt).reduce(
        (a, b) => a.isBefore(b) ? a : b);
    if (!now.isBefore(firstMovementAt)) return false;
    if (memory.ridingTransit != null ||
        memory.knownOnboardStepId != null ||
        memory.completedRideStepId != null) return false;
    if (resolvedEntry != null &&
        (resolvedEntry.legIndex != legIndex ||
         resolvedEntry.routeStepId != null ||
         resolvedEntry.itemKind != ScheduleEntryKind.meeting)) return false;
    return true;
  }

  static ReplanAnchor anchor({required Trip trip, required DateTime now}) {
    final legIndex = trip.activeLegIndex;
    if (trip.tripType != TripType.group ||
        legIndex < 0 || legIndex >= trip.legs.length) {
      throw StateError('集合前の再探索対象legが不正です: tripId=${trip.id}, leg=$legIndex');
    }
    final candidate = trip.legs[legIndex].candidate;
    final name = candidate.originName?.trim();
    final point = candidate.originCoords;
    if (name == null || name.isEmpty || point == null) {
      throw StateError('集合前の出発地点がありません: candidate=${candidate.id}');
    }
    final meetings = trip.schedule.where((entry) =>
        entry.legIndex == legIndex &&
        entry.itemKind == ScheduleEntryKind.meeting).toList();
    if (meetings.length != 1) {
      throw StateError('集合予定を一意に特定できません: leg=$legIndex, count=${meetings.length}');
    }
    final earliestMovement = meetings.single.plannedAt.add(groupMeetingLeadTime);
    final availableAt = now.isAfter(earliestMovement)
        ? now : earliestMovement;
    return ReplanAnchor(
      placeName: name, stopId: null, point: point,
      availableAt: availableAt, source: ReplanAnchorSource.tripOrigin,
    );
  }
}

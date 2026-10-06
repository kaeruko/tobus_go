import '../models/group_models.dart';
import '../models/trip_models.dart';
import 'active_trip_navigation_schedule.dart';
import 'trip_coordinator.dart';

enum GroupLeaderActivePrimaryAction {
  arriveAtGoal,
  completeTrip,
}

bool shouldUseGroupLeaderActiveNavigation(
  Trip trip, {
  required bool forceManagement,
}) {
  if (trip.tripType != TripType.group) {
    throw StateError(
      'Group leader画面の導線判定にGroup以外のtripが渡されました: '
      'tripId=${trip.id}, type=${trip.tripType.name}',
    );
  }

  return trip.travelPhase == TravelPhase.active && !forceManagement;
}

GroupLeaderActivePrimaryAction? resolveGroupLeaderActivePrimaryAction(
  Trip trip, {
  ScheduleEntry? resolvedEntry,
}) {
  if (trip.tripType != TripType.group) {
    throw StateError('Group leader移動中画面にSolo tripが渡されました: tripId=${trip.id}');
  }
  if (trip.travelPhase != TravelPhase.active) {
    throw StateError(
      'Group leader移動中画面にactive以外のtripが渡されました: '
      'tripId=${trip.id}, phase=${trip.travelPhase.name}',
    );
  }
  if (trip.completedLegIndex < -1) {
    throw StateError(
      'completedLegIndexが不正です: '
      'tripId=${trip.id}, completedLegIndex=${trip.completedLegIndex}',
    );
  }

  if (resolvedEntry == null ||
      resolvedEntry.legIndex != trip.activeLegIndex ||
      resolvedEntry.itemKind != ScheduleEntryKind.goal) {
    return null;
  }

  return trip.completedLegIndex >= 0
      ? GroupLeaderActivePrimaryAction.completeTrip
      : GroupLeaderActivePrimaryAction.arriveAtGoal;
}


GroupLeaderActivePrimaryAction? resolveGroupLeaderActivePrimaryActionAt(
  Trip trip, {
  required DateTime now,
}) {
  final resolved = TripCoordinator.resolveScheduleState(
    scheduleEntries: navigationScheduleForTrip(trip),
    now: now,
  ).resolvedEntry;
  return resolveGroupLeaderActivePrimaryAction(
    trip,
    resolvedEntry: resolved,
  );
}

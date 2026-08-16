import '../models/trip_models.dart';

enum GroupLeaderActivePrimaryAction {
  arriveAtGoal,
  completeTrip,
}

GroupLeaderActivePrimaryAction resolveGroupLeaderActivePrimaryAction(Trip trip) {
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

  return trip.completedLegIndex == -1
      ? GroupLeaderActivePrimaryAction.arriveAtGoal
      : GroupLeaderActivePrimaryAction.completeTrip;
}

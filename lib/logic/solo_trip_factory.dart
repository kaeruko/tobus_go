import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';

/// Reject a new trip when its first actual movement minute has passed.
/// Use the same schedule calculation as navigation, including leading waits.
/// The displayed departure minute remains startable until its end.
class SoloRouteExpiredException implements Exception {
  final String candidateId;
  final DateTime movementStart;
  final DateTime now;

  const SoloRouteExpiredException(this.candidateId, this.movementStart, this.now);

  @override
  String toString() =>
      'Route start expired: candidateId=$candidateId, '
      'movementStart=$movementStart, now=$now';
}

void validateSoloRouteStart(Candidate candidate, DateTime now) {
  final departure = candidate.departureDate;
  if (departure == null) {
    throw StateError(
      'Missing route departure date: candidateId=${candidate.id}',
    );
  }
  final schedule = createScheduleFromRoute(
    candidate,
    startDateTime: departure,
    legIndex: 0,
    includeMeeting: false,
  );
  final movementStart = plannedMovementStartForLeg(schedule, legIndex: 0);
  if (!now.isBefore(movementStart.add(const Duration(minutes: 1)))) {
    throw SoloRouteExpiredException(candidate.id, movementStart, now);
  }
}

Trip buildSoloTrip({
  required String id,
  required String userId,
  required String userName,
  required Candidate candidate,
  required DateTime now,
}) {
  final leg = Leg(
    direction: LegDirection.outbound,
    status: LegStatus.confirmed,
    candidate: candidate,
    confirmedAt: now,
  );
  final schedule = createScheduleFromRoute(
    candidate,
    startDateTime: candidate.departureDate ?? now,
    legIndex: 0,
    includeMeeting: false,
  );
  sortScheduleEntries(schedule);

  return Trip(
    tripType: TripType.solo,
    id: id,
    joinCode: '',
    leaderId: userId,
    title: Trip.generateSoloDisplayTitle(candidate),
    travelPhase: TravelPhase.active,
    date: now,
    plannedDepartureAt: null,
    actualDepartureAt: now,
    legs: [leg],
    schedule: schedule,
    participants: [Participant(uid: userId, name: userName, isLeader: true)],
    memberIds: [userId],
  );
}

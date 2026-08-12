import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';

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

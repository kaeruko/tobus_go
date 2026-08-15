import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/route_replan_commit_policy.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  test('group leader can apply a route replan while active', () {
    expect(
      () => RouteReplanCommitPolicy.validate(
        tripType: TripType.group,
        travelPhase: TravelPhase.active,
        leaderId: 'leader-1',
        actorUserId: 'leader-1',
      ),
      returnsNormally,
    );
  });

  test('group member cannot apply a route replan', () {
    expect(
      () => RouteReplanCommitPolicy.validate(
        tripType: TripType.group,
        travelPhase: TravelPhase.active,
        leaderId: 'leader-1',
        actorUserId: 'member-1',
      ),
      throwsStateError,
    );
  });

  test('solo route replan also requires the owner/leader identity', () {
    expect(
      () => RouteReplanCommitPolicy.validate(
        tripType: TripType.solo,
        travelPhase: TravelPhase.active,
        leaderId: 'solo-user',
        actorUserId: 'other-user',
      ),
      throwsStateError,
    );
  });

  test('replan cannot be committed outside active travel', () {
    expect(
      () => RouteReplanCommitPolicy.validate(
        tripType: TripType.group,
        travelPhase: TravelPhase.planning,
        leaderId: 'leader-1',
        actorUserId: 'leader-1',
      ),
      throwsStateError,
    );
  });
}

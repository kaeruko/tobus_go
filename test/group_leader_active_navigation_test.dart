import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/group_leader_active_navigation.dart';
import 'package:toeigo/models/trip_models.dart';

Trip _trip({
  TripType tripType = TripType.group,
  TravelPhase phase = TravelPhase.active,
  int completedLegIndex = -1,
}) {
  return Trip(
    tripType: tripType,
    id: 'trip-1',
    joinCode: '123456',
    leaderId: 'leader-1',
    title: 'test trip',
    travelPhase: phase,
    date: DateTime(2026, 8, 16),
    plannedDepartureAt: DateTime(2026, 8, 16, 9),
    actualDepartureAt: DateTime(2026, 8, 16, 9),
    legs: const [],
    schedule: const [],
    participants: const [],
    memberIds: const [],
    completedLegIndex: completedLegIndex,
  );
}

void main() {
  test('往路中は目的地到着を主操作にする', () {
    expect(
      resolveGroupLeaderActivePrimaryAction(_trip()),
      GroupLeaderActivePrimaryAction.arriveAtGoal,
    );
  });

  test('往路完了後はおでかけ終了を主操作にする', () {
    expect(
      resolveGroupLeaderActivePrimaryAction(_trip(completedLegIndex: 0)),
      GroupLeaderActivePrimaryAction.completeTrip,
    );
  });

  test('Solo tripはGroup leader移動中画面へ入れない', () {
    expect(
      () => resolveGroupLeaderActivePrimaryAction(
        _trip(tripType: TripType.solo),
      ),
      throwsStateError,
    );
  });

  test('active以外はGroup leader移動中画面へ入れない', () {
    expect(
      () => resolveGroupLeaderActivePrimaryAction(
        _trip(phase: TravelPhase.planning),
      ),
      throwsStateError,
    );
  });

  test('不正なcompletedLegIndexはfail-fastする', () {
    expect(
      () => resolveGroupLeaderActivePrimaryAction(
        _trip(completedLegIndex: -2),
      ),
      throwsStateError,
    );
  });
}

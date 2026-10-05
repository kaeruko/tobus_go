import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/group_leader_active_navigation.dart';
import 'package:toeigo/models/group_models.dart';
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
  test('active groupは共通のleader移動中ナビを使う', () {
    expect(
      shouldUseGroupLeaderActiveNavigation(
        _trip(),
        forceManagement: false,
      ),
      isTrue,
    );
  });

  test('active groupでも管理画面を明示した場合は管理画面に残る', () {
    expect(
      shouldUseGroupLeaderActiveNavigation(
        _trip(),
        forceManagement: true,
      ),
      isFalse,
    );
  });

  test('planning groupは管理画面を使う', () {
    expect(
      shouldUseGroupLeaderActiveNavigation(
        _trip(phase: TravelPhase.planning),
        forceManagement: false,
      ),
      isFalse,
    );
  });

  test('導線判定にSolo tripを渡すとfail-fastする', () {
    expect(
      () => shouldUseGroupLeaderActiveNavigation(
        _trip(tripType: TripType.solo),
        forceManagement: false,
      ),
      throwsStateError,
    );
  });

  test('往路中でもナビが目的地到着前なら主操作を表示しない', () {
    final ride = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 16, 9, 30),
      label: '乗車中',
      itemKind: ScheduleEntryKind.ride,
      legIndex: 0,
    );

    expect(
      resolveGroupLeaderActivePrimaryAction(_trip(), resolvedEntry: ride),
      isNull,
    );
  });

  test('ナビが往路の目的地到着になったら到着操作を表示する', () {
    final goal = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 16, 10),
      label: '目的地 到着',
      itemKind: ScheduleEntryKind.goal,
      legIndex: 0,
    );

    expect(
      resolveGroupLeaderActivePrimaryAction(_trip(), resolvedEntry: goal),
      GroupLeaderActivePrimaryAction.arriveAtGoal,
    );
  });

  test('別legのgoalでは到着操作を表示しない', () {
    final returnGoal = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 16, 11),
      label: '帰着',
      itemKind: ScheduleEntryKind.goal,
      legIndex: 1,
    );

    expect(
      resolveGroupLeaderActivePrimaryAction(
        _trip(),
        resolvedEntry: returnGoal,
      ),
      isNull,
    );
  });

  test('復路中でもナビが帰着前ならおでかけ終了を表示しない', () {
    final ride = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 16, 11),
      label: '帰路 乗車中',
      itemKind: ScheduleEntryKind.ride,
      legIndex: 1,
    );

    expect(
      resolveGroupLeaderActivePrimaryAction(
        _trip(completedLegIndex: 0),
        resolvedEntry: ride,
      ),
      isNull,
    );
  });

  test('復路がゴールになったらおでかけ終了を主操作にする', () {
    final goal = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 16, 12),
      label: '帰着',
      description: 'お疲れ様でした!',
      itemKind: ScheduleEntryKind.goal,
      legIndex: 1,
    );

    expect(
      resolveGroupLeaderActivePrimaryAction(
        _trip(completedLegIndex: 0),
        resolvedEntry: goal,
      ),
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

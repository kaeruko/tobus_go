import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  test('return meeting is ten minutes before the selected departure', () {
    final selectedReturnTime = DateTime(2026, 8, 11, 13, 49);
    final inbound = Candidate(
      id: 'inbound',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 2,
      totalTime: 2,
      points: const [],
      originName: '東墨田店',
      destinationName: '自宅',
      departureDate: selectedReturnTime,
      steps: [
        StepSeg(
          stepId: 'walk-home',
          kind: 'walk',
          title: '徒歩',
          fromName: '東墨田店',
          toName: '自宅',
          minutes: 2,
          departureTime: '13:49',
          arrivalTime: '13:51',
        ),
      ],
    );

    final schedule = createScheduleFromLegs([
      Leg(
        direction: LegDirection.inbound,
        status: LegStatus.confirmed,
        candidate: inbound,
      ),
    ]);
    final meeting = schedule.singleWhere(
      (entry) => entry.itemKind == ScheduleEntryKind.meeting,
    );
    final firstMovement = schedule.singleWhere(
      (entry) => entry.itemKind == ScheduleEntryKind.walk,
    );

    expect(meeting.label, contains('帰りの集合'));
    expect(meeting.plannedAt, DateTime(2026, 8, 11, 13, 39));
    expect(firstMovement.plannedAt, selectedReturnTime);
    expect(
      firstMovement.plannedAt.difference(meeting.plannedAt),
      const Duration(minutes: 10),
    );
  });

  test('rejects return time when return meeting would precede outbound arrival', () {
    final outbound = Candidate(
      id: 'outbound',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 9,
      totalTime: 9,
      points: const [],
      originName: '本所吾妻橋駅',
      destinationName: '新橋駅',
      departureDate: DateTime(2026, 10, 1, 20, 0),
      steps: [
        StepSeg(
          stepId: 'outbound-walk',
          kind: 'walk',
          title: '徒歩',
          fromName: '本所吾妻橋駅',
          toName: '新橋駅',
          minutes: 9,
          departureTime: '20:00',
          arrivalTime: '20:09',
        ),
      ],
    );
    final inbound = Candidate(
      id: 'inbound',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 4,
      totalTime: 4,
      points: const [],
      originName: '新橋駅',
      destinationName: '本所吾妻橋駅',
      departureDate: DateTime(2026, 10, 1, 20, 11),
      steps: [
        StepSeg(
          stepId: 'inbound-walk',
          kind: 'walk',
          title: '徒歩',
          fromName: '新橋駅',
          toName: '本所吾妻橋駅',
          minutes: 4,
          departureTime: '20:11',
          arrivalTime: '20:15',
        ),
      ],
    );

    expect(
      () => createScheduleFromLegs(
        [
          Leg(
            direction: LegDirection.outbound,
            status: LegStatus.confirmed,
            candidate: outbound,
          ),
          Leg(
            direction: LegDirection.inbound,
            status: LegStatus.confirmed,
            candidate: inbound,
          ),
        ],
        userSelectedStartTime: DateTime(2026, 10, 1, 20, 0),
        userSelectedReturnTime: DateTime(2026, 10, 1, 20, 11),
      ),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('帰りの時刻が早すぎます'),
        ),
      ),
    );
  });

  test('allows return meeting exactly at outbound arrival', () {
    final outbound = Candidate(
      id: 'outbound',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 9,
      totalTime: 9,
      points: const [],
      originName: '本所吾妻橋駅',
      destinationName: '新橋駅',
      departureDate: DateTime(2026, 10, 1, 20, 0),
      steps: [
        StepSeg(
          stepId: 'outbound-walk',
          kind: 'walk',
          title: '徒歩',
          fromName: '本所吾妻橋駅',
          toName: '新橋駅',
          minutes: 9,
          departureTime: '20:00',
          arrivalTime: '20:09',
        ),
      ],
    );
    final inbound = Candidate(
      id: 'inbound',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 4,
      totalTime: 4,
      points: const [],
      originName: '新橋駅',
      destinationName: '本所吾妻橋駅',
      departureDate: DateTime(2026, 10, 1, 20, 19),
      steps: [
        StepSeg(
          stepId: 'inbound-walk',
          kind: 'walk',
          title: '徒歩',
          fromName: '新橋駅',
          toName: '本所吾妻橋駅',
          minutes: 4,
          departureTime: '20:19',
          arrivalTime: '20:23',
        ),
      ],
    );

    final schedule = createScheduleFromLegs(
      [
        Leg(
          direction: LegDirection.outbound,
          status: LegStatus.confirmed,
          candidate: outbound,
        ),
        Leg(
          direction: LegDirection.inbound,
          status: LegStatus.confirmed,
          candidate: inbound,
        ),
      ],
      userSelectedStartTime: DateTime(2026, 10, 1, 20, 0),
      userSelectedReturnTime: DateTime(2026, 10, 1, 20, 19),
    );

    final outboundGoal = schedule.singleWhere(
      (entry) =>
          entry.legIndex == 0 && entry.itemKind == ScheduleEntryKind.goal,
    );
    final inboundMeeting = schedule.singleWhere(
      (entry) =>
          entry.legIndex == 1 && entry.itemKind == ScheduleEntryKind.meeting,
    );

    expect(outboundGoal.plannedAt, DateTime(2026, 10, 1, 20, 9));
    expect(inboundMeeting.plannedAt, outboundGoal.plannedAt);
  });
}

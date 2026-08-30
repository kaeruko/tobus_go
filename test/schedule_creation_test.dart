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
}

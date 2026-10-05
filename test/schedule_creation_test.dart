import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  test('final walk without clocks advances goal by its duration', () {
    final route = Candidate(
      id: 'final-walk-no-clocks',
      lines: const ['都01'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 39,
      totalTime: 39,
      points: const [],
      originName: '新橋',
      destinationName: '渋谷駅',
      departureDate: DateTime(2026, 10, 3, 12, 35),
      arrivalTime: '13:14',
      steps: [
        StepSeg(
          stepId: 'walk-origin',
          kind: 'walk',
          title: '徒歩',
          fromName: '新橋',
          toName: '新橋駅前',
          minutes: 2,
        ),
        StepSeg(
          stepId: 'bus-to01',
          kind: 'bus',
          title: '都01',
          fromName: '新橋駅前',
          toName: '渋谷三丁目',
          minutes: 29,
          departureTime: '12:37',
          arrivalTime: '13:06',
        ),
        StepSeg(
          stepId: 'walk-destination',
          kind: 'walk',
          title: '徒歩',
          fromName: '渋谷三丁目',
          toName: '渋谷駅',
          minutes: 8,
        ),
      ],
    );

    final schedule = createScheduleFromRoute(
      route,
      startDateTime: route.departureDate,
    );

    final busArrival = schedule.singleWhere(
      (entry) =>
          entry.routeStepId == 'bus-to01' &&
          entry.itemKind == ScheduleEntryKind.arrival,
    );
    final finalWalk = schedule.singleWhere(
      (entry) => entry.routeStepId == 'walk-destination',
    );
    final goal = schedule.singleWhere(
      (entry) => entry.itemKind == ScheduleEntryKind.goal,
    );

    expect(busArrival.plannedAt, DateTime(2026, 10, 3, 13, 6));
    expect(finalWalk.plannedAt, DateTime(2026, 10, 3, 13, 6));
    expect(goal.plannedAt, DateTime(2026, 10, 3, 13, 14));
  });

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

  test('group return search defaults to one hour after outbound arrival', () {
    final outbound = Candidate(
      id: 'outbound-window',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 47,
      totalTime: 47,
      points: const [],
      departureDate: DateTime(2026, 10, 2, 10, 24),
      steps: const [],
    );

    final window = buildGroupReturnSearchWindow(outbound);

    expect(window.outboundArrivalAt, DateTime(2026, 10, 2, 11, 11));
    expect(
      window.minimumReturnDepartureAt,
      DateTime(2026, 10, 2, 11, 21),
    );
    expect(
      window.defaultReturnDepartureAt,
      DateTime(2026, 10, 2, 12, 11),
    );
  });

  test('planned movement start ignores the group meeting entry', () {
    final schedule = [
      ScheduleEntry(
        id: 'meeting-start',
        plannedAt: DateTime(2026, 10, 2, 10, 14),
        label: '本所吾妻橋駅集合',
        itemKind: ScheduleEntryKind.meeting,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
      ),
      ScheduleEntry(
        id: 'walk-start',
        plannedAt: DateTime(2026, 10, 2, 10, 24),
        label: '本所吾妻橋まで歩く',
        itemKind: ScheduleEntryKind.walk,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
      ),
    ];

    expect(
      plannedMovementStartForLeg(schedule, legIndex: 0),
      DateTime(2026, 10, 2, 10, 24),
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


  test('group return keeps fixed transit clocks from the selected route', () {
    final inbound = Candidate.fromJson({
      'id': 'incident-return',
      'lines': ['都01'],
      'rides': 1,
      'walking_distance_meters': 116,
      'walking_segment_count': 1,
      'boards': 1,
      'transfers': 0,
      'total': 47,
      'total_time': 47,
      'origin_name': '渋谷駅',
      'destination_name': '十間橋',
      'departure_date': '2026-10-05T20:06:00',
      'points': <dynamic>[],
      'steps': [
        {
          'step_id': 'walk-origin',
          'kind': 'walk',
          'title': '徒歩',
          'from_': '渋谷駅',
          'to': '渋谷駅前',
          'minutes': 3,
          'meters': 116,
        },
        {
          'step_id': 'wait-origin',
          'kind': 'wait',
          'title': '待ち時間',
          'from_': '渋谷駅前',
          'to': '渋谷駅前',
          'minutes': 11,
          'departure_time': '20:06',
          'arrival_time': '20:18',
        },
        {
          'step_id': 'bus-incident',
          'kind': 'bus',
          'title': '都01',
          'from_': '渋谷駅前',
          'to': '新橋駅前',
          'minutes': 32,
          'departure_time': '20:18',
          'arrival_time': '20:50',
          'route_id': '006',
          'trip_id': '08501-1-09-170-2018',
          'departureStopId': '0636-06',
          'arrivalPoleId': '0737-04',
        },
      ],
    });

    final schedule = createScheduleFromLegs([
      Leg(
        direction: LegDirection.inbound,
        status: LegStatus.confirmed,
        candidate: inbound,
      ),
    ]);

    final wait = schedule.singleWhere(
      (entry) => entry.routeStepId == 'wait-origin',
    );
    final walk = schedule.singleWhere(
      (entry) => entry.routeStepId == 'walk-origin',
    );
    final ride = schedule.singleWhere(
      (entry) =>
          entry.routeStepId == 'bus-incident' &&
          entry.itemKind == ScheduleEntryKind.ride,
    );
    final arrival = schedule.singleWhere(
      (entry) =>
          entry.routeStepId == 'bus-incident' &&
          entry.itemKind == ScheduleEntryKind.arrival,
    );

    expect(wait.plannedAt, DateTime(2026, 10, 5, 20, 3));
    expect(walk.plannedAt, DateTime(2026, 10, 5, 20, 15));
    expect(ride.plannedAt, DateTime(2026, 10, 5, 20, 18));
    expect(arrival.plannedAt, DateTime(2026, 10, 5, 20, 50));
  });

  test('shiftToStart fails fast instead of moving fixed transit clocks', () {
    final route = Candidate(
      id: 'fixed-transit',
      lines: const ['都01'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 32,
      totalTime: 32,
      points: const [],
      departureDate: DateTime(2026, 10, 5, 20, 21),
      steps: [
        StepSeg(
          stepId: 'bus-fixed',
          kind: 'bus',
          title: '都01',
          fromName: '渋谷駅前',
          toName: '新橋駅前',
          minutes: 32,
          departureTime: '20:18',
          arrivalTime: '20:50',
        ),
      ],
    );

    expect(
      () => createScheduleFromRoute(
        route,
        startDateTime: route.departureDate,
        shiftToStart: true,
      ),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('固定交通時刻をshiftToStartで移動できません'),
        ),
      ),
    );
  });

  test('walking-only return time update shifts the movement to the selected time', () {
    final inbound = Candidate(
      id: 'walking-return',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 2,
      totalTime: 2,
      points: const [],
      originName: '東墨田店',
      destinationName: '自宅',
      departureDate: DateTime(2026, 10, 5, 13, 49),
      steps: [
        StepSeg(
          stepId: 'walk-home-retime',
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

    final selected = DateTime(2026, 10, 5, 14, 10);
    final schedule = createScheduleFromLegs(
      [
        Leg(
          direction: LegDirection.inbound,
          status: LegStatus.confirmed,
          candidate: inbound,
        ),
      ],
      userSelectedReturnTime: selected,
    );

    final meeting = schedule.singleWhere(
      (entry) => entry.itemKind == ScheduleEntryKind.meeting,
    );
    final walk = schedule.singleWhere(
      (entry) => entry.itemKind == ScheduleEntryKind.walk,
    );
    final goal = schedule.singleWhere(
      (entry) => entry.itemKind == ScheduleEntryKind.goal,
    );

    expect(meeting.plannedAt, DateTime(2026, 10, 5, 14, 0));
    expect(walk.plannedAt, selected);
    expect(goal.plannedAt, DateTime(2026, 10, 5, 14, 12));
  });

  test('return time update rejects reusing a fixed transit route', () {
    final inbound = Candidate(
      id: 'fixed-return',
      lines: const ['都01'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 32,
      totalTime: 32,
      points: const [],
      steps: [
        StepSeg(
          stepId: 'bus-fixed-return',
          kind: 'bus',
          title: '都01',
          fromName: '渋谷駅前',
          toName: '新橋駅前',
          minutes: 32,
          departureTime: '20:18',
          arrivalTime: '20:50',
          routeId: '006',
          tripId: '08501-1-09-170-2018',
        ),
      ],
    );

    expect(
      () => validateReturnTimeUpdateCanReuseExistingRoute([
        Leg(
          direction: LegDirection.inbound,
          status: LegStatus.confirmed,
          candidate: inbound,
        ),
      ]),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('経路の再検索が必要です'),
        ),
      ),
    );
  });

  test('return time update merge preserves manual schedule entries', () {
    final manual = ScheduleEntry(
      id: 'manual-onsite',
      plannedAt: DateTime(2026, 10, 5, 18, 0),
      label: '見学',
      generatedBy: ScheduleEntrySource.manual,
    );
    final oldRoute = ScheduleEntry(
      id: 'old-route',
      plannedAt: DateTime(2026, 10, 5, 17, 0),
      label: '古い経路',
      generatedBy: ScheduleEntrySource.route,
    );
    final newRoute = ScheduleEntry(
      id: 'new-route',
      plannedAt: DateTime(2026, 10, 5, 19, 0),
      label: '新しい経路',
      generatedBy: ScheduleEntrySource.route,
    );

    final merged = mergeRegeneratedRouteSchedulePreservingManualEntries(
      [oldRoute, manual],
      [newRoute],
    );

    expect(merged.map((entry) => entry.id).toSet(), {
      'manual-onsite',
      'new-route',
    });
    expect(
      merged.singleWhere((entry) => entry.id == 'manual-onsite'),
      same(manual),
    );
    expect(merged.any((entry) => entry.id == 'old-route'), isFalse);
  });

}

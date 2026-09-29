import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/trip_display_localizations.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  final candidate = Candidate(
    id: 'english-active-trip',
    lines: const ['浅草線', '大江戸線'],
    linesEn: const ['Asakusa Line', 'Oedo Line'],
    rides: 2,
    boards: 2,
    transfers: 1,
    total: 24,
    totalTime: 24,
    points: const [],
    originName: '押上',
    destinationName: '上野駅',
    originNameEn: 'Oshiage',
    destinationNameEn: 'Ueno Station',
    steps: [
      StepSeg(
        stepId: 'walk-1',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '押上',
        toName: '押上',
        toNameEn: 'Oshiage',
        minutes: 5,
      ),
      StepSeg(
        stepId: 'rail-1',
        kind: 'rail',
        title: '浅草線',
        titleEn: 'Asakusa Line',
        fromName: '押上',
        fromNameEn: 'Oshiage',
        toName: '蔵前',
        toNameEn: 'Kuramae',
        minutes: 5,
      ),
      StepSeg(
        stepId: 'rail-2',
        kind: 'rail',
        title: '大江戸線',
        titleEn: 'Oedo Line',
        fromName: '蔵前',
        fromNameEn: 'Kuramae',
        toName: '上野御徒町',
        toNameEn: 'Ueno-okachimachi',
        minutes: 3,
      ),
      StepSeg(
        stepId: 'walk-2',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '上野御徒町',
        fromNameEn: 'Ueno-okachimachi',
        toName: '上野駅',
        minutes: 6,
      ),
    ],
  );

  final entries = [
    ScheduleEntry(
      id: 'walk',
      plannedAt: DateTime(2026, 9, 27, 22, 3),
      label: '押上まで歩く (5分)',
      itemKind: ScheduleEntryKind.walk,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'walk-1',
      routeRole: 'walk',
    ),
    ScheduleEntry(
      id: 'rail-1-board',
      plannedAt: DateTime(2026, 9, 27, 22, 8),
      label: '🚇浅草線 押上に乗る',
      itemKind: ScheduleEntryKind.ride,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'rail-1',
      routeRole: 'ride',
    ),
    ScheduleEntry(
      id: 'rail-1-arrive',
      plannedAt: DateTime(2026, 9, 27, 22, 13),
      label: '🚇浅草線 蔵前に着く',
      itemKind: ScheduleEntryKind.arrival,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'rail-1',
      routeRole: 'arrival',
    ),
    ScheduleEntry(
      id: 'rail-2-board',
      plannedAt: DateTime(2026, 9, 27, 22, 25),
      label: '🚇大江戸線 蔵前に乗る',
      itemKind: ScheduleEntryKind.ride,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'rail-2',
      routeRole: 'ride',
    ),
  ];

  final trip = Trip(
    tripType: TripType.solo,
    id: 'solo-en',
    joinCode: '',
    leaderId: 'user',
    title: '',
    travelPhase: TravelPhase.active,
    date: DateTime(2026, 9, 27),
    plannedDepartureAt: DateTime(2026, 9, 27, 22, 3),
    actualDepartureAt: null,
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: candidate,
      ),
    ],
    schedule: entries,
    participants: const [],
    memberIds: const ['user'],
  );

  test('English solo trip title uses bilingual route endpoints', () {
    expect(
      localizedSoloTripTitle(const Locale('en'), trip),
      'Oshiage (押上) → Ueno Station (上野駅)',
    );
  });

  test('English active-route rows are rebuilt from structured route data', () {
    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[0],
      ),
      'Walk to Oshiage (押上) (5 min)',
    );
    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[1],
      ),
      'Asakusa Line · Board at Oshiage (押上)',
    );
    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[2],
      ),
      'Asakusa Line · Arrive at Kuramae (蔵前)',
    );
    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[3],
      ),
      'Oedo Line · Board at Kuramae (蔵前)',
    );
  });

  test('English active-route compact labels avoid sentence-style rows', () {
    expect(
      localizedSoloScheduleEntryCompactLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[0],
      ),
      'Oshiage\n押上\n5 min',
    );
    expect(
      localizedSoloScheduleEntryCompactLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[1],
      ),
      'Asakusa Line\nOshiage\n押上',
    );
    expect(
      localizedSoloScheduleEntryCompactLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[2],
      ),
      'Kuramae\n蔵前',
    );
    expect(
      localizedSoloScheduleEntryCompactLabel(
        const Locale('en'),
        trip: trip,
        entry: entries[3],
      ),
      'Oedo Line\nKuramae\n蔵前',
    );
  });

  test('English goal label uses persisted bilingual destination', () {
    final goal = ScheduleEntry(
      id: 'goal',
      plannedAt: DateTime(2026, 9, 27, 22, 34),
      label: '上野駅 到着',
      description: 'お疲れ様でした!',
      itemKind: ScheduleEntryKind.goal,
      legIndex: 0,
      generatedBy: ScheduleEntrySource.route,
    );

    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('en'),
        trip: trip,
        entry: goal,
      ),
      'Arrive at Ueno Station (上野駅)',
    );
  });

  test('Japanese active-route rows preserve stored labels', () {
    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('ja'),
        trip: trip,
        entry: entries[1],
      ),
      '🚇浅草線 押上に乗る',
    );
  });

  test('Chinese trip titles use the same bilingual endpoints as English', () {
    expect(
      localizedSoloTripTitle(const Locale('zh'), trip),
      'Oshiage (押上) → Ueno Station (上野駅)',
    );
  });

  test('Chinese schedule instructions retain the official transit names', () {
    const expected = [
      '步行至 Oshiage (押上) (5分钟)',
      'Asakusa Line · 在 Oshiage (押上) 上车',
      'Asakusa Line · 到达 Kuramae (蔵前)',
      'Oedo Line · 在 Kuramae (蔵前) 上车',
    ];
    for (var i = 0; i < entries.length; i++) {
      expect(
        localizedSoloScheduleEntryLabel(
          const Locale('zh'),
          trip: trip,
          entry: entries[i],
        ),
        expected[i],
      );
    }
    expect(
      localizedSoloScheduleEntryCompactLabel(
        const Locale('zh'),
        trip: trip,
        entry: entries[0],
      ),
      'Oshiage\n押上\n5分钟',
    );
    expect(
      localizedSoloScheduleEntryCompactLabel(
        const Locale('zh'),
        trip: trip,
        entry: entries[1],
      ),
      'Asakusa Line\nOshiage\n押上',
    );
  });

  test('Chinese goal rows use bilingual destinations', () {
    final goal = ScheduleEntry(
      id: 'goal-zh',
      plannedAt: DateTime(2026, 9, 27, 22, 34),
      label: '上野駅 到着',
      itemKind: ScheduleEntryKind.goal,
      generatedBy: ScheduleEntrySource.route,
    );

    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('zh'),
        trip: trip,
        entry: goal,
      ),
      '到达 Ueno Station (上野駅)',
    );
  });

  test('Chinese user-authored schedule labels remain untouched', () {
    final custom = ScheduleEntry(
      id: 'custom',
      plannedAt: DateTime(2026, 9, 27, 22, 34),
      label: 'カフェで休憩',
      itemKind: ScheduleEntryKind.goal,
    );

    expect(
      localizedSoloScheduleEntryLabel(
        const Locale('zh'),
        trip: trip,
        entry: custom,
      ),
      'カフェで休憩',
    );
  });
}

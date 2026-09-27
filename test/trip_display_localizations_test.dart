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
}

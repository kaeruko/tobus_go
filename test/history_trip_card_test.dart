import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/widgets/history_trip_card.dart';

void main() {
  final candidate = Candidate(
    id: 'history-route',
    lines: const ['浅草線', '大江戸線'],
    linesEn: const ['Asakusa Line', 'Oedo Line'],
    rides: 2,
    boards: 2,
    transfers: 1,
    total: 24,
    totalTime: 24,
    points: const [],
    originName: '押上',
    originNameEn: 'Oshiage',
    destinationName: '上野駅',
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

  final trip = Trip(
    tripType: TripType.solo,
    id: 'history-trip',
    joinCode: '',
    leaderId: 'user',
    title: '',
    travelPhase: TravelPhase.completed,
    date: DateTime(2026, 9, 27),
    plannedDepartureAt: DateTime(2026, 9, 27, 21, 30),
    actualDepartureAt: DateTime(2026, 9, 27, 21, 30),
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: candidate,
      ),
    ],
    schedule: [
      ScheduleEntry(
        id: 'walk',
        plannedAt: DateTime(2026, 9, 27, 21, 30),
        label: '押上まで歩く (5分)',
        itemKind: ScheduleEntryKind.walk,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'walk-1',
        routeRole: 'walk',
      ),
      ScheduleEntry(
        id: 'goal',
        plannedAt: DateTime(2026, 9, 27, 21, 54),
        label: '上野駅 到着',
        itemKind: ScheduleEntryKind.goal,
        generatedBy: ScheduleEntrySource.route,
      ),
    ],
    participants: const [],
    memberIds: const ['user'],
  );

  Future<void> pumpCard(WidgetTester tester, Locale locale) async {
    await tester.pumpWidget(
      MaterialApp(
        locale: locale,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: HistoryTripCard(
            trip: trip,
            onTap: () {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('English history card shows route summary details', (tester) async {
    await pumpCard(tester, const Locale('en'));

    expect(
      find.text('Oshiage (押上) → Ueno Station (上野駅)'),
      findsOneWidget,
    );
    expect(
      find.text('2026/9/27 · 21:30 → 21:54 · 24 min'),
      findsOneWidget,
    );
    expect(find.text('Asakusa Line → Oedo Line'), findsOneWidget);
    expect(find.text('Transfers: 1 · Walk 11 min'), findsOneWidget);
  });

  testWidgets('Japanese history card uses the same richer layout', (tester) async {
    await pumpCard(tester, const Locale('ja'));

    expect(find.text('押上 → 上野駅'), findsOneWidget);
    expect(
      find.text('2026/9/27 · 21:30 → 21:54 · 24分'),
      findsOneWidget,
    );
    expect(find.text('浅草線 → 大江戸線'), findsOneWidget);
    expect(find.text('乗換 1回 · 徒歩 11分'), findsOneWidget);
  });
}

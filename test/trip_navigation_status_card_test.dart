import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/trip_navigation_status_card.dart';

void main() {
  testWidgets('bus and rail remaining counts use transport-specific wording', (
    tester,
  ) async {
    Future<void> pumpCard({
      required String kind,
      required int remainingStops,
    }) async {
      final step = StepSeg(
        stepId: 'ride-step',
        kind: kind,
        title: kind == 'bus' ? '上23' : '浅草線',
        fromName: '乗車地点',
        toName: '降車地点',
      );
      final navigation = NavigationState(
        mainText: '移動中',
        subText: '降車地点で降ります',
        color: Colors.blue,
        statusLabel: '乗車中',
        remainingStops: remainingStops,
        nextStopName: '次の駅',
        step: step,
      );

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: TripNavigationStatusCard(
              navState: navigation,
              tripTitle: '出発地 → 目的地',
              onTapStops: () {},
            ),
          ),
        ),
      );
    }

    await pumpCard(kind: 'bus', remainingStops: 2);
    expect(find.text('のこり 2 回停車'), findsOneWidget);
    expect(find.text('次: 次の駅'), findsOneWidget);

    await pumpCard(kind: 'rail', remainingStops: 3);
    expect(find.text('のこり 3 駅'), findsOneWidget);
    expect(find.text('のこり 2 回停車'), findsNothing);
  });
  testWidgets('English stop labels are localized', (tester) async {
    final step = StepSeg(
      stepId: 'bus-en',
      kind: 'bus',
      title: 'Route 8',
      fromName: 'Origin',
      toName: 'Destination',
    );
    final navigation = NavigationState(
      mainText: 'Moving',
      subText: 'Stay on board',
      color: Colors.blue,
      statusLabel: 'Riding',
      remainingStops: 2,
      nextStopName: '次の停留所',
      nextStopNameEn: 'Next Stop',
      step: step,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Origin → Destination',
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(find.text('2 stops remaining'), findsOneWidget);
    expect(find.text('Next: Next Stop (次の停留所)'), findsOneWidget);
  });

  testWidgets('semantic navigation messages render in English', (tester) async {
    final navigation = NavigationState.waitingForDeparture(
      plannedAt: DateTime(2026, 9, 27, 8, 29),
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Tokyo Station → Asakusa',
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(find.text('Before departure'), findsOneWidget);
    expect(find.text('Departs at 8:29'), findsOneWidget);
    expect(find.text('Not started'), findsOneWidget);
  });

  testWidgets('semantic ride entity names use official English values', (
    tester,
  ) async {
    final step = StepSeg(
      stepId: 'rail-en',
      kind: 'rail',
      title: '浅草線',
      titleEn: 'Asakusa Line',
      fromName: '東日本橋',
      fromNameEn: 'Higashi-nihombashi',
      toName: '蔵前',
      toNameEn: 'Kuramae',
      arrivalTime: '10:24',
    );
    final navigation = NavigationState(
      mainText: '浅草線 青砥行 東日本橋',
      subText: '10:24 浅草線 青砥行 蔵前到着予定',
      color: Colors.blue,
      statusLabel: '🚇乗車中',
      mainTextToken: const NavigationTextToken(
        NavigationTextKey.rideCurrentPlaceMain,
        {
          'rideTitle': '浅草線 青砥行',
          'rideTitleEn': 'Asakusa Line · Aoto',
          'placeName': '東日本橋',
          'placeNameEn': 'Higashi-nihombashi',
        },
      ),
      subTextToken: const NavigationTextToken(
        NavigationTextKey.rideArrivalSummary,
        {
          'arrivalTime': '10:24',
          'rideTitle': '浅草線 青砥行',
          'rideTitleEn': 'Asakusa Line · Aoto',
          'destination': '蔵前',
          'destinationEn': 'Kuramae',
        },
      ),
      statusLabelToken: const NavigationTextToken(
        NavigationTextKey.railRideStatus,
      ),
      remainingStops: 2,
      nextStopName: '浅草橋',
      nextStopNameEn: 'Asakusabashi',
      step: step,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: TripNavigationStatusCard(
            navState: navigation,
            tripTitle: 'Higashi-nihombashi → Kuramae',
            onTapStops: () {},
          ),
        ),
      ),
    );

    expect(
      find.text('Asakusa Line · Aoto · Higashi-nihombashi (東日本橋)'),
      findsOneWidget,
    );
    expect(
      find.text('10:24 Asakusa Line · Aoto · Arrive at Kuramae (蔵前)'),
      findsOneWidget,
    );
    expect(find.text('Next: Asakusabashi (浅草橋)'), findsOneWidget);
    expect(find.textContaining('東日本橋'), findsWidgets);
  });

}

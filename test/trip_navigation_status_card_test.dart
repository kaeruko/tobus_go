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
      nextStopName: 'Next Stop',
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
    expect(find.text('Next: Next Stop'), findsOneWidget);
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

}

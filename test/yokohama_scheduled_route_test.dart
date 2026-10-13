import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/active_route_content.dart';

Candidate candidateWithDeparture(String? departureTime) => Candidate(
  id: 'fixture-yokohama',
  lines: const ['8'],
  rides: 1,
  boards: 1,
  transfers: 0,
  total: 20,
  totalTime: 20,
  departureDate: DateTime(2026, 10, 14, 9, 55),
  steps: [
    StepSeg(
      stepId: 'ride1',
      kind: 'bus',
      title: '8系統',
      toName: '桜木町駅前',
      departureTime: departureTime,
    ),
  ],
  points: const [],
);

Future<void> pumpCard(WidgetTester tester, Candidate candidate, DateTime now) async {
  await tester.pumpWidget(CupertinoApp(
    locale: const Locale('ja'),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: CupertinoPageScaffold(
      child: ScheduledRideCard(candidate: candidate, now: now),
    ),
  ));
}

void main() {
  testWidgets('Yokohama scheduled card shows remaining minutes without realtime', (tester) async {
    await pumpCard(tester, candidateWithDeparture('10:00'), DateTime(2026, 10, 14, 9, 55));
    expect(find.text('10:00 発予定'), findsOneWidget);
    expect(find.text('発車まであと 5 分'), findsOneWidget);
    expect(find.textContaining('遅延・運休は反映されません'), findsOneWidget);
  });

  testWidgets('a scheduled trip remains selected after scheduled departure', (tester) async {
    await pumpCard(tester, candidateWithDeparture('10:00'), DateTime(2026, 10, 14, 10, 1));
    expect(find.text('10:00 発予定'), findsOneWidget);
    expect(find.textContaining('予定発車時刻を過ぎました'), findsOneWidget);
  });

  test('24-hour-plus GTFS times retain the service date rollover', () {
    final candidate = candidateWithDeparture('24:10');
    final departure = scheduledRideDepartureAt(candidate, candidate.steps.single);
    expect(departure, DateTime(2026, 10, 15, 0, 10));
  });

  test('malformed planned times fail instead of silently shifting a trip', () {
    final candidate = candidateWithDeparture('bad-clock');
    expect(
      () => scheduledRideDepartureAt(candidate, candidate.steps.single),
      throwsFormatException,
    );
  });

  testWidgets('missing scheduled departure is identified without inventing one', (tester) async {
    await pumpCard(tester, candidateWithDeparture(null), DateTime(2026, 10, 14, 9, 55));
    expect(find.text('予定発車時刻を確認できません'), findsOneWidget);
  });
}

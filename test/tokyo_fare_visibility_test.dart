import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/fare_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/pages/route_detail_page.dart';
import 'package:toeigo/widgets/route_card.dart';

void main() {
  final candidate = Candidate(
    id: 'tokyo-no-fare',
    lines: const ['銀座線'],
    linesEn: const ['Ginza Line'],
    rides: 1,
    boards: 1,
    transfers: 0,
    total: 10,
    totalTime: 10,
    arrivalTime: '10:10',
    points: const [],
    steps: [
      StepSeg(
        stepId: 'metro-1',
        kind: 'rail',
        title: '銀座線',
        titleEn: 'Ginza Line',
        fromName: '渋谷',
        fromNameEn: 'Shibuya',
        toName: '表参道',
        toNameEn: 'Omote-sando',
        departureTime: '10:00',
        arrivalTime: '10:10',
      ),
    ],
  );
  const fare = FareQuote(
    normalFareYen: null,
    payNowYen: 0,
    effectiveFareYen: 0,
    policyId: 'tokyo_toei_transport_pass',
    settlementType: 'free_pass',
    status: 'available',
  );

  Widget app(Widget home) => ProviderScope(
    child: CupertinoApp(
      locale: const Locale('ja'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: home,
    ),
  );

  testWidgets('Tokyo route candidate does not display fare or zero yen', (
    tester,
  ) async {
    await tester.pumpWidget(
      app(RouteCard(candidate: candidate, rank: 1, fare: fare)),
    );

    expect(find.textContaining('0円'), findsNothing);
    expect(find.textContaining('支払'), findsNothing);
  });

  testWidgets('Tokyo route detail does not display fare or zero yen', (
    tester,
  ) async {
    await tester.pumpWidget(
      app(
        RouteDetailPage(candidate: candidate, fare: fare, fromSavedRoute: true),
      ),
    );
    await tester.pump();

    expect(find.textContaining('0円'), findsNothing);
    expect(find.textContaining('今回の支払'), findsNothing);
  });
}

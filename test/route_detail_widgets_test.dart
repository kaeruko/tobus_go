import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/fare_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';

Widget localizedApp(Widget home, {Locale locale = const Locale('ja')}) {
  return CupertinoApp(
    locale: locale,
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: home,
  );
}

void main() {
  Candidate candidate() => Candidate(
    id: 'shared-detail',
    lines: const ['008'],
    linesEn: const ['Route 008'],
    rides: 1,
    boards: 1,
    transfers: 0,
    total: 20,
    totalTime: 20,
    originName: '横浜駅',
    originNameEn: 'Yokohama Station',
    destinationName: '山下公園',
    destinationNameEn: 'Yamashita Park',
    arrivalTime: '10:20',
    points: const [],
    steps: [
      StepSeg(
        stepId: 'walk-1',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '横浜駅',
        fromNameEn: 'Yokohama Station',
        toName: '横浜駅前',
        toNameEn: 'Yokohama Station',
        minutes: 2,
        meters: 120,
      ),
      StepSeg(
        stepId: 'bus-1',
        kind: 'bus',
        title: '008系統',
        titleEn: 'Route 008',
        fromName: '横浜駅前',
        fromNameEn: 'Yokohama Station',
        toName: '山下公園前',
        toNameEn: 'Yamashita Park',
        minutes: 15,
      ),
    ],
  );

  testWidgets(
    'shared summary shows walking distance rather than segment count',
    (tester) async {
      await tester.pumpWidget(
        localizedApp(RouteSummary(candidate: candidate())),
      );

      expect(find.text('10:00'), findsOneWidget);
      expect(find.text('10:20'), findsOneWidget);
      expect(find.text('120m'), findsOneWidget);
      expect(find.text('徒歩'), findsOneWidget);
    },
  );

  testWidgets('shared endpoint, step, and fare widgets keep one layout', (
    tester,
  ) async {
    const fare = FareQuote(
      normalFareYen: 220,
      payNowYen: 220,
      effectiveFareYen: 220,
      policyId: 'normal',
      settlementType: 'normal',
      status: 'available',
    );
    final route = candidate();

    await tester.pumpWidget(
      localizedApp(
        ListView(
          children: [
            RouteEndpointSummary(candidate: route),
            const FareSummary(fare: fare),
            RouteStepTile(segment: route.steps[1]),
          ],
        ),
      ),
    );

    expect(find.text('横浜駅'), findsOneWidget);
    expect(find.text('山下公園'), findsOneWidget);
    expect(find.text('通常払い'), findsNothing);
    expect(find.text('今回の支払 220円'), findsOneWidget);
    expect(find.text('008系統'), findsOneWidget);
    expect(find.text('横浜駅前 → 山下公園前'), findsOneWidget);
  });

  testWidgets('English leading wait renders the bilingual origin', (
    tester,
  ) async {
    final route = Candidate.fromJson({
      'id': 'leading-wait-en',
      'lines': ['上23'],
      'lines_en': ['Ueno-Matsuzakaya'],
      'rides': 1,
      'walking_distance_meters': 634,
      'walking_segment_count': 1,
      'boards': 1,
      'transfers': 0,
      'total': 64,
      'total_time': 64,
      'origin_name': '押上',
      'origin_name_en': 'Oshiage',
      'destination_name': '上野',
      'destination_name_en': 'Ueno',
      'steps': [
        {
          'step_id': 'walk-origin',
          'kind': 'walk',
          'title': '徒歩',
          'from_': '現在地',
          'to': '押上駅前',
          'minutes': 8,
          'meters': 634.0,
        },
        {
          'step_id': 'wait-origin',
          'kind': 'wait',
          'title': '待ち時間',
          'from_': '押上駅前',
          'to': '押上駅前',
          'minutes': 2,
          'meters': 0.0,
          'departure_time': '20:45',
          'arrival_time': '20:47',
        },
        {
          'step_id': 'bus-1',
          'kind': 'bus',
          'title': '上23 上野松坂屋前行',
          'title_en': '上23 · Ueno-Matsuzakaya',
          'from_': '押上駅前',
          'from_en': 'Oshiage Sta.',
          'to': '上野松坂屋前',
          'to_en': 'Ueno-Matsuzakaya',
          'minutes': 54,
          'meters': 0.0,
          'departure_time': '20:47',
          'arrival_time': '21:41',
        },
      ],
    });

    await tester.pumpWidget(
      localizedApp(
        ListView(
          children: [
            RouteStepTile(segment: route.steps.first),
          ],
        ),
        locale: const Locale('en'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Wait'), findsOneWidget);
    expect(find.text('Wait at Oshiage (押上)'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('normal fare summary disappears when it has no fare amounts', (
    tester,
  ) async {
    const fare = FareQuote(
      normalFareYen: null,
      payNowYen: null,
      effectiveFareYen: null,
      policyId: 'normal',
      settlementType: 'normal',
      status: 'unavailable',
    );

    await tester.pumpWidget(
      localizedApp(const FareSummary(fare: fare)),
    );

    expect(find.text('通常払い'), findsNothing);
    expect(find.byType(Container), findsNothing);
  });
  testWidgets('shared detail widgets render English labels', (tester) async {
    const fare = FareQuote(
      normalFareYen: 220,
      payNowYen: 0,
      effectiveFareYen: 0,
      policyId: 'free-pass',
      settlementType: 'free_pass',
      status: 'available',
    );

    await tester.pumpWidget(
      localizedApp(
        ListView(
          children: [
            RouteEndpointSummary(candidate: candidate()),
            RouteSummary(candidate: candidate()),
            const FareSummary(fare: fare),
            RouteStepTile(segment: candidate().steps.first),
          ],
        ),
        locale: const Locale('en'),
      ),
    );

    expect(find.text('From'), findsOneWidget);
    expect(find.text('To'), findsOneWidget);
    expect(find.text('Duration'), findsOneWidget);
    expect(find.text('Ride segments'), findsOneWidget);
    expect(find.text('Walk'), findsWidgets);
    expect(find.text('Free pass'), findsOneWidget);
    expect(find.text('Pay now ¥0'), findsOneWidget);
  });

}

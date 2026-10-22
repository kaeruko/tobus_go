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
    originName: '出発駅',
    originNameEn: 'Origin Station',
    destinationName: '山下公園',
    destinationNameEn: 'Yamashita Park',
    arrivalTime: '10:20',
    departureDate: DateTime(2026, 10, 9, 10, 0),
    points: const [],
    steps: [
      StepSeg(
        stepId: 'walk-1',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '出発駅',
        fromNameEn: 'Origin Station',
        toName: '出発駅前',
        toNameEn: 'Origin Station',
        minutes: 2,
        meters: 120,
      ),
      StepSeg(
        stepId: 'bus-1',
        kind: 'bus',
        title: '008系統',
        titleEn: 'Route 008',
        fromName: '出発駅前',
        fromNameEn: 'Origin Station',
        toName: '山下公園前',
        toNameEn: 'Yamashita Park',
        minutes: 15,
        departureTime: '10:02',
        arrivalTime: '10:17',
      ),
    ],
  );

  test('route-step timetable reference uses the planned bus departure', () {
    final route = candidate();
    final reference = routeStepTimetableReferenceTime(route, route.steps[1]);

    expect(reference, DateTime(2026, 10, 9, 10, 2));
  });

  test('route-step timetable reference preserves GTFS after-midnight hours', () {
    final route = candidate();
    final overnightBus = StepSeg(
      stepId: 'overnight-bus',
      kind: 'bus',
      title: '深夜バス',
      departureTime: '25:10',
    );

    final reference = routeStepTimetableReferenceTime(route, overnightBus);

    expect(reference, DateTime(2026, 10, 10, 1, 10));
  });

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

    expect(find.text('出発駅'), findsOneWidget);
    expect(find.text('山下公園'), findsOneWidget);
    expect(find.text('通常払い'), findsNothing);
    expect(find.text('今回の支払 220円'), findsOneWidget);
    expect(find.text('008系統'), findsOneWidget);
    expect(find.text('出発駅前 → 山下公園前'), findsOneWidget);
  });

  for (final kind in ['walk', 'wait', 'bus', 'rail']) {
    testWidgets('$kind step shows its scheduled clock at narrow large text', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(320, 640));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final segment = StepSeg(
        stepId: 'clock-$kind',
        kind: kind,
        title: '深夜便',
        fromName: '出発地',
        toName: '到着地',
        minutes: 7,
        meters: kind == 'walk' ? 307 : 0,
        edges: kind == 'bus' || kind == 'rail' ? 11 : 0,
        departureTime: '25:10',
        arrivalTime: '25:17',
      );

      await tester.pumpWidget(
        localizedApp(
          Builder(
            builder: (context) => MediaQuery(
              data: MediaQuery.of(context).copyWith(
                textScaler: TextScaler.linear(2),
              ),
              child: ListView(children: [RouteStepTile(segment: segment)]),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('25:10 → 25:17'), findsOneWidget);
      expect(find.text('307m'), findsNothing);
      expect(find.text('11停'), findsNothing);
      expect(find.textContaining('約'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('partial or missing step clocks stay explicit without estimates', (
    tester,
  ) async {
    for (final clock in [
      (departure: ' 10:02 ', arrival: null, label: '10:02発'),
      (departure: null, arrival: '10:17', label: '10:17着'),
      (departure: ' ', arrival: null, label: '時刻不明'),
    ]) {
      final segment = StepSeg(
        stepId: 'partial-clock',
        kind: 'walk',
        title: '徒歩',
        minutes: 15,
        departureTime: clock.departure,
        arrivalTime: clock.arrival,
      );
      await tester.pumpWidget(
        localizedApp(ListView(children: [RouteStepTile(segment: segment)])),
      );
      await tester.pumpAndSettle();

      expect(find.text(clock.label), findsOneWidget);
      expect(find.textContaining('15分'), findsNothing);
      expect(find.textContaining('→'), findsNothing);
      expect(tester.takeException(), isNull);
    }
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

  testWidgets(
    'English wait location fails fast when official English is missing',
    (tester) async {
      final wait = StepSeg(
        stepId: 'wait-missing-en',
        kind: 'wait',
        title: '待ち時間',
        fromName: '出発駅前',
        toName: '出発駅前',
        place: '出発駅前',
        minutes: 2,
      );

      await tester.pumpWidget(
        localizedApp(
          ListView(children: [RouteStepTile(segment: wait)]),
          locale: const Locale('en'),
        ),
      );
      await tester.pump();

      final error = tester.takeException();
      expect(error, isA<StateError>());
      expect(error.toString(), contains('field=place_en'));
      expect(error.toString(), contains('stepId=wait-missing-en'));
    },
  );

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

  testWidgets('planned route keeps shared clock layout without warnings or fabricated distance', (tester) async {
    final planned = Candidate(
      planningNotice: 'internal provenance only',
      id: 'shared-planned',
      lines: const ['008'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 20,
      totalTime: 20,
      walkingDistanceMeters: 0,
      walkingSegmentCount: 1,
      arrivalTime: '10:20',
      points: const [],
      steps: [
        StepSeg(
          stepId: 'planned-walk',
          kind: 'walk',
          title: '徒歩（推定）',
          minutes: 3,
          meters: 0,
          departureTime: '10:00',
          arrivalTime: '10:03',
          planningDetails: {
            'physical_walk_meters': null,
            'notice': 'internal walk source',
          },
        ),
      ],
    );
    await tester.pumpWidget(localizedApp(ListView(children: [
      RouteSummary(candidate: planned),
      RouteStepTile(segment: planned.steps.single),
    ])));
    await tester.pumpAndSettle();
    expect(find.text('10:20'), findsOneWidget);
    expect(find.text('--'), findsOneWidget);
    expect(find.text('10:00 → 10:03'), findsOneWidget);
    expect(find.textContaining('目安'), findsNothing);
    expect(find.textContaining('internal'), findsNothing);
    expect(find.text('0m'), findsNothing);
    expect(tester.takeException(), isNull);
  });

}

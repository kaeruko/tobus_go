import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/models/fare_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';

void main() {
  Candidate candidate() => Candidate(
    id: 'shared-detail',
    lines: const ['008'],
    rides: 1,
    boards: 1,
    transfers: 0,
    total: 20,
    totalTime: 20,
    originName: '横浜駅',
    destinationName: '山下公園',
    arrivalTime: '10:20',
    points: const [],
    steps: [
      StepSeg(
        stepId: 'walk-1',
        kind: 'walk',
        title: '徒歩',
        fromName: '横浜駅',
        toName: '横浜駅前',
        minutes: 2,
        meters: 120,
      ),
      StepSeg(
        stepId: 'bus-1',
        kind: 'bus',
        title: '008系統',
        fromName: '横浜駅前',
        toName: '山下公園前',
        minutes: 15,
      ),
    ],
  );

  testWidgets(
    'shared summary shows walking distance rather than segment count',
    (tester) async {
      await tester.pumpWidget(
        CupertinoApp(home: RouteSummary(candidate: candidate())),
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
      CupertinoApp(
        home: ListView(
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
    expect(find.text('今回の支払 220円'), findsOneWidget);
    expect(find.text('008系統'), findsOneWidget);
    expect(find.text('横浜駅前 → 山下公園前'), findsOneWidget);
  });
}

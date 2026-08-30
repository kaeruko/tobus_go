import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/pages/route_only_detail_page.dart';

void main() {
  testWidgets('route-only detail exposes this-route action', (tester) async {
    final candidate = Candidate(
      id: 'candidate-1',
      lines: const ['8'],
      rides: 1,
      walks: 0,
      boards: 1,
      transfers: 0,
      total: 15,
      totalTime: 15,
      steps: [
        StepSeg(
          stepId: 'bus-1',
          kind: 'bus',
          title: '8系統',
          routeId: 'yokohama_bus:R1',
          tripId: 'yokohama_bus:T1',
        ),
      ],
      points: const [],
      arrivalTime: '10:15',
    );

    await tester.pumpWidget(
      CupertinoApp(
        home: RouteOnlyDetailPage(candidate: candidate),
      ),
    );

    expect(find.text('この経路で行く'), findsOneWidget);
    expect(find.text('8系統'), findsOneWidget);
  });
}

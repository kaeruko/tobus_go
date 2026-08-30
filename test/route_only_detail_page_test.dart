import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/core/city_profile.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/pages/route_detail_page.dart';
import 'package:toeigo/providers/city_profile_provider.dart';

void main() {
  testWidgets('Yokohama uses shared detail and exposes realtime action', (
    tester,
  ) async {
    final candidate = Candidate(
      id: 'candidate-1',
      lines: const ['8'],
      rides: 1,
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
      ProviderScope(
        overrides: [cityProfileProvider.overrideWithValue(yokohamaCityProfile)],
        child: CupertinoApp(home: RouteDetailPage(candidate: candidate)),
      ),
    );

    expect(find.text('この経路で行く'), findsOneWidget);
    expect(find.text('所要時間'), findsOneWidget);
    expect(find.text('乗車区間'), findsOneWidget);
    expect(find.text('8系統'), findsOneWidget);
    expect(find.byIcon(CupertinoIcons.bookmark), findsNothing);
  });
}

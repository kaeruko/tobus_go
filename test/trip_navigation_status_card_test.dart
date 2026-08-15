import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
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
}

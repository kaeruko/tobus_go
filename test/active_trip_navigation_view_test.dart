import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/active_trip_navigation_view.dart';

void main() {
  testWidgets('共通statusとmode固有slotを同じ骨格へ配置する', (tester) async {
    var stopsTapped = false;
    final busStep = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '上23',
      fromName: '浅草',
      toName: '平井駅前',
    );
    final navState = NavigationState(
      mainText: '上23 乗車中',
      subText: '浅草',
      color: Colors.green,
      statusLabel: '🚌乗車中',
      remainingStops: 2,
      currentStepId: busStep.stepId,
      step: busStep,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ActiveTripNavigationView(
          navState: navState,
          tripTitle: 'テスト移動',
          appBar: AppBar(title: const Text('共通ナビ')),
          onTapStops: () => stopsTapped = true,
          statusHeaderTrailing: const Text('09:30'),
          beforeScheduleSections: const [Text('遅延セクション')],
          scheduleSection: const Text('予定ウィンドウ'),
          afterScheduleSections: const [Text('モード固有操作')],
          bottomNavigationBar: const Text('下部操作'),
        ),
      ),
    );

    expect(find.text('共通ナビ'), findsOneWidget);
    expect(find.text('テスト移動'), findsOneWidget);
    expect(find.text('09:30'), findsOneWidget);
    expect(find.text('遅延セクション'), findsOneWidget);
    expect(find.text('予定ウィンドウ'), findsOneWidget);
    expect(find.text('モード固有操作'), findsOneWidget);
    expect(find.text('下部操作'), findsOneWidget);

    await tester.tap(find.text('のこり 2 回停車'));
    expect(stopsTapped, isTrue);
  });

  testWidgets('roleを知らず空のtripTitleはfail-fastする', (tester) async {
    final navState = const NavigationState(
      mainText: '徒歩',
      subText: '移動中',
      color: Colors.white,
      statusLabel: '徒歩',
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ActiveTripNavigationView(
          navState: navState,
          tripTitle: '   ',
          appBar: AppBar(),
          onTapStops: () {},
          scheduleSection: const Text('予定'),
        ),
      ),
    );

    final error = tester.takeException();
    expect(error, isA<StateError>());
    expect(error.toString(), contains('tripTitleが空'));
  });
}

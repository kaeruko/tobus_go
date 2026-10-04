import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:toeigo/logic/delay_impact_analyzer.dart';
import 'package:toeigo/logic/next_ride_realtime.dart';
import 'package:toeigo/widgets/delay_recovery_card.dart';

void main() {
  testWidgets('shows only compact transfer facts for a passed next ride', (
    tester,
  ) async {
    final impact = DelayImpact(
      legIndex: 0,
      currentStepId: 'ride-1',
      currentRideTitle: '都01',
      currentAlightingPlaceName: '新橋',
      plannedArrivalAt: DateTime(2026, 10, 4, 19, 20),
      predictedArrivalAt: DateTime(2026, 10, 4, 19, 25),
      delay: const Duration(minutes: 5),
      nextRideStepId: 'ride-2',
      nextRideTitle: '都01（T01） 渋谷駅前行',
      nextDepartureAt: DateTime(2026, 10, 4, 19, 31),
      transferWalkMinutes: 2,
      transferBoardingMinutes: 0,
      earliestTransferReadyAt: DateTime(2026, 10, 4, 19, 27),
      nextTransferFeasible: false,
      missedBy: const Duration(minutes: 4),
      basis: DelayImpactBasis.confirmedTransferPlace,
    );
    final realtime = NextRideRealtimeDeparture(
      stepId: 'ride-2',
      boardingPlaceName: '新橋駅前',
      status: NextRideRealtimeDepartureStatus.passedBoardingPlace,
      observedAt: DateTime(2026, 10, 4, 19, 54),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: DelayRecoveryCard(
            impact: impact,
            nextRideRealtime: realtime,
            action: TextButton(
              onPressed: () {},
              child: const Text('経路を見直す'),
            ),
          ),
        ),
      ),
    );

    expect(find.text('次の乗換えに間に合わない可能性があります'), findsOneWidget);
    expect(find.text('19:25 新橋'), findsOneWidget);
    expect(find.text('徒歩2分'), findsOneWidget);
    expect(find.text('19:54 次便は新橋駅前を通過'), findsOneWidget);
    expect(find.text('経路を見直す'), findsOneWidget);

    expect(find.textContaining('現在地を推測せず'), findsNothing);
    expect(find.textContaining('次便Realtime:'), findsNothing);
    expect(find.textContaining('予定はまだ変更していません'), findsNothing);
  });
}

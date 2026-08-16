import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/delay_impact_analyzer.dart';
import 'package:toeigo/logic/route_replan_presentation.dart';

void main() {
  final base = DateTime(2026, 8, 16, 9);

  DelayImpact impact({
    required Duration delay,
    required bool feasible,
  }) {
    final plannedArrival = base;
    final predictedArrival = plannedArrival.add(delay);
    final nextDeparture = base.add(const Duration(minutes: 10));
    return DelayImpact(
      legIndex: 0,
      currentStepId: 'ride-1',
      currentRideTitle: '上23',
      currentAlightingPlaceName: '本所吾妻橋',
      plannedArrivalAt: plannedArrival,
      predictedArrivalAt: predictedArrival,
      delay: delay,
      nextRideStepId: 'rail-1',
      nextRideTitle: '浅草線',
      nextDepartureAt: nextDeparture,
      transferWalkMinutes: 2,
      earliestTransferReadyAt: predictedArrival.add(
        const Duration(minutes: 2),
      ),
      nextTransferFeasible: feasible,
      missedBy: feasible ? Duration.zero : const Duration(minutes: 1),
      basis: DelayImpactBasis.ridingPrediction,
    );
  }

  test('遅延情報なしでは経路見直しを表示しない', () {
    final presentation = RouteReplanPresentation.fromDelayImpact(null);

    expect(presentation.showAction, isFalse);
    expect(presentation.showWarning, isFalse);
  });

  test('定刻では経路見直しを表示しない', () {
    final presentation = RouteReplanPresentation.fromDelayImpact(
      impact(delay: Duration.zero, feasible: true),
    );

    expect(presentation.showAction, isFalse);
    expect(presentation.showWarning, isFalse);
  });

  test('早着では経路見直しを表示しない', () {
    final presentation = RouteReplanPresentation.fromDelayImpact(
      impact(delay: const Duration(minutes: -2), feasible: true),
    );

    expect(presentation.showAction, isFalse);
    expect(presentation.showWarning, isFalse);
  });

  test('正の遅延があれば乗換え可能でも経路見直しを表示する', () {
    final presentation = RouteReplanPresentation.fromDelayImpact(
      impact(delay: const Duration(minutes: 3), feasible: true),
    );

    expect(presentation.showAction, isTrue);
    expect(presentation.showWarning, isFalse);
  });

  test('乗換え不成立なら警告内で経路見直しを表示する', () {
    final presentation = RouteReplanPresentation.fromDelayImpact(
      impact(delay: const Duration(minutes: 5), feasible: false),
    );

    expect(presentation.showAction, isTrue);
    expect(presentation.showWarning, isTrue);
  });
}

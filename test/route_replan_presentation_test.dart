import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/delay_impact_analyzer.dart';
import 'package:toeigo/logic/next_ride_delay_adjuster.dart';
import 'package:toeigo/logic/next_ride_realtime.dart';
import 'package:toeigo/logic/route_replan_presentation.dart';

void main() {
  final base = DateTime(2026, 8, 16, 9);

  DelayImpact impact({
    required Duration delay,
    required bool feasible,
    Duration? missedBy,
    DelayImpactBasis basis = DelayImpactBasis.ridingPrediction,
  }) {
    final plannedArrival = base;
    final predictedArrival = plannedArrival.add(delay);
    final readyAt = predictedArrival.add(const Duration(minutes: 2));
    final shortfall = feasible
        ? Duration.zero
        : (missedBy ?? const Duration(minutes: 1));
    final nextDeparture = feasible
        ? readyAt.add(const Duration(minutes: 10))
        : readyAt.subtract(shortfall);
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
      transferBoardingMinutes: 0,
      earliestTransferReadyAt: readyAt,
      nextTransferFeasible: feasible,
      missedBy: shortfall,
      basis: basis,
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

  test('正の遅延があっても乗換え可能なら経路見直しを表示しない', () {
    final presentation = RouteReplanPresentation.fromDelayImpact(
      impact(delay: const Duration(minutes: 3), feasible: true),
    );

    expect(presentation.showAction, isFalse);
    expect(presentation.showWarning, isFalse);
  });

  for (final basis in DelayImpactBasis.values) {
    group(basis.name, () {
      test('本所吾妻橋の約75秒不足は警告を抑え、計算結果は保持する', () {
        final arrivalAt = DateTime(2026, 10, 4, 8, 49, 42, 317, 861);
        final readyAt = arrivalAt.add(const Duration(minutes: 4));
        final departureAt = DateTime(2026, 10, 4, 8, 52, 27);
        final baseImpact = DelayImpact(
          legIndex: 0,
          currentStepId: 'ride-1',
          currentRideTitle: '上23',
          currentAlightingPlaceName: '本所吾妻橋',
          plannedArrivalAt: DateTime(2026, 10, 4, 8, 47),
          predictedArrivalAt: arrivalAt,
          delay: arrivalAt.difference(DateTime(2026, 10, 4, 8, 47)),
          nextRideStepId: 'rail-1',
          nextRideTitle: '浅草線',
          nextDepartureAt: DateTime(2026, 10, 4, 8, 51),
          transferWalkMinutes: 2,
          transferBoardingMinutes: 2,
          earliestTransferReadyAt: readyAt,
          nextTransferFeasible: false,
          missedBy: readyAt.difference(DateTime(2026, 10, 4, 8, 51)),
          basis: basis,
        );
        final realtime = NextRideRealtimeDeparture(
          stepId: 'rail-1',
          boardingPlaceName: '本所吾妻橋',
          status: NextRideRealtimeDepartureStatus.predicted,
          observedAt: DateTime(2026, 10, 4, 8, 50),
          predictedDepartureAt: departureAt,
        );
        final adjusted = NextRideDelayAdjuster.apply(
          base: baseImpact,
          realtime: realtime,
        );
        final presentation = RouteReplanPresentation.fromDelayImpact(
          adjusted.impact,
          nextRideRealtime: adjusted.realtime,
        );

        expect(presentation.showAction, isFalse);
        expect(presentation.showWarning, isFalse);
        expect(adjusted.impact.nextTransferFeasible, isFalse);
        expect(adjusted.impact.missedBy.inSeconds, 75);
        expect(adjusted.impact.earliestTransferReadyAt, readyAt);
        expect(adjusted.impact.transferWalkMinutes, 2);
        expect(adjusted.impact.transferBoardingMinutes, 2);
        expect(adjusted.impact.nextDepartureAt, departureAt);
        expect(adjusted.impact.basis, basis);
      });

      test('5分ちょうどの乗換え不足は警告しない', () {
        final presentation = RouteReplanPresentation.fromDelayImpact(
          impact(
            delay: const Duration(minutes: 5),
            feasible: false,
            missedBy: const Duration(minutes: 5),
            basis: basis,
          ),
        );

        expect(presentation.showAction, isFalse);
        expect(presentation.showWarning, isFalse);
      });

      test('5分を1秒超える乗換え不足は警告する', () {
        final presentation = RouteReplanPresentation.fromDelayImpact(
          impact(
            delay: const Duration(minutes: 6),
            feasible: false,
            missedBy: const Duration(minutes: 5, seconds: 1),
            basis: basis,
          ),
        );

        expect(presentation.showAction, isTrue);
        expect(presentation.showWarning, isTrue);
      });

      test('乗車地点で停車中の次便は通過済みと扱わない', () {
        final baseImpact = impact(
          delay: const Duration(minutes: 1),
          feasible: false,
          basis: basis,
        );
        final adjusted = NextRideDelayAdjuster.apply(
          base: baseImpact,
          realtime: NextRideRealtimeDeparture(
            stepId: 'rail-1',
            boardingPlaceName: '本所吾妻橋',
            status: NextRideRealtimeDepartureStatus.atBoardingPlace,
            observedAt: baseImpact.nextDepartureAt,
          ),
        );
        final presentation = RouteReplanPresentation.fromDelayImpact(
          adjusted.impact,
          nextRideRealtime: adjusted.realtime,
        );

        expect(adjusted.impact.missedBy, const Duration(minutes: 1));
        expect(presentation.showAction, isFalse);
        expect(presentation.showWarning, isFalse);
      });

      for (final passedAfterReady in [false, true]) {
        final shortfallLabel = passedAfterReady ? '不足ゼロ' : '不足1分';
        test('次便通過済みは$shortfallLabelでも警告する', () {
          final baseImpact = impact(
            delay: const Duration(minutes: 1),
            feasible: false,
            basis: basis,
          );
          final adjusted = NextRideDelayAdjuster.apply(
            base: baseImpact,
            realtime: NextRideRealtimeDeparture(
              stepId: 'rail-1',
              boardingPlaceName: '本所吾妻橋',
              status: NextRideRealtimeDepartureStatus.passedBoardingPlace,
              observedAt: passedAfterReady
                  ? baseImpact.earliestTransferReadyAt.add(
                      const Duration(seconds: 1),
                    )
                  : baseImpact.nextDepartureAt,
            ),
          );
          final presentation = RouteReplanPresentation.fromDelayImpact(
            adjusted.impact,
            nextRideRealtime: adjusted.realtime,
          );

          expect(
            adjusted.impact.missedBy,
            passedAfterReady ? Duration.zero : const Duration(minutes: 1),
          );
          expect(adjusted.impact.nextTransferFeasible, isFalse);
          expect(presentation.showAction, isTrue);
          expect(presentation.showWarning, isTrue);
        });
      }
    });
  }

  test('別の次便のRealtimeを渡したら診断情報付きで停止する', () {
    expect(
      () => RouteReplanPresentation.fromDelayImpact(
        impact(delay: Duration.zero, feasible: true),
        nextRideRealtime: NextRideRealtimeDeparture(
          stepId: 'different-rail',
          boardingPlaceName: '本所吾妻橋',
          status: NextRideRealtimeDepartureStatus.passedBoardingPlace,
          observedAt: base,
        ),
      ),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('rail-1 != different-rail'),
        ),
      ),
    );
  });
}

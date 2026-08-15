import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/rail_progress.dart';
import 'package:toeigo/services/train_location_source.dart';

void main() {
  const sparseStops = <TrainTripStop>[
    TrainTripStop(sequence: 1, stopId: 'A', stopName: 'A駅'),
    TrainTripStop(sequence: 10, stopId: 'B', stopName: 'B駅'),
    TrainTripStop(sequence: 30, stopId: 'C', stopName: 'C駅'),
    TrainTripStop(sequence: 90, stopId: 'D', stopName: 'D駅'),
  ];

  TrainLocation sparseLocation({
    required int currentSequence,
    required String status,
    int boardingSequence = 1,
    int destinationSequence = 90,
  }) {
    final current = sparseStops.firstWhere(
      (stop) => stop.sequence == currentSequence,
    );
    return TrainLocation(
      tripId: 'sparse-trip',
      routeId: 'rail-1',
      tripHeadsign: 'D駅',
      vehicleId: 'train-1',
      currentStopSequence: currentSequence,
      currentStatus: status,
      currentStopId: current.stopId,
      currentStopName: current.stopName,
      boardingSequence: boardingSequence,
      destinationSequence: destinationSequence,
      vehicleAgeSeconds: 4,
      tripStops: sparseStops,
    );
  }

  test('STOPPED_ATの残り駅数はstop_sequence差ではなく停車駅indexで数える', () {
    final progress = RailProgress.forLocation(
      stepId: 'step-rail',
      location: sparseLocation(
        currentSequence: 30,
        status: 'STOPPED_AT',
      ),
    );

    expect(progress.phase, RailProgressPhase.riding);
    expect(progress.lastReachedSequence, 30);
    expect(progress.remainingStops, 1);
    expect(progress.currentStopName, 'C駅');
    expect(progress.nextStopName, 'D駅');
  });

  test('IN_TRANSIT_TOの直前駅もtrip_stopsの前indexから求める', () {
    final progress = RailProgress.forLocation(
      stepId: 'step-rail',
      location: sparseLocation(
        currentSequence: 30,
        status: 'IN_TRANSIT_TO',
      ),
    );

    expect(progress.phase, RailProgressPhase.riding);
    expect(progress.lastReachedSequence, 10);
    expect(progress.remainingStops, 2);
    expect(progress.currentStopName, 'B駅');
    expect(progress.nextStopName, 'C駅');
  });

  test('乗車駅までの駅数も停車駅indexで数える', () {
    final progress = RailProgress.forLocation(
      stepId: 'step-rail',
      location: sparseLocation(
        currentSequence: 10,
        status: 'STOPPED_AT',
        boardingSequence: 30,
      ),
    );

    expect(progress.phase, RailProgressPhase.approaching);
    expect(progress.stopsUntilBoarding, 1);
    expect(progress.remainingStops, 2);
    expect(progress.currentStopName, 'B駅');
    expect(progress.nextStopName, 'C駅');
  });

  test('trip_stopsがsequence昇順でなければ並べ替えずfail-fastする', () {
    const invalidStops = <TrainTripStop>[
      TrainTripStop(sequence: 1, stopId: 'A', stopName: 'A駅'),
      TrainTripStop(sequence: 30, stopId: 'C', stopName: 'C駅'),
      TrainTripStop(sequence: 10, stopId: 'B', stopName: 'B駅'),
      TrainTripStop(sequence: 90, stopId: 'D', stopName: 'D駅'),
    ];
    final location = TrainLocation(
      tripId: 'invalid-order-trip',
      routeId: 'rail-1',
      tripHeadsign: 'D駅',
      vehicleId: 'train-2',
      currentStopSequence: 30,
      currentStatus: 'STOPPED_AT',
      currentStopId: 'C',
      currentStopName: 'C駅',
      boardingSequence: 1,
      destinationSequence: 90,
      tripStops: invalidStops,
    );

    expect(
      () => RailProgress.forLocation(
        stepId: 'step-rail',
        location: location,
      ),
      throwsStateError,
    );
  });
}

import 'package:flutter_test/flutter_test.dart';
import 'package:tobus_go/logic/trip_navigator.dart';
import 'package:tobus_go/models/rail_progress.dart';
import 'package:tobus_go/models/route_models.dart';
import 'package:tobus_go/services/train_location_source.dart';

void main() {
  const tripStops = <TrainTripStop>[
    TrainTripStop(sequence: 9, stopId: '115', stopName: '東日本橋'),
    TrainTripStop(sequence: 10, stopId: '116', stopName: '浅草橋'),
    TrainTripStop(sequence: 11, stopId: '117', stopName: '蔵前'),
  ];

  TrainLocation location({
    required int sequence,
    required String status,
    required String currentName,
  }) {
    final currentStop = tripStops.firstWhere(
      (stop) => stop.sequence == sequence,
    );
    return TrainLocation(
      tripId: '121603T0',
      routeId: '1',
      vehicleId: '121603T0',
      currentStopSequence: sequence,
      currentStatus: status,
      currentStopId: currentStop.stopId,
      currentStopName: currentName,
      boardingSequence: 9,
      destinationSequence: 11,
      vehicleAgeSeconds: 5,
      tripStops: tripStops,
    );
  }

  test('IN_TRANSIT_TO counts the approached station as still remaining', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 10,
        status: 'IN_TRANSIT_TO',
        currentName: '浅草橋',
      ),
    );

    expect(progress.phase, RailProgressPhase.riding);
    expect(progress.lastReachedSequence, 9);
    expect(progress.remainingStops, 2);
    expect(progress.currentStopName, '東日本橋');
    expect(progress.nextStopName, '浅草橋');
  });

  test('STOPPED_AT reduces remaining stations immediately', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 10,
        status: 'STOPPED_AT',
        currentName: '浅草橋',
      ),
    );

    expect(progress.phase, RailProgressPhase.riding);
    expect(progress.lastReachedSequence, 10);
    expect(progress.remainingStops, 1);
    expect(progress.currentStopName, '浅草橋');
    expect(progress.nextStopName, '蔵前');
  });

  test('destination STOPPED_AT marks the rail ride arrived', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 11,
        status: 'STOPPED_AT',
        currentName: '蔵前',
      ),
    );

    expect(progress.phase, RailProgressPhase.arrived);
    expect(progress.remainingStops, 0);
  });

  test('rail navigation exposes remaining stations to shared card', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 10,
        status: 'IN_TRANSIT_TO',
        currentName: '浅草橋',
      ),
    );
    final step = StepSeg(
      stepId: 'rail-1',
      kind: 'rail',
      title: '浅草線',
      fromName: '東日本橋',
      toName: '蔵前',
      arrivalTime: '16:24',
    );

    final navigation = NavigationState.navigating(
      step: step,
      busProgress: null,
      railProgress: progress,
    );

    expect(navigation.mainText, '浅草線に乗車中');
    expect(navigation.subText, '蔵前で降ります');
    expect(navigation.remainingStops, 2);
    expect(navigation.nextStopName, '浅草橋');
    expect(navigation.step?.kind, 'rail');
  });
}

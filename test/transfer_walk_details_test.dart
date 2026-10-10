import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/transfer_walk_details.dart';
import 'package:toeigo/models/route_models.dart';

StopPoint stop(String name, double latitude, double longitude) => StopPoint(
  name: name,
  point: LatLng(latitude, longitude),
);

List<StepSeg> transferSteps({
  double boardingLatitude = 35.710,
  String arrivalClock = '12:04',
  String departureClock = '12:11',
  int walkingMinutes = 3,
}) => [
  StepSeg(
    stepId: 'initial',
    kind: 'walk',
    title: '徒歩',
    minutes: 2,
  ),
  StepSeg(
    stepId: 'ue23',
    kind: 'bus',
    title: '上23 上野松坂屋前行',
    departureTime: '11:30',
    arrivalTime: arrivalClock,
    stops: [
      stop('平井七丁目', 35.70, 139.84),
      stop('浅草雷門', 35.709, 139.799),
    ],
  ),
  StepSeg(
    stepId: 'transfer-walk',
    kind: 'walk',
    title: '徒歩',
    fromName: '浅草雷門',
    toName: '浅草雷門南',
    minutes: walkingMinutes,
    meters: 210,
  ),
  StepSeg(
    stepId: 'transfer-wait',
    kind: 'wait',
    title: '待ち時間',
    minutes: 4,
    departureTime: '12:07',
    arrivalTime: '12:11',
  ),
  StepSeg(
    stepId: 'kusa64',
    kind: 'bus',
    title: '草64 池袋駅東口行',
    departureTime: departureClock,
    arrivalTime: '13:11',
    stops: [
      stop('浅草雷門南', boardingLatitude, 139.800),
      stop('池袋駅東口', 35.729, 139.712),
    ],
  ),
  StepSeg(
    stepId: 'final',
    kind: 'walk',
    title: '徒歩',
    minutes: 4,
  ),
];

void main() {
  test('transfer walk and following wait resolve to the same precise stop pair', () {
    final steps = transferSteps();
    final walking = TransferWalkDetails.forStep(steps, 2);
    final waiting = TransferWalkDetails.forStep(steps, 3);

    expect(walking, isNotNull);
    expect(waiting, isNotNull);
    for (final details in [walking!, waiting!]) {
      expect(details.alightingStop.name, '浅草雷門');
      expect(details.boardingStop.name, '浅草雷門南');
      expect(details.alightingTime, '12:04');
      expect(details.boardingTime, '12:11');
      expect(details.transferMinutes, 7);
      expect(details.walkingStep.stepId, 'transfer-walk');
      expect(details.waitingStep?.stepId, 'transfer-wait');
      expect(details.departingRide.stepId, 'kusa64');
    }
  });

  test('origin/final walks and unrelated waits are not transfer details', () {
    final steps = transferSteps();
    expect(TransferWalkDetails.forStep(steps, 0), isNull);
    expect(TransferWalkDetails.forStep(steps, 1), isNull);
    expect(TransferWalkDetails.forStep(steps, 4), isNull);
    expect(TransferWalkDetails.forStep(steps, 5), isNull);
    expect(
      TransferWalkDetails.forStep([
        StepSeg(stepId: 'wait', kind: 'wait', title: '待ち時間'),
        ...steps,
      ], 0),
      isNull,
    );
  });

  test('walk directly between rides is a valid transfer without waiting', () {
    final steps = transferSteps()..removeAt(3);
    final details = TransferWalkDetails.forStep(steps, 2)!;
    expect(details.waitingStep, isNull);
    expect(details.transferMinutes, 7);
  });

  test('missing transfer pin fails fast instead of placing an invented stop', () {
    final steps = transferSteps(boardingLatitude: 0);
    // Both coordinates must be missing to form the prohibited (0,0) placeholder.
    final departing = steps[4];
    steps[4] = StepSeg(
      stepId: departing.stepId,
      kind: departing.kind,
      title: departing.title,
      departureTime: departing.departureTime,
      stops: [
        stop('浅草雷門南', 0, 0),
        departing.stops.last,
      ],
    );
    expect(
      () => TransferWalkDetails.forStep(steps, 2),
      throwsA(isA<StateError>().having(
        (e) => e.toString(), 'diagnostic', contains('浅草雷門南'),
      )),
    );
  });

  test('missing and invalid clocks fail fast without guessing times', () {
    for (final value in ['', '12:99', 'not-a-time']) {
      final steps = transferSteps(arrivalClock: value);
      expect(
        () => TransferWalkDetails.forStep(steps, 2),
        throwsStateError,
        reason: value,
      );
    }
  });

  test('too-short transfer window fails fast', () {
    final steps = transferSteps(departureClock: '12:05', walkingMinutes: 3);
    expect(
      () => TransferWalkDetails.forStep(steps, 2),
      throwsA(isA<StateError>().having(
        (e) => e.toString(), 'diagnostic', contains('shorter than walking time'),
      )),
    );
  });

  test('overnight transfer uses the local clock rollover', () {
    final steps = transferSteps(
      arrivalClock: '23:57', departureClock: '00:08',
    );
    expect(TransferWalkDetails.forStep(steps, 2)!.transferMinutes, 11);
  });

  test('invalid step index fails fast', () {
    expect(() => TransferWalkDetails.forStep(transferSteps(), -1), throwsRangeError);
  });
}

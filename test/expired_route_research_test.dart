import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/expired_route_research.dart';
import 'package:toeigo/models/route_models.dart';

StepSeg ride({
  String kind = 'bus',
  String? routeId = '023',
  String? direction = 'outbound',
  String tripId = 'first',
  String departure = '09:08',
  List<String?> stopIds = const ['A', 'B', 'C'],
  String boarding = 'A',
  String alighting = 'C',
}) => StepSeg(
  stepId: tripId,
  kind: kind,
  title: 'Same display title',
  routeId: routeId,
  directionId: direction,
  tripId: tripId,
  departureTime: departure,
  departureStopId: boarding,
  arrivalPoleId: alighting,
  stops: [
    for (final id in stopIds)
      StopPoint(name: 'Same name', point: const LatLng(35, 139), stopId: id),
  ],
);

Candidate candidate(String id, List<StepSeg> steps) => Candidate(
  id: id,
  lines: const ['Same display title'],
  rides: steps.where((step) => step.isRide).length,
  boards: steps.where((step) => step.isRide).length,
  transfers: 0,
  total: 20,
  totalTime: 20,
  steps: steps,
  points: const [],
);

void main() {
  final original = candidate('old', [ride()]);

  test('chooses a later matching service instead of a different first result', () {
    final different = candidate('rank-1', [ride(routeId: '064')]);
    final same = candidate('rank-2', [
      StepSeg(stepId: 'wait', kind: 'wait', title: 'Wait', minutes: 10),
      ride(tripId: 'later', departure: '09:28'),
    ]);
    expect(matchingRefreshedRoute(original, [different, same]), same);
  });

  test('never auto-selects a different pole, direction or stop sequence', () {
    final alternatives = [
      candidate('pole', [ride(boarding: 'A-other')]),
      candidate('direction', [ride(direction: 'inbound')]),
      candidate('pattern', [ride(stopIds: ['A', 'D', 'C'])]),
      candidate('missing', [ride(stopIds: ['A', null, 'C'])]),
      candidate('route', [ride(routeId: null)]),
      candidate('extra', [ride(), ride(tripId: 'extra')]),
    ];
    expect(matchingRefreshedRoute(original, alternatives), isNull);
    expect(matchingRefreshedRoute(original, []), isNull);
  });

  test('rail direction is identified by ordered stations without pole IDs', () {
    final old = candidate('old-rail', [
      ride(kind: 'rail', direction: null, boarding: '', alighting: ''),
    ]);
    final reverse = candidate('reverse', [
      ride(kind: 'rail', direction: null, boarding: '', alighting: '',
          stopIds: ['C', 'B', 'A']),
    ]);
    final same = candidate('same-rail', [
      ride(kind: 'rail', direction: null, boarding: '', alighting: '',
          tripId: 'later'),
    ]);
    expect(matchingRefreshedRoute(old, [reverse, same]), same);
  });

  test('unknown identity and walking-only routes require explicit selection', () {
    final unknown = candidate('unknown', [ride(routeId: null)]);
    expect(matchingRefreshedRoute(unknown, [unknown]), isNull);
    final walk = candidate('walk', [
      StepSeg(stepId: 'walk', kind: 'walk', title: 'Walk'),
    ]);
    expect(matchingRefreshedRoute(walk, [walk]), isNull);
  });
}

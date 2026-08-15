import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/services/route_replanner.dart';

void main() {
  RouteReplanRequest request({
    DateTime? availableAt,
    LatLng anchorPoint = const LatLng(35.703, 139.790),
    String candidateId = 'candidate-1',
    String stepId = 'rail-1',
  }) {
    return RouteReplanRequest(
      anchor: ReplanAnchor(
        placeName: '蔵前',
        stopId: 'station-kuramae',
        point: anchorPoint,
        availableAt: availableAt ?? DateTime.utc(2026, 8, 15, 9, 6),
        source: ReplanAnchorSource.predictedNextTransitPlace,
        routeStepId: stepId,
      ),
      activeStepId: stepId,
      originalCandidateId: candidateId,
      destination: const LatLng(35.690, 139.700),
      destinationName: '目的地',
      preference: 'fastest',
    );
  }

  test('same replan state is equal', () {
    expect(
      sameRouteReplanRequestState(request(), request()),
      isTrue,
    );
  });

  test('new realtime ETA invalidates the previous preview request', () {
    expect(
      sameRouteReplanRequestState(
        request(availableAt: DateTime.utc(2026, 8, 15, 9, 6)),
        request(availableAt: DateTime.utc(2026, 8, 15, 9, 8)),
      ),
      isFalse,
    );
  });

  test('same instant with another timezone offset remains the same request', () {
    final utc = DateTime.utc(2026, 8, 15, 9, 6);
    final jst = DateTime.parse('2026-08-15T18:06:00+09:00');

    expect(sameRouteReplanRequestState(
      request(availableAt: utc),
      request(availableAt: jst),
    ), isTrue);
  });

  test('different actionable place invalidates the previous preview request', () {
    expect(
      sameRouteReplanRequestState(
        request(),
        request(anchorPoint: const LatLng(35.710, 139.795)),
      ),
      isFalse,
    );
  });

  test('changed original candidate invalidates the previous preview request', () {
    expect(
      sameRouteReplanRequestState(
        request(candidateId: 'candidate-1'),
        request(candidateId: 'candidate-2'),
      ),
      isFalse,
    );
  });
}

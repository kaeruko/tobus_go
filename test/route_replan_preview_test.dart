import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/logic/route_replan_preview.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/services/route_replanner.dart';
import 'package:toeigo/services/route_search_service.dart';

void main() {
  final anchorPoint = const LatLng(35.703, 139.790);
  final destinationPoint = const LatLng(35.690, 139.780);

  Candidate originalCandidate() {
    return Candidate(
      id: 'original-candidate',
      lines: const ['浅草線', '新宿線'],
      rides: 2,
      walks: 1,
      boards: 2,
      transfers: 1,
      total: 20,
      totalTime: 20,
      steps: [
        StepSeg(
          stepId: 'rail-current',
          kind: 'rail',
          title: '浅草線 青砥行',
          fromName: '浅草橋',
          toName: '東日本橋',
          departureTime: '18:00',
          arrivalTime: '18:10',
          stops: [
            StopPoint(
              name: '浅草橋',
              point: const LatLng(35.697, 139.785),
              stopId: 'asakusabashi',
            ),
            StopPoint(
              name: '蔵前',
              point: anchorPoint,
              stopId: 'kuramae',
            ),
            StopPoint(
              name: '東日本橋',
              point: const LatLng(35.692, 139.785),
              stopId: 'higashi-nihombashi',
            ),
          ],
        ),
        StepSeg(
          stepId: 'walk-transfer',
          kind: 'walk',
          title: '徒歩',
          fromName: '東日本橋',
          toName: '馬喰横山',
          departureTime: '18:10',
          arrivalTime: '18:14',
        ),
        StepSeg(
          stepId: 'rail-next',
          kind: 'rail',
          title: '新宿線 本八幡行',
          fromName: '馬喰横山',
          toName: '目的地最寄り',
          departureTime: '18:15',
          arrivalTime: '18:24',
          stops: [
            StopPoint(
              name: '馬喰横山',
              point: const LatLng(35.692, 139.782),
            ),
            StopPoint(
              name: '目的地最寄り',
              point: const LatLng(35.691, 139.781),
            ),
          ],
        ),
      ],
      points: const [],
      originName: '出発地',
      destinationName: '目的地',
      originCoords: const LatLng(35.697, 139.785),
      destinationCoords: destinationPoint,
      arrivalTime: '18:28',
    );
  }

  Trip trip(Candidate candidate) {
    return Trip(
      tripType: TripType.solo,
      id: 'trip-preview',
      joinCode: '',
      leaderId: 'user',
      title: 'test',
      travelPhase: TravelPhase.active,
      date: DateTime(2026, 8, 15),
      plannedDepartureAt: null,
      actualDepartureAt: null,
      legs: [
        Leg(
          direction: LegDirection.outbound,
          status: LegStatus.confirmed,
          candidate: candidate,
        ),
      ],
      schedule: const [],
      participants: const [],
      memberIds: const ['user'],
    );
  }

  RouteReplanRequest request({String candidateId = 'original-candidate'}) {
    return RouteReplanRequest(
      anchor: ReplanAnchor(
        placeName: '蔵前',
        stopId: 'kuramae',
        point: anchorPoint,
        availableAt: DateTime(2026, 8, 15, 18, 6),
        source: ReplanAnchorSource.predictedNextTransitPlace,
        routeStepId: 'rail-current',
      ),
      activeStepId: 'rail-current',
      originalCandidateId: candidateId,
      destination: destinationPoint,
      destinationName: '目的地',
    );
  }

  Candidate newCandidate({List<LatLng> points = const []}) {
    return Candidate(
      id: 'new-candidate',
      lines: const ['浅草線', '大江戸線'],
      rides: 2,
      walks: 1,
      boards: 2,
      transfers: 1,
      total: 18,
      totalTime: 18,
      steps: [
        StepSeg(
          stepId: 'new-rail',
          kind: 'rail',
          title: '浅草線',
          fromName: '蔵前',
          toName: '目的地最寄り',
          arrivalTime: '18:22',
          stops: [
            StopPoint(name: '蔵前', point: anchorPoint),
            StopPoint(
              name: '目的地最寄り',
              point: const LatLng(35.691, 139.781),
            ),
          ],
        ),
      ],
      points: points,
      originName: '蔵前',
      destinationName: '目的地',
      originCoords: anchorPoint,
      destinationCoords: destinationPoint,
      arrivalTime: '18:25',
    );
  }

  RouteSearchResult result(Candidate candidate) {
    return RouteSearchResult(
      candidates: [candidate],
      fareByCandidateId: const {},
      meta: RouteMeta(
        destinationReachable: true,
        destinationLabel: '目的地',
      ),
    );
  }

  test('old map starts at predicted anchor and excludes already passed stops', () {
    final preview = RouteReplanPreview.build(
      trip: trip(originalCandidate()),
      request: request(),
      result: result(newCandidate()),
    );

    expect(preview.originalFuturePoints.first, anchorPoint);
    expect(
      preview.originalFuturePoints,
      isNot(contains(const LatLng(35.697, 139.785))),
    );
    expect(preview.originalFuturePoints.last, destinationPoint);
  });

  test('new route uses API geometry and pins it to anchor and destination', () {
    final candidate = newCandidate(
      points: const [
        LatLng(35.702, 139.789),
        LatLng(35.695, 139.784),
      ],
    );
    final preview = RouteReplanPreview.build(
      trip: trip(originalCandidate()),
      request: request(),
      result: result(candidate),
    );

    final points = preview.pointsForNewCandidate(candidate);
    expect(points.first, anchorPoint);
    expect(points[1], const LatLng(35.702, 139.789));
    expect(points.last, destinationPoint);
  });

  test('candidate mismatch fails instead of comparing another route', () {
    expect(
      () => RouteReplanPreview.build(
        trip: trip(originalCandidate()),
        request: request(candidateId: 'other-candidate'),
        result: result(newCandidate()),
      ),
      throwsStateError,
    );
  });

  test('comparison labels keep route and arrival information', () {
    final candidate = newCandidate();
    expect(RouteReplanPreview.arrivalLabel(candidate), '18:25');
    expect(RouteReplanPreview.lineSummary(candidate), '浅草線 → 大江戸線');
  });
}

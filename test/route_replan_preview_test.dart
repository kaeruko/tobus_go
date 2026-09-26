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

  test('filters getting off and waiting to reboard the same current route', () {
    const anchor = LatLng(35.711078, 139.820995);
    const bridge = LatLng(35.708082, 139.817247);
    const honjo = LatLng(35.708700, 139.804000);

    final current = Candidate(
      id: 'bus-original',
      lines: const ['上２３ 上野松坂屋前行'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 30,
      totalTime: 30,
      steps: [
        StepSeg(
          stepId: 'bus-current',
          kind: 'bus',
          title: '上２３ 上野松坂屋前行',
          fromName: '平井七丁目北公園前',
          toName: '本所吾妻橋',
          routeId: '070',
          tripId: 'current-trip',
          directionId: '1',
          departureTime: '10:12',
          arrivalTime: '10:36',
          stops: [
            StopPoint(
              name: '文花三丁目',
              point: const LatLng(35.716, 139.823),
              stopId: '1383-02',
            ),
            StopPoint(
              name: '十間橋通り',
              point: anchor,
              stopId: '0752-02',
            ),
            StopPoint(
              name: '十間橋',
              point: bridge,
              stopId: '0751-02',
            ),
            StopPoint(
              name: '本所吾妻橋',
              point: honjo,
              stopId: 'honjo',
              isDestination: true,
            ),
          ],
        ),
      ],
      points: const [],
      originName: '平井七丁目北公園前',
      destinationName: '新橋',
      originCoords: const LatLng(35.73, 139.84),
      destinationCoords: destinationPoint,
      arrivalTime: '11:19',
    );

    final reboard = Candidate(
      id: 'same-bus-later',
      lines: const ['上２３ 上野松坂屋前行', '浅草線'],
      rides: 2,
      boards: 2,
      transfers: 1,
      total: 50,
      totalTime: 50,
      steps: [
        StepSeg(
          stepId: 'wait-same-bus',
          kind: 'wait',
          title: '待ち時間',
          fromName: '十間橋通り',
          toName: '十間橋通り',
          place: '十間橋通り',
          departureTime: '10:29',
          arrivalTime: '10:47',
          minutes: 18,
        ),
        StepSeg(
          stepId: 'same-bus',
          kind: 'bus',
          title: '上２３ 上野松坂屋前行',
          fromName: '十間橋通り',
          toName: '本所吾妻橋',
          routeId: '070',
          tripId: 'later-trip',
          directionId: '1',
          departureTime: '10:47',
          arrivalTime: '10:54',
          stops: [
            StopPoint(
              name: '十間橋通り',
              point: anchor,
              stopId: '0752-02',
              isOrigin: true,
            ),
            StopPoint(
              name: '十間橋',
              point: bridge,
              stopId: '0751-02',
            ),
            StopPoint(
              name: '本所吾妻橋',
              point: honjo,
              stopId: 'honjo',
              isDestination: true,
            ),
          ],
        ),
      ],
      points: const [],
      originName: '十間橋通り',
      destinationName: '新橋',
      originCoords: anchor,
      destinationCoords: destinationPoint,
      arrivalTime: '11:19',
    );

    final alternative = Candidate(
      id: 'different-route',
      lines: const ['浅草線'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 35,
      totalTime: 35,
      steps: [
        StepSeg(
          stepId: 'walk-other',
          kind: 'walk',
          title: '徒歩',
          fromName: '十間橋通り',
          toName: '押上',
          departureTime: '10:29',
          arrivalTime: '10:35',
          minutes: 6,
          meters: 480,
        ),
        StepSeg(
          stepId: 'rail-other',
          kind: 'rail',
          title: '浅草線',
          fromName: '押上',
          toName: '新橋',
          routeId: '1',
          tripId: 'rail-trip',
          departureTime: '10:37',
          arrivalTime: '10:57',
          minutes: 20,
        ),
      ],
      points: const [],
      originName: '十間橋通り',
      destinationName: '新橋',
      originCoords: anchor,
      destinationCoords: destinationPoint,
      arrivalTime: '10:57',
    );

    final busRequest = RouteReplanRequest(
      anchor: ReplanAnchor(
        placeName: '十間橋通り',
        stopId: '0752-02',
        point: anchor,
        availableAt: DateTime(2026, 8, 15, 10, 29),
        source: ReplanAnchorSource.predictedNextTransitPlace,
        routeStepId: 'bus-current',
      ),
      activeStepId: 'bus-current',
      originalCandidateId: 'bus-original',
      destination: destinationPoint,
      destinationName: '新橋',
    );

    final preview = RouteReplanPreview.build(
      trip: trip(current),
      request: busRequest,
      result: RouteSearchResult(
        candidates: [reboard, alternative],
        fareByCandidateId: const {},
        meta: RouteMeta(
          destinationReachable: true,
          destinationLabel: '新橋',
        ),
      ),
    );

    expect(
      preview.newCandidates.map((candidate) => candidate.id),
      ['different-route'],
    );
  });

  test('keeps same-route reboard when current ride does not reach its destination', () {
    const anchor = LatLng(35.711078, 139.820995);
    const honjo = LatLng(35.708700, 139.804000);

    final current = Candidate(
      id: 'short-bus-original',
      lines: const ['上２３ 上野松坂屋前行'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 10,
      totalTime: 10,
      steps: [
        StepSeg(
          stepId: 'short-bus-current',
          kind: 'bus',
          title: '上２３ 上野松坂屋前行',
          fromName: '文花三丁目',
          toName: '十間橋',
          routeId: '070',
          directionId: '1',
          stops: [
            StopPoint(
              name: '十間橋通り',
              point: anchor,
              stopId: '0752-02',
            ),
            StopPoint(
              name: '十間橋',
              point: const LatLng(35.708082, 139.817247),
              stopId: '0751-02',
              isDestination: true,
            ),
          ],
        ),
      ],
      points: const [],
      originName: '文花三丁目',
      destinationName: '新橋',
      originCoords: const LatLng(35.716, 139.823),
      destinationCoords: destinationPoint,
    );

    final neededReboard = Candidate(
      id: 'same-route-needed',
      lines: const ['上２３ 上野松坂屋前行'],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 20,
      totalTime: 20,
      steps: [
        StepSeg(
          stepId: 'same-route-needed-step',
          kind: 'bus',
          title: '上２３ 上野松坂屋前行',
          fromName: '十間橋通り',
          toName: '本所吾妻橋',
          routeId: '070',
          directionId: '1',
          stops: [
            StopPoint(
              name: '十間橋通り',
              point: anchor,
              stopId: '0752-02',
              isOrigin: true,
            ),
            StopPoint(
              name: '本所吾妻橋',
              point: honjo,
              stopId: 'honjo',
              isDestination: true,
            ),
          ],
        ),
      ],
      points: const [],
      originName: '十間橋通り',
      destinationName: '新橋',
      originCoords: anchor,
      destinationCoords: destinationPoint,
    );

    final busRequest = RouteReplanRequest(
      anchor: ReplanAnchor(
        placeName: '十間橋通り',
        stopId: '0752-02',
        point: anchor,
        availableAt: DateTime(2026, 8, 15, 10, 29),
        source: ReplanAnchorSource.predictedNextTransitPlace,
        routeStepId: 'short-bus-current',
      ),
      activeStepId: 'short-bus-current',
      originalCandidateId: 'short-bus-original',
      destination: destinationPoint,
      destinationName: '新橋',
    );

    final preview = RouteReplanPreview.build(
      trip: trip(current),
      request: busRequest,
      result: result(neededReboard),
    );

    expect(preview.newCandidates.single.id, 'same-route-needed');
  });

  test('comparison labels keep route and arrival information', () {
    final candidate = newCandidate();
    expect(RouteReplanPreview.arrivalLabel(candidate), '18:25');
    expect(RouteReplanPreview.lineSummary(candidate), '浅草線 → 大江戸線');
  });
}

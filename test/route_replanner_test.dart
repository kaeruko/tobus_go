import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/services/route_replanner.dart';
import 'package:toeigo/services/route_search_service.dart';

void main() {
  Candidate candidate({
    String id = 'candidate-1',
    String? destinationName = '目的地',
    LatLng? destinationCoords = const LatLng(35.70, 139.80),
    String? preference = 'shortTime',
  }) {
    return Candidate(
      id: id,
      lines: const ['浅草線'],
      rides: 1,
      walks: 1,
      boards: 1,
      transfers: 0,
      total: 20,
      totalTime: 20,
      steps: [
        StepSeg(
          stepId: 'rail-1',
          kind: 'rail',
          title: '浅草線',
          fromName: '浅草橋',
          toName: '東日本橋',
        ),
      ],
      points: const [],
      originName: '出発地',
      destinationName: destinationName,
      originCoords: const LatLng(35.69, 139.78),
      destinationCoords: destinationCoords,
      preference: preference,
    );
  }

  Trip trip(Candidate candidate) {
    return Trip(
      id: 'trip-1',
      joinCode: '',
      leaderId: 'leader',
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
      memberIds: const [],
    );
  }

  ReplanAnchor anchor({
    String? routeStepId = 'rail-1',
    DateTime? availableAt,
  }) {
    return ReplanAnchor(
      placeName: '蔵前',
      stopId: 'station-kuramae',
      point: const LatLng(35.703, 139.790),
      availableAt: availableAt ?? DateTime(2026, 8, 15, 18, 6),
      source: ReplanAnchorSource.predictedNextTransitPlace,
      routeStepId: routeStepId,
    );
  }

  RouteReplanRequest requestAt(DateTime availableAt) {
    return RouteReplanRequestBuilder.build(
      trip: trip(candidate()),
      activeStepId: 'rail-1',
      anchor: anchor(availableAt: availableAt),
    );
  }

  test('builds a replan request for the candidate containing the active step', () {
    final request = RouteReplanRequestBuilder.build(
      trip: trip(candidate()),
      activeStepId: 'rail-1',
      anchor: anchor(),
    );

    expect(request.originalCandidateId, 'candidate-1');
    expect(request.destinationName, '目的地');
    expect(request.destination, const LatLng(35.70, 139.80));
    expect(request.preference, 'shortTime');
    expect(request.anchor.placeName, '蔵前');
  });

  test('replanner searches from anchor point at anchor availableAt', () async {
    final fake = _FakeRouteSearchService();
    final replanner = RouteReplanner(fake);
    final request = RouteReplanRequestBuilder.build(
      trip: trip(candidate()),
      activeStepId: 'rail-1',
      anchor: anchor(),
    );

    await replanner.replan(request);

    final search = fake.lastRequest!;
    expect(search.origin, const LatLng(35.703, 139.790));
    expect(search.originName, '蔵前');
    expect(search.destination, const LatLng(35.70, 139.80));
    expect(search.destinationName, '目的地');
    expect(search.startTime, DateTime(2026, 8, 15, 18, 6));
    expect(search.preference, 'shortTime');
  });

  test('route API body uses the device local clock for an absolute UTC time', () {
    final utcStart = DateTime.utc(2026, 8, 15, 9, 6);
    final localStart = utcStart.toLocal();
    final request = RouteSearchRequest(
      origin: const LatLng(35.703, 139.790),
      destination: const LatLng(35.70, 139.80),
      originName: '蔵前',
      destinationName: '目的地',
      startTime: utcStart,
      preference: 'shortTime',
    );

    final body = request.toApiBody();
    final expectedClock =
        '${localStart.hour.toString().padLeft(2, '0')}:'
        '${localStart.minute.toString().padLeft(2, '0')}';
    final expectedDate =
        '${localStart.year.toString().padLeft(4, '0')}-'
        '${localStart.month.toString().padLeft(2, '0')}-'
        '${localStart.day.toString().padLeft(2, '0')}';

    expect(body['start_time'], expectedClock);
    expect(body['target_date_str'], expectedDate);
    expect(body['pref'], 'time');
  });

  test('request stays current when availableAt changes only within API minute', () {
    final first = requestAt(DateTime.utc(2026, 8, 15, 9, 10, 3, 100));
    final later = requestAt(DateTime.utc(2026, 8, 15, 9, 10, 53, 900));

    expect(sameRouteReplanRequestState(first, later), isTrue);
    expect(first.anchor.availableAt, isNot(later.anchor.availableAt));
    expect(
      RouteSearchRequest(
        origin: first.anchor.point,
        destination: first.destination,
        originName: first.anchor.placeName,
        destinationName: first.destinationName,
        startTime: first.anchor.availableAt,
        preference: first.preference,
      ).toApiBody()['start_time'],
      RouteSearchRequest(
        origin: later.anchor.point,
        destination: later.destination,
        originName: later.anchor.placeName,
        destinationName: later.destinationName,
        startTime: later.anchor.availableAt,
        preference: later.preference,
      ).toApiBody()['start_time'],
    );
  });

  test('request becomes stale when availableAt crosses API minute', () {
    final first = requestAt(DateTime.utc(2026, 8, 15, 9, 10, 53));
    final nextMinute = requestAt(DateTime.utc(2026, 8, 15, 9, 11, 13));

    expect(sameRouteReplanRequestState(first, nextMinute), isFalse);
  });

  test('fails when a riding anchor belongs to another step', () {
    expect(
      () => RouteReplanRequestBuilder.build(
        trip: trip(candidate()),
        activeStepId: 'rail-1',
        anchor: anchor(routeStepId: 'rail-other'),
      ),
      throwsStateError,
    );
  });

  test('fails instead of guessing a missing destination coordinate', () {
    expect(
      () => RouteReplanRequestBuilder.build(
        trip: trip(candidate(destinationCoords: null)),
        activeStepId: 'rail-1',
        anchor: anchor(),
      ),
      throwsStateError,
    );
  });

  test('route preference normalization remains shared with normal search', () {
    expect(normalizeRoutePreferenceForApi('shortTime'), 'time');
    expect(normalizeRoutePreferenceForApi('fewTransfers'), 'fewTransfers');
    expect(normalizeRoutePreferenceForApi(null), 'cost');
  });
}

class _FakeRouteSearchService implements RouteSearchService {
  RouteSearchRequest? lastRequest;

  @override
  Future<RouteSearchResult> search(RouteSearchRequest request) async {
    lastRequest = request;
    return RouteSearchResult(
      candidates: const [],
      fareByCandidateId: const {},
      meta: RouteMeta(
        destinationReachable: true,
        destinationLabel: '目的地',
      ),
    );
  }
}

import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  test('StepSeg serialization with coordinates', () {
    final Map<String, dynamic> stepJson = {
      "step_id": "bus-1",
      "kind": "bus",
      "title": "Bus 1",
      "edges": 1,
      "stops": [
        {"name": "Stop 1", "lat": 35.123, "lon": 139.123, "is_origin": true},
        {"name": "Stop 2", "lat": 35.124, "lon": 139.124},
      ],
    };

    final step = StepSeg.fromJson(stepJson);
    expect(step.stops.length, 2);
    expect(step.stops[0].lat, 35.123);

    // To Json
    final json = step.toJson();
    final stopsJson = json['stops'] as List;
    expect(stopsJson[0]['lat'], 35.123);
  });

  test('StepSeg preserves explicit boarding time', () {
    final step = StepSeg.fromJson({
      'step_id': 'rail-1',
      'kind': 'rail',
      'title': '浅草線',
      'boarding_minutes': 2,
    });

    expect(step.boardingMinutes, 2);
    expect(step.toJson()['boarding_minutes'], 2);
  });

  test('StepSeg rejects invalid explicit boarding time', () {
    expect(
      () => StepSeg.fromJson({
        'step_id': 'rail-invalid',
        'kind': 'rail',
        'title': '浅草線',
        'boarding_minutes': 1.5,
      }),
      throwsFormatException,
    );
  });

  test('Trip serialization flow', () {
    final Map<String, dynamic> candidateJson = {
      "id": "c1",
      "lines": ["L1"],
      "walking_distance_meters": 0,
      "walking_segment_count": 0,
      "steps": [
        {
          "step_id": "bus-1",
          "kind": "bus",
          "title": "Bus 1",
          "edges": 1,
          "stops": [
            {"name": "Stop 1", "lat": 35.123, "lon": 139.123},
          ],
        },
      ],
    };

    final candidate = Candidate.fromJson(candidateJson);
    final leg = Leg(
      direction: LegDirection.outbound,
      status: LegStatus.confirmed,
      candidate: candidate,
    );

    // Simulate Trip.toFirestore
    final tripMap = {
      'legs': [leg.toJson(includePoints: false)],
    };

    // Simulate reading back
    final legData = tripMap['legs'] as List;
    final legRead = Leg.fromJson(legData[0]);

    expect(legRead.candidate.steps[0].stops[0].lat, 35.123);
  });

  test('Candidate preserves bilingual endpoint names', () {
    final candidate = Candidate(
      id: 'bilingual-endpoints',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 1,
      totalTime: 1,
      steps: const [],
      points: const [],
      originName: '押上',
      destinationName: '上野駅',
      originNameEn: 'Oshiage',
      destinationNameEn: 'Ueno Station',
    );

    final restored = Candidate.fromJson(candidate.toJson());

    expect(restored.originName, '押上');
    expect(restored.destinationName, '上野駅');
    expect(restored.originNameEn, 'Oshiage');
    expect(restored.destinationNameEn, 'Ueno Station');
  });

  test('Candidate keeps favorite memo only in local-storage serialization', () {
    final candidate = Candidate(
      id: 'favorite-memo',
      lines: const [],
      rides: 0,
      boards: 0,
      transfers: 0,
      total: 1,
      totalTime: 1,
      steps: const [],
      points: const [],
    ).withSavedRouteMemo('雨の日はこの経路');

    final regularJson = candidate.toJson();
    expect(regularJson.containsKey('saved_route_memo'), isFalse);

    final storageJson = candidate.toJson(includeSavedRouteMemo: true);
    expect(storageJson['saved_route_memo'], '雨の日はこの経路');

    final restored = Candidate.fromJson(storageJson);
    expect(restored.savedRouteMemo, '雨の日はこの経路');

    final cleared = restored.withSavedRouteMemo(null);
    expect(cleared.savedRouteMemo, isNull);
  });

  test('StepSeg rejects a route response without step_id', () {
    expect(
      () => StepSeg.fromJson({'kind': 'walk', 'title': '徒歩'}),
      throwsFormatException,
    );
  });

  test('Candidate rejects ambiguous or inconsistent walking metrics', () {
    final base = <String, dynamic>{
      'id': 'walk-metrics',
      'lines': const <String>[],
      'walking_distance_meters': 120,
      'walking_segment_count': 1,
      'steps': [
        {
          'step_id': 'walk-1',
          'kind': 'walk',
          'title': '徒歩',
          'meters': 120,
        },
      ],
    };

    expect(Candidate.fromJson(base).walkingDistanceMeters, 120);
    expect(
      () => Candidate.fromJson({...base}..remove('walking_distance_meters')),
      throwsFormatException,
    );
    expect(
      () => Candidate.fromJson({...base, 'walking_segment_count': 2}),
      throwsStateError,
    );
  });

  test('Firestore leg persistence rejects unresolved rail identity', () {
    Candidate railCandidate({String? tripId, String? routeId}) {
      return Candidate(
        id: 'rail-persistence',
        lines: const ['浅草線'],
        rides: 1,
        boards: 1,
        transfers: 0,
        total: 10,
        totalTime: 10,
        steps: [
          StepSeg(
            stepId: 'rail-1',
            kind: 'rail',
            title: '浅草線',
            tripId: tripId,
            routeId: routeId,
          ),
        ],
        points: const [],
      );
    }

    Leg leg(Candidate candidate) => Leg(
      direction: LegDirection.inbound,
      status: LegStatus.confirmed,
      candidate: candidate,
    );

    expect(
      () => leg(railCandidate(routeId: '1')).toFirestore(),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('GTFS tripId'),
        ),
      ),
    );
    expect(
      () => leg(railCandidate(tripId: '121603T0')).toFirestore(),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('GTFS routeId'),
        ),
      ),
    );
    expect(
      () => leg(
        railCandidate(tripId: '121603T0', routeId: '1'),
      ).toFirestore(),
      returnsNormally,
    );
  });

  test('Trip rejects schemas other than navigation v2', () {
    expect(
      () => Trip(
        schemaVersion: 1,
        id: 'old-trip',
        joinCode: '123456',
        leaderId: 'leader',
        title: 'Old trip',
        travelPhase: TravelPhase.planning,
        date: DateTime(2025),
        plannedDepartureAt: null,
        actualDepartureAt: null,
        legs: const [],
        schedule: const [],
        participants: const [],
        memberIds: const [],
      ),
      throwsStateError,
    );
  });
}

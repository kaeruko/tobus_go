import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/solo_trip_factory.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  Candidate candidate() => Candidate.fromJson({
    ...navigationV2Candidate().toJson(),
    'points': [
      [35.1, 139.1],
      [35.123456789, 139.234567891], // A bend that is not a stop.
      [35.4, 139.4],
    ],
    'origin_coords': [35.09, 139.09],
    'destination_coords': [35.41, 139.41],
  });

  void expectNoNestedArrays(dynamic value) {
    if (value is List) {
      for (final item in value) {
        expect(item, isNot(isA<List>()));
        expectNoNestedArrays(item);
      }
    } else if (value is Map) {
      for (final item in value.values) {
        expectNoNestedArrays(item);
      }
    }
  }

  test('Trip persistence retains all geometry without nested arrays', () {
    final route = candidate();
    final trip = buildSoloTrip(
      id: 'solo', userId: 'user', userName: 'User',
      candidate: route, now: DateTime(2026, 9, 28),
    );
    final document = trip.toFirestore();
    expectNoNestedArrays(document);
    final persistedLeg = (document['legs'] as List).single as Map<String, dynamic>;
    expect((persistedLeg['candidate'] as Map)['points'], isEmpty);
    final restored = Leg.fromJson(persistedLeg);
    expect(restored.candidate.points, route.points);
    expect(restored.routeGeometryIsApproximate, isFalse);
    expect(Leg.fromJson(restored.toFirestore()).candidate.points, route.points);
  });

  test('legacy reconstruction stays explicitly approximate after saving', () {
    final legacy = Leg.fromJson({
      'candidate': candidate().toJson(includePoints: false),
    });
    expect(legacy.routeGeometryIsApproximate, isTrue);
    expect(legacy.candidate.points.first, const LatLng(35.09, 139.09));
    expect(legacy.candidate.points.last, const LatLng(35.41, 139.41));
    expect(legacy.candidate.points, isNot(contains(const LatLng(35.123456789, 139.234567891))));
    expect(Leg.fromJson(legacy.toFirestore()).routeGeometryIsApproximate, isTrue);
    expect(Leg.fromJson(legacy.toJson()).routeGeometryIsApproximate, isTrue);
  });

  test('an explicitly empty saved geometry is not silently reconstructed', () {
    final leg = Leg.fromJson({
      'candidate': candidate().toJson(includePoints: false),
      'routePoints': <double>[],
    });
    expect(leg.candidate.points, isEmpty);
    expect(leg.routeGeometryIsApproximate, isFalse);
  });

  test('malformed persisted geometry fails without legacy fallback', () {
    for (final invalid in [null, 'invalid', [35.0], [35, '139'], [91, 139], [35, 181], [double.nan, 139]]) {
      expect(() => Leg.fromJson({
        'candidate': candidate().toJson(),
        'routePoints': invalid,
      }), throwsFormatException, reason: '$invalid');
    }
    expect(() => Leg.fromJson({
      'candidate': candidate().toJson(),
      'routeGeometryIsApproximate': 'true',
    }), throwsFormatException);
  });
}

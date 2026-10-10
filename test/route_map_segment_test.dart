import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/models/route_models.dart';

Map<String, dynamic> baseCandidate() => {
  'id': 'tokyo-geometry',
  'lines': ['上23'],
  'rides': 1,
  'boards': 1,
  'transfers': 0,
  'total': 15,
  'total_time': 15,
  'walking_distance_meters': 0,
  'walking_segment_count': 0,
  'steps': [],
  'points': [
    [35.0, 139.0],
    [35.005, 139.005],
    [35.01, 139.01],
  ],
  'arrival_time': '10:15',
};

void main() {
  test('route leg geometry retains correct modes and endpoint coordinates', () {
    final input = baseCandidate()..['route_geometry'] = [
      {
        'kind': 'walk',
        'points': [[35.0, 139.0], [35.005, 139.005]],
      },
      {
        'kind': 'bus',
        'points': [[35.005, 139.005], [35.01, 139.01]],
      },
    ];
    final route = Candidate.fromJson(input);
    expect(route.routeGeometry, hasLength(2));
    expect(route.routeGeometry!.first.kind, 'walk');
    expect(route.routeGeometry!.last.kind, 'bus');
    expect(route.routeGeometry!.last.points.last,
        const LatLng(35.01, 139.01));

    final restored = Candidate.fromJson(route.toJson());
    expect(restored.routeGeometry![0].points,
        route.routeGeometry![0].points);
    expect(restored.routeGeometry![1].kind, 'bus');
    expect(route.toJson(includePoints: false).containsKey('route_geometry'), isFalse);
  });

  test('older/other-city candidates remain explicitly unsegmented', () {
    final route = Candidate.fromJson(baseCandidate());
    expect(route.routeGeometry, isNull);
    expect(route.toJson().containsKey('route_geometry'), isFalse);
  });

  test('malformed provided geometry must not fall back to untyped line', () {
    for (final invalid in [
      null,
      'not a list',
      [{'kind': 'hover', 'points': [[35.0, 139.0], [35.001, 139.0]]}],
      [{'kind': 'walk', 'points': [[35.0, 139.0]]}],
      [{'kind': 'walk', 'points': [[0.0, 0.0], [35.001, 139.0]]}],
      [{'kind': 'rail', 'points': [[35.0, 139.0], ['bad', 139.0]]}],
    ]) {
      final input = baseCandidate()..['route_geometry'] = invalid;
      expect(() => Candidate.fromJson(input), throwsFormatException,
          reason: 'invalid value: $invalid');
    }
  });
}

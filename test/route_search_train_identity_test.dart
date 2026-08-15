import 'dart:convert';

import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/route_search_service.dart';

void main() {
  late http.Client originalClient;

  setUp(() {
    originalClient = ApiClient.httpClient;
  });

  tearDown(() {
    ApiClient.httpClient = originalClient;
  });

  RouteSearchRequest request() => RouteSearchRequest(
    origin: const LatLng(35.69, 139.78),
    destination: const LatLng(35.71, 139.80),
    originName: '東日本橋',
    destinationName: '蔵前',
    startTime: DateTime(2026, 8, 15, 16, 0),
  );

  Map<String, dynamic> railCandidate({
    String? tripId,
    String? routeId,
  }) => {
    'id': 'Fastest',
    'lines': ['浅草線'],
    'rides': 1,
    'walks': 0,
    'boards': 1,
    'transfers': 0,
    'total': 1,
    'total_time': 10,
    'steps': [
      {
        'step_id': 'rail-1',
        'kind': 'rail',
        'title': '浅草線',
        'from_': '東日本橋',
        'to': '蔵前',
        'minutes': 5,
        'meters': 0,
        'departure_time': '16:25',
        'arrival_time': '16:30',
        'route_id': routeId,
        'trip_id': tripId,
        'stops': [
          {
            'name': '東日本橋',
            'lat': 35.69,
            'lon': 139.78,
            'id': 'odpt.Station:Toei.Asakusa.HigashiNihombashi',
          },
          {
            'name': '浅草橋',
            'lat': 35.70,
            'lon': 139.79,
            'id': 'odpt.Station:Toei.Asakusa.Asakusabashi',
          },
          {
            'name': '蔵前',
            'lat': 35.71,
            'lon': 139.80,
            'id': 'odpt.Station:Toei.Asakusa.Kuramae',
          },
        ],
      },
    ],
    'points': [],
  };

  Map<String, dynamic> meta() => {
    'destination_reachable': true,
    'destination_label': '目的地',
    'walk_limit_m': 1000,
  };

  test('rail candidates are resolved to exact trip_id before parsing', () async {
    final calls = <String>[];
    ApiClient.httpClient = MockClient((request) async {
      calls.add(request.url.path);
      if (request.url.path == '/route') {
        return http.Response(
          jsonEncode({
            'candidates': [railCandidate()],
            'meta': meta(),
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path == '/train/resolve-route-identities') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['target_date_str'], '2026-08-15');
        return http.Response(
          jsonEncode({
            'candidates': [
              railCandidate(tripId: '121603T0', routeId: '1'),
            ],
            'rejections': [],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('not found', 404);
    });

    final result = await const ApiRouteSearchService().search(request());

    expect(calls, ['/route', '/train/resolve-route-identities']);
    expect(result.candidates, hasLength(1));
    expect(result.candidates.single.steps.single.tripId, '121603T0');
    expect(result.candidates.single.steps.single.routeId, '1');
  });

  test('all rejected rail identities fail instead of falling back', () async {
    ApiClient.httpClient = MockClient((request) async {
      if (request.url.path == '/route') {
        return http.Response(
          jsonEncode({
            'candidates': [railCandidate()],
            'meta': meta(),
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path == '/train/resolve-route-identities') {
        return http.Response(
          jsonEncode({
            'candidates': [],
            'rejections': [
              {
                'candidate_id': 'Fastest',
                'code': 'rail_static_trip_ambiguous',
                'message': 'multiple exact static trips',
              },
            ],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('not found', 404);
    });

    await expectLater(
      const ApiRouteSearchService().search(request()),
      throwsA(
        isA<StateError>().having(
          (error) => error.message,
          'message',
          contains('rail_static_trip_ambiguous'),
        ),
      ),
    );
  });
}

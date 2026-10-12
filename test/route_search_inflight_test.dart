import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/route_search_service.dart';

RouteSearchRequest _request({
  LatLng origin = const LatLng(35.69, 139.78),
  LatLng destination = const LatLng(35.71, 139.80),
  String originName = '始点',
  String destinationName = '終点',
  String? originNameEn = 'Origin',
  String? destinationNameEn = 'Destination',
  DateTime? startTime,
  String? preference = 'fewTransfers',
  bool busOnly = false,
}) => RouteSearchRequest(
  origin: origin,
  destination: destination,
  originName: originName,
  destinationName: destinationName,
  originNameEn: originNameEn,
  destinationNameEn: destinationNameEn,
  startTime: startTime ?? DateTime(2026, 10, 12, 10),
  preference: preference,
  busOnly: busOnly,
);

Map<String, dynamic> _railCandidate({String? tripId, String? routeId}) => {
  'id': 'rail-route',
  'lines': ['fixture rail'],
  'rides': 1,
  'walking_distance_meters': 0,
  'walking_segment_count': 0,
  'boards': 1,
  'transfers': 0,
  'total': 1,
  'total_time': 5,
  'steps': [
    {
      'step_id': 'rail-step',
      'kind': 'rail',
      'title': 'fixture rail',
      'from_': '始点',
      'to': '終点',
      'minutes': 5,
      'meters': 0,
      'departure_time': '10:00',
      'arrival_time': '10:05',
      'boarding_minutes': 2,
      'trip_id': tripId,
      'route_id': routeId,
      'stops': [
        {'id': 'stop-a', 'name': '始点', 'lat': 35.69, 'lon': 139.78},
        {'id': 'stop-b', 'name': '終点', 'lat': 35.71, 'lon': 139.80},
      ],
    },
  ],
  'points': [],
};

http.Response _response(Map<String, dynamic> body, {int status = 200}) =>
    http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

http.Response _routeResponse({bool rail = false}) => _response({
  'candidates': rail ? [_railCandidate()] : [],
  'meta': {'destination_reachable': true, 'destination_label': '終点'},
});

Future<void> _settleHttp() => Future<void>.delayed(Duration.zero);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late http.Client originalClient;

  setUp(() {
    originalClient = ApiClient.httpClient;
    configureApiBase(Uri.parse('https://inflight.example.test'));
  });

  tearDown(() {
    ApiClient.httpClient = originalClient;
  });

  test(
    'identical searches share route and identity work until completion',
    () async {
      final routeGate = Completer<void>();
      final identityGate = Completer<void>();
      var routeCalls = 0;
      var identityCalls = 0;
      ApiClient.httpClient = MockClient((request) async {
        if (request.url.path == '/route') {
          routeCalls++;
          await routeGate.future;
          return _routeResponse(rail: true);
        }
        identityCalls++;
        await identityGate.future;
        return _response({
          'candidates': [
            _railCandidate(tripId: 'trip-$routeCalls', routeId: 'line-1'),
          ],
          'rejections': [],
        });
      });

      final first = const ApiRouteSearchService().search(_request());
      final second = const ApiRouteSearchService().search(_request());
      await _settleHttp();
      expect(routeCalls, 1);
      routeGate.complete();
      await _settleHttp();
      expect(identityCalls, 1);

      // Sharing must remain active while the second HTTP request is unfinished.
      final third = const ApiRouteSearchService().search(_request());
      await _settleHttp();
      expect(routeCalls, 1);
      expect(identityCalls, 1);
      identityGate.complete();
      final results = await Future.wait([first, second, third]);
      expect(results, hasLength(3));
      for (final result in results) {
        expect(result.candidates.single.steps.single.tripId, 'trip-1');
        expect(result.candidates.single.originName, '始点');
        expect(result.candidates.single.destinationNameEn, 'Destination');
      }

      // A manual refresh after completion obtains new data, even in this minute.
      final refreshed = await const ApiRouteSearchService().search(_request());
      expect(routeCalls, 2);
      expect(identityCalls, 2);
      expect(refreshed.candidates.single.steps.single.tripId, 'trip-2');
    },
  );

  test(
    'normalized API minute preference and trimmed names can share',
    () async {
      final gate = Completer<void>();
      var routeCalls = 0;
      ApiClient.httpClient = MockClient((request) async {
        routeCalls++;
        await gate.future;
        return _routeResponse();
      });
      final first = const ApiRouteSearchService().search(
        _request(
          preference: 'shortTime',
          originName: ' 始点 ',
          destinationName: ' 終点 ',
          originNameEn: ' Origin ',
          destinationNameEn: ' Destination ',
          startTime: DateTime(2026, 10, 12, 10, 0, 1),
        ),
      );
      final second = const ApiRouteSearchService().search(
        _request(
          preference: 'time',
          startTime: DateTime(2026, 10, 12, 10, 0, 59).toUtc(),
        ),
      );
      await _settleHttp();
      expect(routeCalls, 1);
      gate.complete();
      await Future.wait([first, second]);
    },
  );

  final differentRequests = <String, RouteSearchRequest Function()>{
    'departure minute': () =>
        _request(startTime: DateTime(2026, 10, 12, 10, 1)),
    'service date': () => _request(startTime: DateTime(2026, 10, 13, 10)),
    'preference': () => _request(preference: 'shortTime'),
    'transport mode': () => _request(busOnly: true),
    'origin coordinate': () => _request(origin: const LatLng(35.68, 139.78)),
    'destination coordinate': () =>
        _request(destination: const LatLng(35.72, 139.80)),
    'origin name': () => _request(originName: '別の始点名'),
    'destination name': () => _request(destinationName: '別の終点名'),
    'English origin name': () => _request(originNameEn: 'Other origin'),
    'English destination name': () =>
        _request(destinationNameEn: 'Other destination'),
  };
  for (final entry in differentRequests.entries) {
    test(
      'concurrent searches with different ${entry.key} stay distinct',
      () async {
        final gate = Completer<void>();
        var routeCalls = 0;
        ApiClient.httpClient = MockClient((request) async {
          routeCalls++;
          await gate.future;
          return _routeResponse();
        });
        final first = const ApiRouteSearchService().search(_request());
        final different = const ApiRouteSearchService().search(entry.value());
        await _settleHttp();
        expect(routeCalls, 2);
        gate.complete();
        await Future.wait([first, different]);
      },
    );
  }

  test(
    'concurrent searches with different API endpoints stay distinct',
    () async {
      final gate = Completer<void>();
      final hosts = <String>[];
      ApiClient.httpClient = MockClient((request) async {
        hosts.add(request.url.host);
        await gate.future;
        return _routeResponse();
      });
      final first = const ApiRouteSearchService().search(_request());
      configureApiBase(Uri.parse('https://other-inflight.example.test'));
      final second = const ApiRouteSearchService().search(_request());
      await _settleHttp();
      expect(hosts, ['inflight.example.test', 'other-inflight.example.test']);
      gate.complete();
      await Future.wait([first, second]);
    },
  );

  for (final failure in [
    'route HTTP',
    'identity HTTP',
    'route parsing',
    'identity parsing',
  ]) {
    test('$failure failure is shared and removed so retry is fresh', () async {
      final gate = Completer<void>();
      var fail = true;
      var routeCalls = 0;
      var identityCalls = 0;
      final needsIdentity = failure.startsWith('identity');
      ApiClient.httpClient = MockClient((request) async {
        if (request.url.path == '/route') {
          routeCalls++;
          if (!needsIdentity) await gate.future;
          if (fail && failure == 'route HTTP') {
            return _response({'detail': 'route failed'}, status: 500);
          }
          if (fail && failure == 'route parsing') {
            return _response({
              'meta': {'destination_reachable': true},
            });
          }
          return _routeResponse(rail: needsIdentity);
        }
        identityCalls++;
        await gate.future;
        if (fail && failure == 'identity HTTP') {
          return _response({'detail': 'identity failed'}, status: 500);
        }
        final resolved = _railCandidate(tripId: 'trip-1', routeId: 'line-1');
        if (fail && failure == 'identity parsing') {
          return _response({
            'candidates': [resolved],
          });
        }
        return _response({
          'candidates': [resolved],
          'rejections': [],
        });
      });
      final first = const ApiRouteSearchService().search(_request());
      final second = const ApiRouteSearchService().search(_request());
      final expectedError = failure.endsWith('HTTP')
          ? isA<ApiException>()
          : isA<FormatException>();
      final errorsObserved = Future.wait([
        expectLater(first, throwsA(expectedError)),
        expectLater(second, throwsA(expectedError)),
      ]);
      await _settleHttp();
      expect(routeCalls, 1);
      expect(identityCalls, needsIdentity ? 1 : 0);
      gate.complete();
      await errorsObserved;

      fail = false;
      final result = await const ApiRouteSearchService().search(_request());
      expect(routeCalls, 2);
      expect(identityCalls, needsIdentity ? 2 : 0);
      expect(result.candidates, needsIdentity ? hasLength(1) : isEmpty);
    });
  }
}

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/bus_location_source.dart';

void main() {
  group('ApiClient.fetchBusLocation', () {
    late http.Client originalClient;

    setUp(() {
      originalClient = ApiClient.httpClient;
    });

    tearDown(() {
      ApiClient.httpClient = originalClient;
    });

    test('throws when backend returns an error', () async {
      ApiClient.httpClient = MockClient((request) async {
        return http.Response('Server error', 500);
      });

      expect(
        ApiClient.fetchBusLocation(routeId: 'route-id', tripId: 'trip-id'),
        throwsException,
      );
    });

    test('preserves the backend error code', () async {
      ApiClient.httpClient = MockClient((request) async {
        return http.Response(
          '{"detail":{"code":"bus_trip_not_found","message":"not live yet"}}',
          404,
        );
      });

      expect(
        ApiClient.fetchBusLocation(routeId: 'route-id', tripId: 'trip-id'),
        throwsA(
          isA<ApiException>()
              .having((error) => error.statusCode, 'statusCode', 404)
              .having((error) => error.code, 'code', 'bus_trip_not_found'),
        ),
      );
    });

    test('treats a missing realtime vehicle as waiting for the bus', () async {
      ApiClient.httpClient = MockClient((request) async {
        return http.Response(
          '{"detail":{"code":"bus_trip_not_found","message":"not live yet"}}',
          404,
        );
      });

      expect(
        const RealtimeBusLocationSource().fetch(
          routeId: 'route-id',
          tripId: 'trip-id',
        ),
        throwsA(isA<BusLocationNotAvailableException>()),
      );
    });
  });
}

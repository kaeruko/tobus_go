import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:toeigo/core/api_client.dart';

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
  });
}

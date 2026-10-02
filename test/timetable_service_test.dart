import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/timetable_service.dart';

void main() {
  test('next bus request sends the device reference date and time', () async {
    final originalClient = ApiClient.httpClient;
    configureApiBase(Uri.parse('https://api.example.test'));

    ApiClient.httpClient = MockClient((request) async {
      expect(request.url.path, '/bus/next');
      expect(request.url.queryParameters['pole_id'], 'stop-a');
      expect(request.url.queryParameters['route_id'], 'route-a');
      expect(request.url.queryParameters['target_pole_id'], 'stop-b');
      expect(request.url.queryParameters['date'], '2026-10-02');
      expect(request.url.queryParameters['time'], '10:46');
      return http.Response(
        '{"destinations":[{"destination_pole_id":"stop-b",'
        '"destination_name":"新橋",'
        '"times":["10:50","11:05"]}]}',
        200,
        headers: const {'content-type': 'application/json; charset=utf-8'},
      );
    });
    addTearDown(() => ApiClient.httpClient = originalClient);

    final groups = await TimetableService().getNextBusesFromApi(
      'route-a',
      'stop-a',
      targetPoleId: 'stop-b',
      referenceTime: DateTime(2026, 10, 2, 10, 46),
    );

    expect(groups.single['times'], ['10:50', '11:05']);
  });

  test('full-day request uses day type and omits date selector', () async {
    final originalClient = ApiClient.httpClient;
    configureApiBase(Uri.parse('https://api.example.test'));

    ApiClient.httpClient = MockClient((request) async {
      expect(request.url.queryParameters['day_type'], 'weekday');
      expect(request.url.queryParameters.containsKey('date'), isFalse);
      expect(request.url.queryParameters['time'], '10:46');
      expect(request.url.queryParameters['include_all'], 'true');
      return http.Response(
        '{"destinations":[{"destination_pole_id":"stop-b",'
        '"destination_name":"新橋",'
        '"times":["10:50"],'
        '"all_times":["06:59","07:14","10:50"]}]}',
        200,
        headers: const {'content-type': 'application/json; charset=utf-8'},
      );
    });
    addTearDown(() => ApiClient.httpClient = originalClient);

    final groups = await TimetableService().getNextBusesFromApi(
      'route-a',
      'stop-a',
      targetPoleId: 'stop-b',
      dayType: 'Weekday',
      referenceTime: DateTime(2026, 10, 2, 10, 46),
      includeAllDay: true,
    );

    expect(groups.single['times'], ['10:50']);
    expect(groups.single['allTimes'], ['06:59', '07:14', '10:50']);
  });
}

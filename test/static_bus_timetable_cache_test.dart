import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/timetable_service.dart';

const _fullDayResponse = '{'
    '"day_type":"weekday","destinations":['
    '{"destination_pole_id":"stop-b",'
    '"destination_name":"平井駅前",'
    '"destination_name_en":"Hirai Station",'
    '"times":["15:37","16:08"],'
    '"all_times":["06:12","15:37","16:08","16:37","25:10"]}'
    ']}';

void main() {
  setUp(() {
    configureApiBase(Uri.parse('https://api-static.example.test'));
    SharedPreferences.setMockInitialValues({});
  });

  test('fixed full-day schedule is persisted and next times move without HTTP', () async {
    final previous = ApiClient.httpClient;
    var requests = 0;
    ApiClient.httpClient = MockClient((request) async {
      requests++;
      expect(request.url.path, '/bus/next');
      expect(request.url.queryParameters['include_all'], 'true');
      expect(request.url.queryParameters['date'], '2026-10-15');
      return http.Response(_fullDayResponse, 200,
        headers: const {'content-type': 'application/json; charset=utf-8'});
    });
    addTearDown(() => ApiClient.httpClient = previous);

    final service = TimetableService();
    String? firstDay;
    final first = await service.getSavedFullDayBusesFromApi(
      'route-a', 'stop-a',
      referenceTime: DateTime(2026, 10, 15, 15, 23),
      onResolvedDayType: (day) => firstDay = day,
    );
    expect(firstDay, 'Weekday');
    expect(first.single['times'], ['15:37', '16:08', '16:37']);
    expect(first.single['allTimes'], hasLength(5));
    final preferences = await SharedPreferences.getInstance();
    expect(preferences.getKeys().where(
      (key) => key.startsWith('bus_static_schedule_v1:'),
    ), hasLength(1));

    String? nextDay;
    final reopened = await TimetableService().getSavedFullDayBusesFromApi(
      'route-a', 'stop-a',
      referenceTime: DateTime(2026, 10, 15, 16, 10),
      onResolvedDayType: (day) => nextDay = day,
    );
    expect(nextDay, 'Weekday');
    expect(reopened.single['times'], ['16:37', '25:10']);
    expect(requests, 1);
  });

  test('date and stop identity cannot share a saved timetable', () async {
    final previous = ApiClient.httpClient;
    var calls = 0;
    ApiClient.httpClient = MockClient((request) async {
      calls++;
      return http.Response(_fullDayResponse, 200,
        headers: const {'content-type': 'application/json; charset=utf-8'});
    });
    addTearDown(() => ApiClient.httpClient = previous);
    final service = TimetableService();
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
      referenceTime: DateTime(2026, 10, 15, 15, 0));
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
      referenceTime: DateTime(2026, 10, 16, 15, 0));
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-c',
      referenceTime: DateTime(2026, 10, 15, 15, 0));
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
      targetPoleId: 'stop-b', referenceTime: DateTime(2026, 10, 15, 15, 0));
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
      dayType: 'Weekday', referenceTime: DateTime(2026, 10, 15, 15, 0));
    expect(calls, 5);
  });

  test('expired timetable is re-fetched instead of showing stale data', () async {
    final previous = ApiClient.httpClient;
    var calls = 0;
    ApiClient.httpClient = MockClient((request) async {
      calls++;
      return http.Response(_fullDayResponse, 200,
        headers: const {'content-type': 'application/json; charset=utf-8'});
    });
    addTearDown(() => ApiClient.httpClient = previous);
    final service = TimetableService();
    final time = DateTime(2026, 10, 15, 15, 0);
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
      referenceTime: time);
    final prefs = await SharedPreferences.getInstance();
    final key = prefs.getKeys().singleWhere(
      (value) => value.startsWith('bus_static_schedule_v1:'),
    );
    final data = jsonDecode(prefs.getString(key)!) as Map<String, dynamic>;
    data['saved_at_millis'] = DateTime.now()
        .subtract(const Duration(days: 2)).millisecondsSinceEpoch;
    await prefs.setString(key, jsonEncode(data));
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
      referenceTime: time);
    expect(calls, 2);
  });

  test('malformed persistent schedule fails fast without hiding it via HTTP', () async {
    final previous = ApiClient.httpClient;
    var calls = 0;
    ApiClient.httpClient = MockClient((request) async {
      calls++;
      return http.Response(_fullDayResponse, 200,
        headers: const {'content-type': 'application/json; charset=utf-8'});
    });
    addTearDown(() => ApiClient.httpClient = previous);
    final service = TimetableService();
    final time = DateTime(2026, 10, 15, 15, 0);
    await service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
      referenceTime: time);
    final prefs = await SharedPreferences.getInstance();
    final key = prefs.getKeys().singleWhere(
      (value) => value.startsWith('bus_static_schedule_v1:'),
    );
    await prefs.setString(key, '{"schema":1,"groups":"invalid"}');
    await expectLater(
      service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
        referenceTime: time),
      throwsFormatException,
    );
    expect(calls, 1);
  });

  test('two simultaneous visits share one request and never cache a failure', () async {
    final previous = ApiClient.httpClient;
    var calls = 0;
    var fail = true;
    ApiClient.httpClient = MockClient((request) async {
      calls++;
      await Future<void>.delayed(const Duration(milliseconds: 5));
      if (fail) {
        return http.Response('{"detail":"unavailable"}', 503);
      }
      return http.Response(_fullDayResponse, 200,
        headers: const {'content-type': 'application/json; charset=utf-8'});
    });
    addTearDown(() => ApiClient.httpClient = previous);
    final service = TimetableService();
    final time = DateTime(2026, 10, 15, 15, 0);
    final pending = [
      service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
        referenceTime: time),
      service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
        referenceTime: time),
    ];
    for (final request in pending) {
      await expectLater(request, throwsA(isA<ApiException>()));
    }
    expect(calls, 1);
    fail = false;
    final success = await Future.wait([
      service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
        referenceTime: time),
      service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
        referenceTime: time),
    ]);
    expect(success, hasLength(2));
    expect(calls, 2);
  });

  test('invalid schedule clocks do not get persisted', () async {
    final previous = ApiClient.httpClient;
    var calls = 0;
    ApiClient.httpClient = MockClient((request) async {
      calls++;
      return http.Response(_fullDayResponse.replaceAll('16:08', 'bad'),
        200, headers: const {'content-type': 'application/json; charset=utf-8'});
    });
    addTearDown(() => ApiClient.httpClient = previous);
    final service = TimetableService();
    await expectLater(
      service.getSavedFullDayBusesFromApi('route-a', 'stop-a',
        referenceTime: DateTime(2026, 10, 15, 15, 0)),
      throwsFormatException,
    );
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getKeys().where((key) =>
      key.startsWith('bus_static_schedule_v1:')), isEmpty);
    expect(calls, 1);
  });
}

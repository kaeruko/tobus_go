import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/bus_location_source.dart';
import 'package:toeigo/services/timetable_service.dart';

void main() {
  setUp(() {
    configureApiBase(Uri.parse('https://api.example.test'));
  });

  group('ApiClient.fetchBusLocation', () {
    late http.Client originalClient;

    setUp(() {
      originalClient = ApiClient.httpClient;
    });

    tearDown(() {
      ApiClient.httpClient = originalClient;
    });

    test('GET timeout fails instead of hanging indefinitely', () async {
      ApiClient.httpClient = MockClient((request) async {
        await Future<void>.delayed(const Duration(milliseconds: 50));
        return http.Response('{}', 200);
      });

      await expectLater(
        ApiClient.get(
          '/slow',
          timeout: const Duration(milliseconds: 5),
        ),
        throwsA(isA<TimeoutException>()),
      );
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

    test('preserves realtime 404 diagnostics for device logs', () async {
      ApiClient.httpClient = MockClient((request) async {
        return http.Response(
          '{"detail":{"code":"bus_trip_not_found","message":"not live yet",'
          '"diagnostic":{"requested_vehicle_id":"BUS-1",'
          '"requested_vehicle_matches":[{"vehicle_id":"BUS-1",'
          '"route_id":"route-1","trip_id":"trip-2"}]}}}',
          404,
        );
      });

      await expectLater(
        const RealtimeBusLocationSource().fetch(
          routeId: 'route-id',
          tripId: 'trip-id',
          vehicleId: 'BUS-1',
        ),
        throwsA(
          isA<BusLocationNotAvailableException>()
              .having((error) => error.code, 'code', 'bus_trip_not_found')
              .having(
                (error) => error.diagnostic,
                'diagnostic',
                {
                  'requested_vehicle_id': 'BUS-1',
                  'requested_vehicle_matches': [
                    {
                      'vehicle_id': 'BUS-1',
                      'route_id': 'route-1',
                      'trip_id': 'trip-2',
                    },
                  ],
                },
              )
              .having(
                (error) => error.toString(),
                'toString',
                contains('trip-2'),
              ),
        ),
      );
    });

    test('sends boarding stop and scheduled departure together', () async {
      Uri? requestedUri;
      ApiClient.httpClient = MockClient((request) async {
        requestedUri = request.url;
        return http.Response('{}', 200);
      });

      await ApiClient.fetchBusLocation(
        routeId: 'route-id',
        tripId: 'trip-id',
        boardingStopId: 'stop-1',
        scheduledDepartureAt: DateTime.parse('2026-10-04T10:13:00+09:00'),
      );

      expect(requestedUri?.queryParameters['boarding_stop_id'], 'stop-1');
      expect(
        requestedUri?.queryParameters['scheduled_departure_at'],
        '2026-10-04T01:13:00.000Z',
      );
    });

    test('rejects incomplete boarding schedule context before HTTP', () async {
      var requestCount = 0;
      ApiClient.httpClient = MockClient((request) async {
        requestCount++;
        return http.Response('{}', 200);
      });

      await expectLater(
        ApiClient.fetchBusLocation(
          routeId: 'route-id',
          tripId: 'trip-id',
          boardingStopId: 'stop-1',
        ),
        throwsArgumentError,
      );
      expect(requestCount, 0);
    });

    test('treats 425 realtime-not-started as an expected unavailable state', () async {
      ApiClient.httpClient = MockClient((request) async {
        return http.Response(
          '{"detail":{"code":"bus_realtime_not_started",'
          '"message":"Realtime lookup has not started for this trip",'
          '"diagnostic":{"realtime_check_start_at":"2026-10-04T10:13:00+09:00"}}}',
          425,
        );
      });

      await expectLater(
        const RealtimeBusLocationSource().fetch(
          routeId: 'route-id',
          tripId: 'trip-id',
          boardingStopId: 'stop-1',
          scheduledDepartureAt: DateTime(2026, 10, 4, 10, 13),
        ),
        throwsA(
          isA<BusLocationNotAvailableException>()
              .having(
                (error) => error.code,
                'code',
                'bus_realtime_not_started',
              )
              .having(
                (error) => error.diagnostic,
                'diagnostic',
                {'realtime_check_start_at': '2026-10-04T10:13:00+09:00'},
              ),
        ),
      );
    });

    test('adds force_refresh only for a manual refresh', () async {
      Uri? requestedUri;
      ApiClient.httpClient = MockClient((request) async {
        requestedUri = request.url;
        return http.Response('{}', 200);
      });

      await ApiClient.fetchBusLocation(
        routeId: 'route-id',
        tripId: 'trip-id',
        vehicleId: 'vehicle-id',
        forceRefresh: true,
      );

      expect(requestedUri?.queryParameters['force_refresh'], 'true');
    });

    test('does not force refresh during normal polling', () async {
      Uri? requestedUri;
      ApiClient.httpClient = MockClient((request) async {
        requestedUri = request.url;
        return http.Response('{}', 200);
      });

      await ApiClient.fetchBusLocation(routeId: 'route-id', tripId: 'trip-id');

      expect(requestedUri?.queryParameters, isNot(contains('force_refresh')));
      expect(requestedUri?.queryParameters['debug'], 'true');
    });

    test('sends the configured city identity on API requests', () async {
      String? requestedCity;
      ApiClient.httpClient = MockClient((request) async {
        requestedCity = request.headers['X-App-City'];
        return http.Response('{}', 200);
      });

      await ApiClient.fetchBusLocation(routeId: 'route-id', tripId: 'trip-id');

      // flutter test has no native flavor, so the compatibility profile is Tokyo.
      expect(requestedCity, 'tokyo');
    });
  });

  test('preserves realtime freshness diagnostics', () {
    final location = BusLocation.fromJson(
      {
        'vehicle_id': 'vehicle-id',
        'vehicle_lat': 35.6812,
        'vehicle_lon': 139.7671,
        'odpt:fromBusstopPole': 'stop-3',
        'trip_id': 'trip-id',
        'trip_stop_ids': ['stop-1', 'stop-2', 'stop-3'],
        'raw_stop_id': 'stop-4',
        'raw_stop_name': 'Stop 4',
        'from_stop_sequence': 3,
        'observed_stop_sequence': 4,
        'current_status': 'IN_TRANSIT_TO',
        'feed_ts': 1700000000,
        'vehicle_ts': 1700000010,
        'realtime_fetched_ts': 1700000020.5,
        'server_now': '2026-08-14T00:00:00+00:00',
        'snapshot_age_seconds': 1.5,
        'feed_age_seconds': 20.0,
        'vehicle_age_seconds': 10,
        'trip_stop_schedule': [
          {
            'sequence': 3,
            'stop_id': 'stop-3',
            'stop_name': 'Stop 3',
            'arrival_minute': 813,
            'departure_minute': 813,
            'arrival_time': '13:33',
            'departure_time': '13:33',
          },
        ],
      },
      routeId: 'route-id',
      tripId: 'trip-id',
    );

    expect(location.vehicleLat, 35.6812);
    expect(location.vehicleLon, 139.7671);
    expect(location.rawStopId, 'stop-4');
    expect(location.rawStopName, 'Stop 4');
    expect(location.fromStopSequence, 3);
    expect(location.observedStopSequence, 4);
    expect(location.currentStatus, 'IN_TRANSIT_TO');
    expect(location.feedTimestamp, 1700000000);
    expect(location.vehicleTimestamp, 1700000010);
    expect(location.realtimeFetchedTimestamp, 1700000020);
    expect(location.serverNow, '2026-08-14T00:00:00+00:00');
    expect(location.snapshotAgeSeconds, 1.5);
    expect(location.feedAgeSeconds, 20.0);
    expect(location.vehicleAgeSeconds, 10.0);
    expect(location.tripStopSchedule, hasLength(1));
    expect(location.tripStopSchedule.single.sequence, 3);
    expect(location.tripStopSchedule.single.stopName, 'Stop 3');
    expect(location.tripStopSchedule.single.arrivalTime, '13:33');
  });

  test('requests and parses a full-day bilingual timetable', () async {
    final originalClient = ApiClient.httpClient;
    Uri? requestedUri;
    ApiClient.httpClient = MockClient((request) async {
      requestedUri = request.url;
      return http.Response(
        '{"destinations":[{"destination_pole_id":"stop-ueno",'
        '"destination_name":"上野松坂屋前",'
        '"destination_name_en":"Ueno-matsuzakaya",'
        '"times":["16:10","16:25","16:40"],'
        '"all_times":["06:10","06:30","16:10","16:25","16:40","22:15"]}]}',
        200,
        headers: const {'content-type': 'application/json; charset=utf-8'},
      );
    });
    addTearDown(() => ApiClient.httpClient = originalClient);

    final result = await TimetableService().getNextBusesFromApi(
      'route-ueno',
      'stop-hirai',
      targetPoleId: 'stop-oshiage',
      dayType: 'Saturday',
      limit: 3,
      includeAllDay: true,
    );

    expect(requestedUri?.queryParameters['include_all'], 'true');
    expect(requestedUri?.queryParameters['day_type'], 'saturday');
    expect(requestedUri?.queryParameters['limit'], '3');
    expect(requestedUri?.queryParameters['target_pole_id'], 'stop-oshiage');
    expect(result, hasLength(1));
    expect(result.single['destinationName'], '上野松坂屋前');
    expect(result.single['destinationNameEn'], 'Ueno-matsuzakaya');
    expect(result.single['times'], ['16:10', '16:25', '16:40']);
    expect(
      result.single['allTimes'],
      ['06:10', '06:30', '16:10', '16:25', '16:40', '22:15'],
    );
  });

  test('rejects a timetable request without a stop ID', () async {
    final originalClient = ApiClient.httpClient;
    var requestCount = 0;
    ApiClient.httpClient = MockClient((request) async {
      requestCount++;
      return http.Response('{"destinations":[]}', 200);
    });
    addTearDown(() => ApiClient.httpClient = originalClient);

    await expectLater(
      TimetableService().getNextBusesFromApi('070', ''),
      throwsArgumentError,
    );

    expect(requestCount, 0);
  });
}

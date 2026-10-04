import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/services/bus_location_source.dart';

void main() {
  const routeId = '006';
  const tripId = '08501-2-09-100-0920';
  final saved = jsonDecode(File(
    'api/benchmarks/bus_location_2026_10_04/local_api_response.json',
  ).readAsStringSync()) as Map<String, dynamic>;
  final payload = Map<String, dynamic>.from(saved['body'] as Map);
  final schedule = (payload['trip_stop_schedule'] as List)
      .map((item) => Map<String, dynamic>.from(item as Map))
      .toList();
  final step = StepSeg(
    stepId: 'step-bus-43ed3fd4c14b46a583238f56933476f4',
    kind: 'bus',
    title: '都０１（Ｔ０１） 渋谷駅前行',
    fromName: '新橋駅前',
    toName: schedule.last['stop_name'] as String,
    routeId: routeId,
    tripId: tripId,
    departureTime: schedule.first['departure_time'] as String,
    arrivalTime: schedule.last['arrival_time'] as String,
    stops: [
      for (var i = 0; i < schedule.length; i++)
        StopPoint(
          name: schedule[i]['stop_name'] as String,
          stopId: schedule[i]['stop_id'] as String,
          point: const LatLng(35.666221618652344, 139.75929260253906),
          isOrigin: i == 0,
          isDestination: i == schedule.length - 1,
        ),
    ],
  );

  test('exact trip 404 produces null-progress waiting display', () async {
    final originalClient = ApiClient.httpClient;
    addTearDown(() => ApiClient.httpClient = originalClient);
    configureApiBase(Uri.parse('https://api.example.test'));
    ApiClient.httpClient = MockClient((request) async {
      expect(request.url.queryParameters['route_id'], routeId);
      expect(request.url.queryParameters['trip_id'], tripId);
      return http.Response(jsonEncode({
        'detail': {
          'code': 'bus_trip_not_found',
          'message': 'No bus found for trip $tripId on route $routeId',
          'diagnostic': {
            'candidates_total': 385,
            'route_match_count': 3,
            'route_trip_match_count': 0,
          },
        },
      }), 404);
    });
    await expectLater(
      const RealtimeBusLocationSource().fetch(
        routeId: routeId,
        tripId: tripId,
        forceRefresh: true,
      ),
      throwsA(isA<BusLocationNotAvailableException>()
          .having((error) => error.code, 'code', 'bus_trip_not_found')),
    );
    final navigation = NavigationState.navigating(
      step: step,
      busProgress: null,
    );
    expect(step.stops.first.stopId, '0737-04');
    expect(navigation.mainText, '待機中');
    expect(navigation.subText, '新橋駅前 📍');
    expect(navigation.statusLabel, '乗車待ち');
    print(jsonEncode({
      'case': 'exact_trip_404_null_progress',
      'mainText': navigation.mainText,
      'subText': navigation.subText,
      'statusLabel': navigation.statusLabel,
    }));
  });

  test('saved local 200 before-first-stop response produces approaching display', () {
    expect(saved['status'], 200);
    final location = BusLocation.fromJson(
      payload,
      routeId: routeId,
      tripId: tripId,
    );
    expect(location.vehicleId, 'B785');
    expect(location.beforeFirstStop, isTrue);
    expect(location.rawStopId, '0737-04');
    expect(location.observedStopSequence, 1);
    final progress = BusProgress.forStep(
      step: step,
      fromStopId: location.fromStopId,
      beforeFirstStop: location.beforeFirstStop,
      tripStopIds: location.tripStopIds,
      observedStopId: location.rawStopId,
      observedStopName: location.rawStopName,
      currentStatus: location.currentStatus,
      vehicleAgeSeconds: location.vehicleAgeSeconds,
    );
    expect(progress.phase, BusProgressPhase.approaching);
    expect(progress.fromStopId, isNull);
    expect(progress.stopsUntilBoarding, 1);
    final navigation = NavigationState.navigating(
      step: step,
      busProgress: progress,
    );
    expect(navigation.mainText, '都０１（Ｔ０１） 1停留所前');
    expect(navigation.subText, '乗る場所:新橋駅前');
    expect(navigation.statusLabel, '乗車待ち');
    print(jsonEncode({
      'case': 'saved_local_200_before_first_stop',
      'phase': progress.phase.name,
      'mainText': navigation.mainText,
      'subText': navigation.subText,
      'statusLabel': navigation.statusLabel,
      'vehicleAgeSeconds': location.vehicleAgeSeconds,
    }));
  });
}

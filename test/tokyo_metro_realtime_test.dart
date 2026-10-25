import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/transport_scope.dart';
import 'package:toeigo/services/train_location_source.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late http.Client originalClient;

  setUp(() {
    originalClient = ApiClient.httpClient;
  });

  tearDown(() {
    ApiClient.httpClient = originalClient;
  });

  test(
    'Tokyo Metro rail never calls the Toei train location endpoint',
    () async {
      var requests = 0;
      ApiClient.httpClient = MockClient((request) async {
        requests++;
        return http.Response('unexpected request', 500);
      });
      final step = StepSeg(
        stepId: 'metro-rail-1',
        kind: 'rail',
        title: '銀座線',
        operatorId: TransportServiceId.tokyoMetro,
        tripId: 'tokyo_metro:trip-1',
        routeId: 'tokyo_metro:route-1',
        stops: [
          StopPoint(
            name: '渋谷',
            point: const LatLng(35.6580, 139.7016),
            stopId: 'tokyo_metro:G01',
          ),
          StopPoint(
            name: '表参道',
            point: const LatLng(35.6652, 139.7125),
            stopId: 'tokyo_metro:G02',
          ),
        ],
      );

      await expectLater(
        const RealtimeTrainLocationSource().fetch(step: step),
        throwsA(
          isA<TrainLocationNotAvailableException>().having(
            (error) => error.code,
            'code',
            contains('tokyo_metro'),
          ),
        ),
      );
      expect(requests, 0);
    },
  );

  test('legacy saved Metro identity is also excluded from realtime', () {
    final step = StepSeg(
      stepId: 'legacy-metro-rail',
      kind: 'rail',
      title: '丸ノ内線',
      tripId: 'tokyo_metro:legacy-trip',
      routeId: 'tokyo_metro:legacy-route',
    );

    expect(step.operatorId, isNull);
    expect(step.isTokyoMetroRail, isTrue);
    expect(step.supportsRealtimeVehiclePosition, isFalse);
  });

  test(
    'an explicitly unknown rail operator never calls the Toei endpoint',
    () async {
      var requests = 0;
      ApiClient.httpClient = MockClient((request) async {
        requests++;
        return http.Response('unexpected request', 500);
      });
      final step = StepSeg(
        stepId: 'unknown-operator-rail',
        kind: 'rail',
        title: 'Unknown railway',
        operatorId: 'third_party_operator',
        tripId: 'third-party-trip',
        routeId: 'third-party-route',
        stops: [
          StopPoint(name: 'A', point: const LatLng(35.0, 139.0), stopId: 'A'),
          StopPoint(name: 'B', point: const LatLng(35.1, 139.1), stopId: 'B'),
        ],
      );

      await expectLater(
        const RealtimeTrainLocationSource().fetch(step: step),
        throwsA(isA<TrainLocationNotAvailableException>()),
      );
      expect(requests, 0);
    },
  );
}

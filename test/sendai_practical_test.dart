import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/models/sendai_practical_models.dart';
import 'package:toeigo/pages/sendai_practical_test_page.dart';
import 'package:toeigo/services/sendai_practical_service.dart';

Map<String, dynamic> clock(String basis, String time) => {
  'date': '2026-10-16', 'time': time, 'basis': basis,
  'minute': {'numerator': 600, 'denominator': 1},
  'actual_arrival_verified': false,
};
Map<String, dynamic> candidate() => {
  'schema': 'sendai_practical_route_v1', 'profile': 'sendai_published_minute_v1',
  'exact_arrival_verified': false, 'actual_connection_guaranteed': false,
  'experimental_margin_formally_adopted': false,
  'fare': {'policy_id': 'sendai_fureai_pass', 'additional_payment_yen': 0},
  'arrival': clock('journey_arrival_estimate', '10:19'),
  'events': [{
    'kind': 'ride', 'mode': 'rail', 'trip_id': 'sendai_subway:concrete-row',
    'from_stop_id': 'sendai_subway:tozai/仙台', 'to_stop_id': 'sendai_subway:tozai/荒井',
    'departure': clock('published_departure_minute', '10:00'),
    'arrival': clock('published_clock_arrival_proxy', '10:19'),
  }],
};
Map<String, dynamic> capabilities() => {
  'schema': 'sendai_practical_route_v1', 'environment': 'test', 'city': 'sendai',
  'actual_connection_guaranteed': false, 'experimental_margin_formally_adopted': false,
  'fare_policy_ids': ['sendai_fureai_pass'], 'supported_modes': ['rail'],
  'unsupported': ['miyagi_kotsu', 'bus'], 'operating_dates': ['2026-10-16'],
  'stops': [
    {'id': 'sendai_subway:tozai/仙台', 'name': '仙台', 'mode': 'rail'},
    {'id': 'sendai_subway:tozai/荒井', 'name': '荒井', 'mode': 'rail'},
  ],
};

void main() {
  test('clock bases and free-pass results are explicit and reject false guarantees', () {
    final route = SendaiPracticalCandidate.fromJson(candidate());
    final ride = route.events.single as SendaiPracticalRide;
    expect(ride.departure.basis, 'published_departure_minute');
    expect(ride.arrival.basis, 'published_clock_arrival_proxy');
    expect(() => SendaiPracticalCandidate.fromJson({...candidate(), 'exact_arrival_verified': true}), throwsFormatException);
    final bad = candidate();
    ((bad['events'] as List).first as Map<String, dynamic>)['arrival'] = clock('exact_arrival', '10:19');
    expect(() => SendaiPracticalCandidate.fromJson(bad), throwsFormatException);
    expect(() => SendaiPracticalCapabilities.fromJson({...capabilities(), 'environment': 'production'}), throwsFormatException);
  });

  test('service sends exact selected OD/date/pass and never normal-to-free converts', () async {
    var calls = 0;
    final service = SendaiPracticalService(baseUri: Uri.parse('http://localhost:8000'),
      client: MockClient((request) async {
        calls++;
        expect(request.url.path, '/test/sendai/route');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['origin_stop_id'], 'a'); expect(body['destination_stop_id'], 'b');
        expect(body['civil_date'], '2026-10-16'); expect(body['departure_minute'], 600);
        expect(body['fare_policy_id'], 'sendai_fureai_pass');
        expect(body['accept_experimental_transfer_model'], true);
        return http.Response(jsonEncode({'schema':'sendai_practical_route_v1', 'candidates':[candidate()]}), 200);
      }));
    await expectLater(service.search(originStopId: 'a', destinationStopId: 'b', civilDate: '2026-10-16',
      departureMinute: 600, farePolicyId: 'normal', acceptExperimentalTransfers: true), throwsArgumentError);
    expect(calls, 0);
    expect((await service.search(originStopId: 'a', destinationStopId: 'b', civilDate: '2026-10-16',
      departureMinute: 600, farePolicyId: 'sendai_fureai_pass', acceptExperimentalTransfers: true)).length, 1);
    expect(calls, 1);
  });

  test('HTTP failure is propagated without a second endpoint or partial success', () async {
    var calls = 0;
    final service = SendaiPracticalService(baseUri: Uri.parse('http://localhost:8000'),
      client: MockClient((r) async { calls++; return http.Response('search_limit', 503); }));
    await expectLater(service.search(originStopId: 'a', destinationStopId: 'b', civilDate: '2026-10-16',
      departureMinute: 600, farePolicyId: 'sendai_fureai_pass', acceptExperimentalTransfers: true), throwsStateError);
    expect(calls, 1);
  });

  testWidgets('test page shows missing buses and requires explicit pass/model selection', (tester) async {
    final service = SendaiPracticalService(baseUri: Uri.parse('http://localhost:8000'),
      client: MockClient((r) async => http.Response(jsonEncode(capabilities()), 200,
        headers: {'content-type':'application/json; charset=utf-8'})));
    await tester.pumpWidget(MaterialApp(home: SendaiPracticalTestPage(service: service)));
    await tester.pumpAndSettle();
    expect(find.text('市営バスはこのデータでは未対応'), findsOneWidget);
    expect(find.text('宮城交通・未確認の市営区間・特別ダイヤ・Realtimeは未対応'), findsOneWidget);
    expect(find.text('乗車証を明示選択'), findsOneWidget);
    final button = find.text('追加支払0円の確認済み区間を検索');
    await tester.scrollUntilVisible(button, 180); await tester.tap(button); await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('sendai-test-error')), 100);
    expect(find.byKey(const Key('sendai-test-error')), findsOneWidget);
    expect(find.textContaining('選択してください'), findsOneWidget);
  });
}

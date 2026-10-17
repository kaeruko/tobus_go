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
        return http.Response(jsonEncode({'schema':'sendai_practical_route_v1', 'candidates':[candidate()]}), 200,
          headers: {'content-type': 'application/json; charset=utf-8'});
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
    final pageScroll = find.descendant(of: find.byType(ListView), matching: find.byType(Scrollable)).first;
    await tester.scrollUntilVisible(button, 180, scrollable: pageScroll); await tester.tap(button); await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('sendai-test-error')), 100, scrollable: pageScroll);
    expect(find.byKey(const Key('sendai-test-error')), findsOneWidget);
    expect(find.textContaining('入力不足: 出発地・目的地・対応日'), findsOneWidget);
  });
  testWidgets('unsupported scope is visible and an API error is shown without retry', (tester) async {
    var routeCalls = 0;
    final service = SendaiPracticalService(
      baseUri: Uri.parse('http://localhost:8000'),
      client: MockClient((request) async {
        if (request.url.path == '/test/sendai/capabilities' && request.method == 'GET') {
          return http.Response(jsonEncode(capabilities()), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        if (request.url.path != '/test/sendai/route' || request.method != 'POST') {
          throw StateError('Unexpected Sendai test request: ${request.method} ${request.url.path}');
        }
        routeCalls++;
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['origin_stop_id'], 'sendai_subway:tozai/仙台');
        expect(body['destination_stop_id'], 'sendai_subway:tozai/荒井');
        expect(body['departure_minute'], 600);
        expect(body['civil_date'], '2026-10-16');
        expect(body['fare_policy_id'], 'sendai_fureai_pass');
        expect(body['accept_experimental_transfer_model'], true);
        return http.Response(jsonEncode({'detail': {
          'code': 'unsupported_review_scope',
          'message': 'Outside the reviewed test scope'
        }}), 422, headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await tester.pumpWidget(MaterialApp(home: SendaiPracticalTestPage(service: service)));
    await tester.pumpAndSettle();
    expect(find.text('宮城交通・未確認の市営区間・特別ダイヤ・Realtimeは未対応'), findsOneWidget);
    final pageScroll = find.descendant(
        of: find.byType(ListView), matching: find.byType(Scrollable)).first;
    Future<void> reveal(Finder target) async {
      final position = tester.state<ScrollableState>(pageScroll).position;
      position.jumpTo(position.minScrollExtent);
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(target, 200, scrollable: pageScroll);
      await tester.pumpAndSettle();
    }
    Future<void> choose(String field, String id) async {
      final selector = find.byKey(Key('sendai-$field'));
      await reveal(selector);
      await tester.tap(selector);
      await tester.pumpAndSettle();
      final item = find.byKey(ValueKey('sendai-$field-item-$id'));
      await tester.tap(item.last);
      await tester.pumpAndSettle();
    }
    await choose('origin', 'sendai_subway:tozai/仙台');
    await choose('destination', 'sendai_subway:tozai/荒井');
    final dateField = find.byKey(const Key('sendai-date'));
    await reveal(dateField);
    await tester.tap(dateField);
    await tester.pumpAndSettle();
    final reviewedDay = find.byKey(const ValueKey('sendai-date-item-2026-10-16'));
    expect(reviewedDay, findsWidgets);
    expect(find.text('2026-12-31'), findsNothing);
    await tester.tap(reviewedDay.last);
    await tester.pumpAndSettle();
    await choose('pass', 'sendai_fureai_pass');
    final accept = find.byKey(const Key('sendai-accept-transfer'));
    await reveal(accept);
    await tester.tap(accept);
    await tester.pumpAndSettle();
    final search = find.byKey(const Key('sendai-search'));
    await reveal(search);
    await tester.tap(search);
    await tester.pumpAndSettle();
    await reveal(find.byKey(const Key('sendai-test-error')));
    expect(find.textContaining('HTTP 422'), findsOneWidget);
    expect(find.textContaining('unsupported_review_scope'), findsOneWidget);
    expect(routeCalls, 1);
    expect(find.byKey(const Key('sendai-result')), findsNothing);
  });

  testWidgets('direct date input rejects out-of-scope days without API fallback', (tester) async {
    var routeCalls = 0;
    final fixture = capabilities();
    fixture['operating_dates'] = ['2026-11-19', '2026-11-30'];
    final service = SendaiPracticalService(baseUri: Uri.parse('http://localhost:8000'),
      client: MockClient((request) async {
        if (request.method == 'GET' && request.url.path == '/test/sendai/capabilities') {
          return http.Response(jsonEncode(fixture), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        routeCalls++;
        throw StateError('unsupported input must not issue an API search');
      }));
    await tester.pumpWidget(MaterialApp(home: SendaiPracticalTestPage(service: service)));
    await tester.pumpAndSettle();
    final dateField = find.byKey(const Key('sendai-date-direct'));
    final pageScroll = find.descendant(of: find.byType(ListView), matching: find.byType(Scrollable)).first;
    await tester.scrollUntilVisible(dateField, 120, scrollable: pageScroll);
    await tester.enterText(dateField, '2026-12-01');
    await tester.pumpAndSettle();
    expect(find.text('この日付は現在の確認範囲外です'), findsOneWidget);
    final search = find.byKey(const Key('sendai-search'));
    await tester.scrollUntilVisible(search, 120, scrollable: pageScroll);
    await tester.tap(search);
    await tester.pumpAndSettle();
    expect(routeCalls, 0);
  });

}

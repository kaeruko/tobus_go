import 'dart:convert';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart' show MaterialApp, Scaffold, SingleChildScrollView;
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/widgets/sendai_practical_launcher.dart';
import 'package:toeigo/pages/sendai_practical_test_page.dart';

void main() {
  test('ordinary-screen entry requires Sendai, a debug build and explicit endpoint', () {
    for (final city in ['tokyo', 'sendai']) {
      for (final debug in [false, true]) {
        expect(showSendaiPracticalEntry(city: city, debugBuild: debug,
          endpoint: 'http://127.0.0.1:8000'), city == 'sendai' && debug);
      }
    }
    expect(showSendaiPracticalEntry(city: 'sendai', debugBuild: true, endpoint: ''), false);
    expect(() => showSendaiPracticalEntry(city: 'sendai', debugBuild: true,
      endpoint: 'https://example.test/?secret=1'), throwsArgumentError);
  });

  testWidgets('configured development entry renders without starting an API request', (tester) async {
    await tester.pumpWidget(const CupertinoApp(home: SendaiPracticalLauncher(
      city: 'sendai', debugBuild: true, endpoint: 'http://127.0.0.1:8000')));
    expect(find.byKey(const Key('sendai-practical-entry')), findsOneWidget);
    expect(find.byKey(const Key('sendai-practical-inline-toggle')), findsOneWidget);
    await tester.pumpWidget(const CupertinoApp(home: SendaiPracticalLauncher(
      city: 'sendai', debugBuild: false, endpoint: 'http://127.0.0.1:8000')));
    expect(find.byKey(const Key('sendai-practical-entry')), findsNothing);
    expect(find.byKey(const Key('sendai-practical-inline-toggle')), findsNothing);
  });

  testWidgets('ordinary Sendai tab expands reviewed controls only with debug endpoint', (tester) async {
    var capabilityCalls = 0;
    final fake = MockClient((request) async {
      if (request.method != 'GET' || request.url.path != '/test/sendai/capabilities') {
        throw StateError('unexpected endpoint: ${request.method} ${request.url}');
      }
      capabilityCalls++;
      return http.Response(jsonEncode({
        'schema': 'sendai_practical_route_v1',
        'environment': 'test', 'city': 'sendai',
        'actual_connection_guaranteed': false,
        'experimental_margin_formally_adopted': false,
        'fare_policy_ids': ['sendai_fureai_pass'],
        'supported_modes': ['bus', 'rail'], 'unsupported': ['miyagi_kotsu'],
        'operating_dates': ['2026-11-03', '2026-11-19', '2026-11-30'],
        'date_boundary_notice': '日付境界は検索できない場合があります',
        'stops': [
          {'id': 'sendai_bus:1294_10', 'name': '住吉台西三丁目', 'mode': 'bus'},
          {'id': 'sendai_subway:namboku/仙台', 'name': '仙台', 'mode': 'rail'},
        ],
      }), 200, headers: {'content-type': 'application/json'});
    });
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: SingleChildScrollView(
      child: SendaiPracticalLauncher(city: 'sendai', debugBuild: true,
        endpoint: 'http://127.0.0.1:8000', clientFactory: () => fake)))));
    expect(find.byKey(const Key('sendai-origin')), findsNothing);
    await tester.tap(find.byKey(const Key('sendai-practical-inline-toggle')));
    await tester.pumpAndSettle();
    expect(find.byType(SendaiPracticalTestPage), findsOneWidget,
      reason: 'The ordinary search tab must embed the existing practical form');
    expect(capabilityCalls, 1,
      reason: 'The expanded form must fetch the explicit test capabilities once');
  });
}

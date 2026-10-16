import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:toeigo/main_sendai_practical.dart' as app;

const _day = '2026-10-16';
const _busOut = 'sendai_bus:5099_10';
const _busIn = 'sendai_bus:5099_0';
const _araiBus = 'sendai_bus:5181_0';
const _sendaiRail = 'sendai_subway:tozai/仙台';
const _araiRail = 'sendai_subway:tozai/荒井';

Finder get _pageScroll => find.descendant(
  of: find.byType(ListView).first,
  matching: find.byType(Scrollable),
).first;

Future<void> _reveal(WidgetTester tester, Finder target) async {
  // Every search starts from a known scroll position; the preceding result
  // may have left the page below an earlier dropdown.
  final page = tester.state<ScrollableState>(_pageScroll);
  page.position.jumpTo(page.position.minScrollExtent);
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(
    target, 250, scrollable: _pageScroll,
  );
  await tester.pumpAndSettle();
}

Future<void> _select(
  WidgetTester tester, String field, String value,
) async {
  final input = find.byKey(Key('sendai-$field'));
  await _reveal(tester, input);
  await tester.tap(input);
  await tester.pumpAndSettle();
  final item = find.byKey(ValueKey('sendai-$field-item-$value'));
  final menuScroll = find.byType(Scrollable).last;
  // Dropdowns re-open at their previously selected item, so rewind before
  // selecting an earlier stop (e.g. after a rail -> bus query).
  final menu = tester.state<ScrollableState>(menuScroll);
  menu.position.jumpTo(menu.position.minScrollExtent);
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(item, 220, scrollable: menuScroll);
  await tester.tap(item.last);
  await tester.pumpAndSettle();
}

Future<void> _search(
  WidgetTester tester, {
  required String origin,
  required String destination,
  required String time,
  required String expectedArrival,
  required String firstMode,
  String? secondMode,
}) async {
  await _select(tester, 'origin', origin);
  await _select(tester, 'destination', destination);
  final timeInput = find.byKey(const Key('sendai-time'));
  await _reveal(tester, timeInput);
  await tester.enterText(timeInput, time);
  await tester.pumpAndSettle();
  expect(tester.widget<TextField>(timeInput).controller!.text, time,
      reason: 'Search time field did not accept the requested time');
  final button = find.byKey(const Key('sendai-search'));
  await _reveal(tester, button);
  await tester.tap(button);
  await tester.pumpAndSettle();
  final result = find.byKey(const Key('sendai-result'));
  await _reveal(tester, result);
  expect(result, findsOneWidget);
  final rendered = tester.widgetList<Text>(find.descendant(
    of: result, matching: find.byType(Text),
  )).map((widget) => widget.data).whereType<String>().toList();
  final expected = '追加支払0円・到着目安 $_day $expectedArrival';
  expect(rendered.any((value) => value.contains(expected)), isTrue,
      reason: 'Rendered route for $origin -> $destination at $time: $rendered');
  expect(find.textContaining(firstMode), findsWidgets);
  if (secondMode != null) {
    expect(find.textContaining(secondMode), findsWidgets);
    expect(find.textContaining('仮の乗換5分＋仮の余裕2分'), findsOneWidget);
  }
  expect(find.textContaining('乗換は保証しません'), findsOneWidget);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('official GTFS localhost API: four fixed routes via Chrome UI',
      (tester) async {
    // The same opt-in entry point used for manual Chrome validation.
    // No mock client, dataset substitution, or production endpoint.
    app.main();
    await tester.pumpAndSettle();
    expect(find.text('仙台でGO 検証用'), findsOneWidget);
    expect(find.textContaining('確認済み:'), findsOneWidget);

    final search = find.byKey(const Key('sendai-search'));
    await _reveal(tester, search);
    await tester.tap(search);
    await tester.pumpAndSettle();
    await _reveal(tester, find.byKey(const Key('sendai-test-error')));
    expect(find.textContaining('選択してください'), findsOneWidget);

    await _select(tester, 'date', _day);
    await _select(tester, 'pass', 'sendai_fureai_pass');
    final accept = find.byKey(const Key('sendai-accept-transfer'));
    await _reveal(tester, accept);
    await tester.tap(accept);
    await tester.pumpAndSettle();

    await _search(tester, origin: _busOut, destination: _araiBus,
        time: '11:00', expectedArrival: '11:51', firstMode: '市営バス');
    await _search(tester, origin: _sendaiRail, destination: _araiRail,
        time: '10:00', expectedArrival: '10:19', firstMode: '地下鉄');
    await _search(tester, origin: _busOut, destination: _sendaiRail,
        time: '11:00', expectedArrival: '12:14',
        firstMode: '市営バス', secondMode: '地下鉄');
    await _search(tester, origin: _sendaiRail, destination: _busIn,
        time: '10:00', expectedArrival: '10:58',
        firstMode: '地下鉄', secondMode: '市営バス');
  });
}

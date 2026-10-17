import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:toeigo/main_sendai_practical.dart' as app;

String _chromeStage = 'start';

Finder get _pageScroll => find.descendant(of: find.byType(ListView).first,
  matching: find.byType(Scrollable)).first;

Future<void> _reveal(WidgetTester tester, Finder input) async {
  tester.state<ScrollableState>(_pageScroll).position.jumpTo(0);
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(input, 220, scrollable: _pageScroll);
  await tester.pumpAndSettle();
}

Future<void> _select(WidgetTester tester, String field, String value) async {
  _chromeStage = 'select $field=$value: reveal field';
  final input = find.byKey(Key('sendai-$field'));
  await _reveal(tester, input);
  _chromeStage = 'select $field=$value: tap field';
  await tester.tap(input);
  await tester.pumpAndSettle();
  _chromeStage = 'select $field=$value: locate menu';
  final menu = find.byType(Scrollable).last;
  tester.state<ScrollableState>(menu).position.jumpTo(0);
  await tester.pumpAndSettle();
  // Re-selecting the current date renders its key in both the field and the
  // open overlay. Scope to the menu while allowing lazily built items to be
  // absent until scrollUntilVisible scrolls them into view.
  final item = find.descendant(
    of: menu,
    matching: find.byKey(ValueKey('sendai-$field-item-$value')),
  );
  _chromeStage = 'select $field=$value: find menu item';
  await tester.scrollUntilVisible(item, 64, maxScrolls: 160,
    alignment: 0.5, scrollable: menu);
  await tester.tap(item);
  await tester.pumpAndSettle();
  final committed = tester.state<FormFieldState<String>>(input).value;
  if (committed != value) {
    throw StateError('Drop-down failed to commit $field=$value; '
        'current FormFieldState.value=$committed; visible menu item=${item.evaluate().length}');
  }
  _chromeStage = 'selected $field=$value';
}

Future<void> _query(WidgetTester tester, {required String origin,
    required String destination, required String day, required String time,
    String? arrival, required bool izumiTransfer}) async {
  _chromeStage = 'query $origin -> $destination $day $time: direct date';
  final directDate = find.byKey(const Key('sendai-date-direct'));
  await _reveal(tester, directDate);
  _chromeStage = 'query $day: enter direct date';
  await tester.enterText(directDate, day);
  await tester.pumpAndSettle();
  expect(tester.widget<TextField>(directDate).controller!.text, day);
  await _select(tester, 'origin', origin);
  await _select(tester, 'destination', destination);
  _chromeStage = 'query $day: locate time';
  final input = find.byKey(const Key('sendai-time'));
  await _reveal(tester, input);
  await tester.tap(input);
  await tester.pumpAndSettle();
  await tester.enterText(input, time);
  expect(tester.widget<TextField>(input).controller!.text, time);
  _chromeStage = 'query $day: reveal search';
  final button = find.byKey(const Key('sendai-search'));
  await _reveal(tester, button);
  await tester.tap(button);
  await tester.pumpAndSettle();
  _chromeStage = 'query $day: search returned';
  final result = find.byKey(const Key('sendai-result'));
  if (result.evaluate().isEmpty) {
    final errorFinder = find.byKey(const Key('sendai-test-error'));
    final diagnostic = errorFinder.evaluate().isNotEmpty
        ? tester.widget<Text>(errorFinder).data : 'no error widget';
    throw StateError('No result for $origin -> $destination on $day $time; UI error: $diagnostic');
  }
  await _reveal(tester, result);
  final rendered = tester.widgetList<Text>(find.descendant(of: result,
    matching: find.byType(Text))).map((w) => w.data).whereType<String>().toList();
  expect(rendered.any((v) => arrival == null
      ? v.startsWith('追加支払0円・到着目安 $day ')
      : v.contains('追加支払0円・到着目安 $day $arrival')), isTrue,
    reason: 'Fixed reviewed UI route differs: $origin -> $destination at $day $time: $rendered');
  if (izumiTransfer) {
    expect(find.textContaining('仮の乗換8分＋仮の余裕2分'), findsOneWidget);
    expect(find.textContaining('東1出入口'), findsOneWidget);
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('November bus, subway and transfers through the Flutter Chrome UI', (tester) async {
    try {
    _chromeStage = 'boot app';
    app.main();
    await tester.pumpAndSettle();
    expect(find.textContaining('泉中央20/21'), findsOneWidget);
    expect(find.textContaining('日付境界'), findsOneWidget);
    _chromeStage = 'select pass';
    await _select(tester, 'pass', 'sendai_fureai_pass');
    _chromeStage = 'accept model';
    final accept = find.byKey(const Key('sendai-accept-transfer'));
    await _reveal(tester, accept);
    await tester.tap(accept);
    await tester.pumpAndSettle();
    await _query(tester, origin: 'sendai_bus:1294_10', destination: 'sendai_bus:1085_0',
      day: '2026-11-19', time: '09:00', arrival: '09:49', izumiTransfer: false);
    await _query(tester, origin: 'sendai_bus:1294_10', destination: 'sendai_subway:namboku/仙台',
      day: '2026-11-19', time: '09:00', arrival: '10:16', izumiTransfer: true);
    await _query(tester, origin: 'sendai_subway:namboku/仙台', destination: 'sendai_bus:1294_0',
      day: '2026-11-19', time: '08:20', arrival: '09:57', izumiTransfer: true);
    await _query(tester, origin: 'sendai_bus:1294_10', destination: 'sendai_bus:1085_0',
      day: '2026-11-03', time: '09:00', arrival: '10:09', izumiTransfer: false);
    await _query(tester, origin: 'sendai_bus:1085_12', destination: 'sendai_bus:1294_0',
      day: '2026-11-21', time: '09:00', arrival: '10:23', izumiTransfer: false);
    await _query(tester, origin: 'sendai_subway:namboku/仙台',
      destination: 'sendai_subway:namboku/泉中央',
      day: '2026-11-19', time: '09:00', arrival: null, izumiTransfer: false);
    } catch (error, stack) {
      Error.throwWithStackTrace(StateError('Stage: $_chromeStage; original error: $error; original stack:\n$stack'), stack);
    }
  });
}

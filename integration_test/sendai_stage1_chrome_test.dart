import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:toeigo/main_sendai_practical.dart' as app;

Finder get _pageScroll => find.descendant(of: find.byType(ListView).first,
  matching: find.byType(Scrollable)).first;

Future<void> _reveal(WidgetTester tester, Finder input) async {
  tester.state<ScrollableState>(_pageScroll).position.jumpTo(0);
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(input, 220, scrollable: _pageScroll);
  await tester.pumpAndSettle();
}

Future<void> _select(WidgetTester tester, String field, String value) async {
  final input = find.byKey(Key('sendai-$field'));
  await _reveal(tester, input);
  await tester.tap(input);
  await tester.pumpAndSettle();
  final menu = find.byType(Scrollable).last;
  tester.state<ScrollableState>(menu).position.jumpTo(0);
  await tester.pumpAndSettle();
  // Re-selecting the current date renders its key in both the field and the
  // open overlay. Select the menu occurrence explicitly, including for scroll.
  final item = find.byKey(ValueKey('sendai-$field-item-$value')).last;
  await tester.scrollUntilVisible(item, 220, scrollable: menu);
  await tester.tap(item);
  await tester.pumpAndSettle();
}

Future<void> _query(WidgetTester tester, {required String origin,
    required String destination, required String day, required String time,
    required String arrival, required bool izumiTransfer}) async {
  await _select(tester, 'date', day);
  await _select(tester, 'origin', origin);
  await _select(tester, 'destination', destination);
  final input = find.byKey(const Key('sendai-time'));
  await _reveal(tester, input);
  await tester.tap(input);
  await tester.pumpAndSettle();
  await tester.enterText(input, time);
  expect(tester.widget<TextField>(input).controller!.text, time);
  final button = find.byKey(const Key('sendai-search'));
  await _reveal(tester, button);
  await tester.tap(button);
  await tester.pumpAndSettle();
  final result = find.byKey(const Key('sendai-result'));
  await _reveal(tester, result);
  final rendered = tester.widgetList<Text>(find.descendant(of: result,
    matching: find.byType(Text))).map((w) => w.data).whereType<String>().toList();
  expect(rendered.any((v) => v.contains('追加支払0円・到着目安 $day $arrival')), isTrue,
    reason: 'Fixed new-stage UI route differs: $origin -> $destination at $day $time: $rendered');
  if (izumiTransfer) {
    expect(find.textContaining('仮の乗換8分＋仮の余裕2分'), findsOneWidget);
    expect(find.textContaining('東1出入口'), findsOneWidget);
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('new Arai21, Izumi hub and extended date through the actual Chrome UI', (tester) async {
    app.main();
    await tester.pumpAndSettle();
    expect(find.textContaining('泉中央21'), findsOneWidget);
    expect(find.textContaining('日付境界'), findsOneWidget);
    await _select(tester, 'pass', 'sendai_fureai_pass');
    final accept = find.byKey(const Key('sendai-accept-transfer'));
    await _reveal(tester, accept);
    await tester.tap(accept);
    await tester.pumpAndSettle();
    await _query(tester, origin: 'sendai_bus:5181_11', destination: 'sendai_bus:5099_0',
      day: '2026-10-16', time: '07:00', arrival: '07:22', izumiTransfer: false);
    await _query(tester, origin: 'sendai_bus:9260_10', destination: 'sendai_subway:namboku/仙台',
      day: '2026-10-19', time: '09:00', arrival: '10:00', izumiTransfer: true);
    await _query(tester, origin: 'sendai_subway:namboku/仙台', destination: 'sendai_bus:9260_0',
      day: '2026-10-19', time: '08:20', arrival: '09:36', izumiTransfer: true);
  });
}

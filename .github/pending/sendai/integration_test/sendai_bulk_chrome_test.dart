import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart' as gestures show kTouchSlop;
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:toeigo/widgets/sendai_practical_launcher.dart';
import 'package:toeigo/pages/sendai_practical_test_page.dart';

String _chromeStage = 'start';

Finder get _pageScroll => find.descendant(of: find.byType(ListView).first,
  matching: find.byType(Scrollable)).first;

Future<void> _reveal(WidgetTester tester, Finder input) async {
  tester.state<ScrollableState>(_pageScroll).position.jumpTo(0);
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(input, 220, scrollable: _pageScroll);
  await Scrollable.ensureVisible(tester.element(input), alignment: 0.4);
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
  // The existing form uses variable-height rows (itemHeight=null). Reuse
  // scrollUntilVisible on the SAME menu, with overlapping gestures derived
  // from its measured viewport. Never assume a per-option pixel offset.
  final position = tester.state<ScrollableState>(menu).position;
  final delta = position.viewportDimension / 2;
  if (!delta.isFinite || delta <= gestures.kTouchSlop) {
    throw StateError('Menu viewport cannot support the declared drag: '
        '$field=$value; viewport=${position.viewportDimension}');
  }
  final maxScrolls = (position.maxScrollExtent / (delta - gestures.kTouchSlop)).ceil() + 20;
  _chromeStage = 'select $field=$value: viewport=${position.viewportDimension}, '
      'extent=${position.maxScrollExtent}, delta=$delta, budget=$maxScrolls';
  await tester.scrollUntilVisible(item, delta,
      maxScrolls: maxScrolls, scrollable: menu);
  await Scrollable.ensureVisible(tester.element(item), alignment: 0.5);
  await tester.pumpAndSettle();
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
    String? arrival}) async {
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
  final errorFinder = find.byKey(const Key('sendai-test-error'));
  // The live localhost HTTP request can outlast pumpAndSettle: settling frames
  // is not proof that a real network Future completed. Poll the SAME request,
  // once, with a finite wait; never retry the API or alter the search.
  for (var attempt = 0; attempt < 100; attempt++) {
    if (result.evaluate().isNotEmpty || errorFinder.evaluate().isNotEmpty) break;
    // Results are lazy ListView children: scroll to where a new result is
    // mounted, rather than mistaking an off-screen card for no API response.
    final page = tester.state<ScrollableState>(_pageScroll).position;
    page.jumpTo(page.maxScrollExtent);
    await tester.pump(const Duration(milliseconds: 250));
  }
  if (result.evaluate().isEmpty) {
    final diagnostic = errorFinder.evaluate().isNotEmpty
        ? tester.widget<Text>(errorFinder).data
        : 'neither result nor error appeared after bounded wait';
    throw StateError('No result for $origin -> $destination on $day $time; UI error: $diagnostic');
  }
  await _reveal(tester, result);
  final rendered = tester.widgetList<Text>(find.descendant(of: result,
    matching: find.byType(Text))).map((w) => w.data).whereType<String>().toList();
  expect(rendered.any((v) => arrival == null
      ? v.startsWith('追加支払0円・到着目安 $day ')
      : v.contains('追加支払0円・到着目安 $day $arrival')), isTrue,
    reason: 'Fixed reviewed UI route differs: $origin -> $destination at $day $time: $rendered');
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Bulk municipal operator real routes through the existing inline Sendai form in Chrome', (tester) async {
    try {
      _chromeStage = 'open existing ordinary-screen inline form';
      await tester.pumpWidget(const MaterialApp(home: Scaffold(
        body: SingleChildScrollView(child: SendaiPracticalLauncher(
          city: 'sendai', endpoint: String.fromEnvironment('SENDAI_TEST_API_BASE'))))));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sendai-practical-inline-toggle')));
      await tester.pumpAndSettle();
      expect(tester.widget<SendaiPracticalTestPage>(find.byType(SendaiPracticalTestPage)).embedded, isTrue);
      expect(find.textContaining('336/339'), findsOneWidget);
      expect(find.textContaining('8,142'), findsOneWidget);
      await _select(tester, 'pass', 'sendai_fureai_pass');
      final accept = find.byKey(const Key('sendai-accept-transfer'));
      await _reveal(tester, accept);
      await tester.tap(accept);
      await tester.pumpAndSettle();
      await _query(tester, origin: 'sendai_bus:2005_50', destination: 'sendai_bus:2041_0',
        day: '2026-11-19', time: '09:00', arrival: '09:38');
      await _query(tester, origin: 'sendai_bus:5227_10', destination: 'sendai_subway:namboku/泉中央',
        day: '2026-11-19', time: '09:00', arrival: '10:56');
      await _query(tester, origin: 'sendai_subway:namboku/仙台', destination: 'sendai_bus:1155_0',
        day: '2026-11-19', time: '09:00', arrival: '10:48');
      await _query(tester, origin: 'sendai_bus:2151_50', destination: 'sendai_bus:2603_10',
        day: '2026-11-19', time: '08:00', arrival: '08:33');
      await tester.pumpWidget(const SizedBox.shrink());
    } catch (error, stack) {
      Error.throwWithStackTrace(StateError('Stage: $_chromeStage; original error: $error; original stack:\n$stack'), stack);
    }
  });
}

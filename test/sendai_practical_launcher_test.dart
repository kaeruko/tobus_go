import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/widgets/sendai_practical_launcher.dart';

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
    await tester.pumpWidget(const CupertinoApp(home: SendaiPracticalLauncher(
      city: 'sendai', debugBuild: false, endpoint: 'http://127.0.0.1:8000')));
    expect(find.byKey(const Key('sendai-practical-entry')), findsNothing);
  });
}

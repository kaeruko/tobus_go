import 'package:flutter_test/flutter_test.dart';
import 'package:toei_go/main.dart';

void main() {
  testWidgets('App smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const App());
  });
}

import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/main.dart';

void main() {
  test('App can be constructed without starting Firebase', () {
    expect(const App(), isA<App>());
  });
}

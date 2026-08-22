import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/utils/stop_map_utils.dart';

void main() {
  group('hasUsableTransitCoordinate', () {
    test('accepts a Tokyo transit coordinate', () {
      expect(
        hasUsableTransitCoordinate(35.7067, 139.8423),
        isTrue,
      );
    });

    test('rejects missing placeholder coordinate', () {
      expect(hasUsableTransitCoordinate(0.0, 0.0), isFalse);
    });

    test('rejects non-finite and out-of-range values', () {
      expect(hasUsableTransitCoordinate(double.nan, 139.0), isFalse);
      expect(hasUsableTransitCoordinate(35.0, double.infinity), isFalse);
      expect(hasUsableTransitCoordinate(91.0, 139.0), isFalse);
      expect(hasUsableTransitCoordinate(35.0, 181.0), isFalse);
    });
  });

  group('buildGoogleMapsCoordinateUri', () {
    test('builds a coordinate search URL without changing coordinates', () {
      final uri = buildGoogleMapsCoordinateUri(
        latitude: 35.7067,
        longitude: 139.8423,
      );

      expect(uri.scheme, 'https');
      expect(uri.host, 'www.google.com');
      expect(uri.path, '/maps/search/');
      expect(uri.queryParameters['api'], '1');
      expect(uri.queryParameters['query'], '35.7067,139.8423');
    });

    test('fails fast for an unusable coordinate', () {
      expect(
        () => buildGoogleMapsCoordinateUri(latitude: 0.0, longitude: 0.0),
        throwsArgumentError,
      );
    });
  });
}

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

  group('buildGoogleMapsMapViewUri', () {
    test('opens a map area with no place-search pin', () {
      final uri = buildGoogleMapsMapViewUri(
        latitude: 35.700193,
        longitude: 139.802249,
        zoom: 13,
      );

      expect(uri.scheme, 'https');
      expect(uri.host, 'www.google.com');
      expect(uri.path, '/maps/@');
      expect(uri.queryParameters, {
        'api': '1',
        'map_action': 'map',
        'center': '35.700193,139.802249',
        'zoom': '13',
      });
    });

    test('rejects invalid coordinates or zoom levels', () {
      expect(
        () => buildGoogleMapsMapViewUri(
          latitude: 0,
          longitude: 0,
          zoom: 13,
        ),
        throwsArgumentError,
      );
      expect(
        () => buildGoogleMapsMapViewUri(
          latitude: 35.7,
          longitude: 139.8,
          zoom: 22,
        ),
        throwsRangeError,
      );
      expect(
        () => buildGoogleMapsMapViewUri(
          latitude: 35.7,
          longitude: 139.8,
          zoom: -1,
        ),
        throwsRangeError,
      );
    });
  });

  group('buildGoogleMapsNearbyAreaUri', () {
    test('centers a free Google Maps area view on the exact stop', () {
      final uri = buildGoogleMapsNearbyAreaUri(
        latitude: 35.7138,
        longitude: 139.7773,
      );

      expect(uri.scheme, 'https');
      expect(uri.host, 'www.google.com');
      expect(uri.path, '/maps/@');
      expect(uri.queryParameters, {
        'api': '1',
        'map_action': 'map',
        'center': '35.7138,139.7773',
        'zoom': '16',
      });
    });

    test('fails fast rather than opening the wrong area', () {
      expect(
        () => buildGoogleMapsNearbyAreaUri(latitude: 0.0, longitude: 0.0),
        throwsArgumentError,
      );
      expect(
        () => buildGoogleMapsNearbyAreaUri(latitude: double.nan, longitude: 139.0),
        throwsArgumentError,
      );
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

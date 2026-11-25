import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/core/usage_analytics.dart';

void main() {
  test('counts route and both realtime modes without request payloads', () async {
    final events = <(String, Map<String, Object>?)>[];
    final analytics = UsageAnalytics((name, parameters) async {
      events.add((name, parameters));
    });

    await analytics.recordApiRequest('POST', '/route');
    await analytics.recordApiRequest('GET', '/bus/location');
    await analytics.recordApiRequest('GET', '/train/location');
    await analytics.recordRouteDetail();
    await analytics.recordApiRequest('GET', '/bus/location');

    expect(events.map((event) => event.$1), [
      'route_search',
      'realtime_use',
      'realtime_use',
      'route_detail_view',
      'realtime_use',
    ]);
    expect(events.map((event) => event.$2), [
      null,
      {'transport': 'bus'},
      {'transport': 'train'},
      null,
      {'transport': 'bus'},
    ]);
  });

  test('does not mistake timetable or identity lookup for realtime', () async {
    final events = <String>[];
    final analytics = UsageAnalytics((name, parameters) async {
      events.add(name);
    });

    await analytics.recordApiRequest('GET', '/route');
    await analytics.recordApiRequest('GET', '/bus/next');
    await analytics.recordApiRequest('POST', '/train/resolve-route-identities');
    await analytics.recordApiRequest('GET', '/warmup');
    await analytics.recordApiRequest('GET', '/autocomplete');
    await analytics.recordApiRequest('GET', '/details');
    await analytics.recordApiRequest('GET', '/bus/location?trip_id=secret');

    expect(events, isEmpty);
  });

  test('failed telemetry reports original diagnostic without retry', () async {
    final originalHandler = FlutterError.onError;
    final diagnostics = <FlutterErrorDetails>[];
    final originalError = StateError('telemetry failed');
    var calls = 0;
    FlutterError.onError = diagnostics.add;
    try {
      final analytics = UsageAnalytics((name, parameters) async {
        calls++;
        throw originalError;
      });
      await analytics.recordApiRequest('POST', '/route');
      expect(calls, 1);
      expect(diagnostics.single.exception, same(originalError));
      expect(diagnostics.single.stack, isNotNull);
    } finally {
      FlutterError.onError = originalHandler;
    }
  });
}

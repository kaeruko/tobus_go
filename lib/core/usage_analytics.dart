import 'dart:async';

import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:flutter/foundation.dart';

import 'city_profile.dart';

typedef UsageEventSink = Future<void> Function(
  String name,
  Map<String, Object>? parameters,
);

/// Feature telemetry is independent from routing and never receives payloads.
class UsageAnalytics {
  UsageAnalytics(this._send);

  final UsageEventSink _send;
  static UsageAnalytics? _active;
  static bool _started = false;

  /// Only Tokyo Android/iOS release builds emit custom production events.
  /// Analytics initialization is independent of app bootstrap.
  static void start(CityProfile profile) {
    if (_started ||
        !kReleaseMode ||
        kIsWeb ||
        profile.city != AppCity.tokyo ||
        !profile.distribution.firebaseEnabled ||
        (defaultTargetPlatform != TargetPlatform.android &&
            defaultTargetPlatform != TargetPlatform.iOS)) {
      return;
    }
    _started = true;
    unawaited(_initialize());
  }

  static Future<void> _initialize() async {
    try {
      final sdk = FirebaseAnalytics.instance;
      await sdk.setAnalyticsCollectionEnabled(true);
      _active = UsageAnalytics(
        (name, parameters) => sdk.logEvent(
          name: name,
          parameters: parameters,
        ),
      );
    } catch (error, stack) {
      // Stop telemetry initialization, not the independent route service.
      // Preserve the original diagnostic; no alternate sink or retry.
      _report(error, stack, 'initialization');
    }
  }

  static void trackApiRequest(String method, String path) {
    final active = _active;
    if (active != null) {
      unawaited(active.recordApiRequest(method, path));
    }
  }

  static void trackRouteDetail() {
    final active = _active;
    if (active != null) {
      unawaited(active.recordRouteDetail());
    }
  }

  Future<void> recordApiRequest(String method, String path) async {
    if (method == 'POST' && path == '/route') {
      await _emit('route_search');
    } else if (method == 'GET' && path == '/bus/location') {
      await _emit('realtime_use', const {'transport': 'bus'});
    } else if (method == 'GET' && path == '/train/location') {
      await _emit('realtime_use', const {'transport': 'train'});
    }
  }

  Future<void> recordRouteDetail() => _emit('route_detail_view');

  Future<void> _emit(
    String name, [
    Map<String, Object>? parameters,
  ]) async {
    try {
      await _send(name, parameters);
    } catch (error, stack) {
      // A failed telemetry operation is reported and stops here. Never retry
      // or change the outcome of the user's independent API request.
      _report(error, stack, name);
    }
  }

  static void _report(Object error, StackTrace stack, String operation) {
    FlutterError.reportError(
      FlutterErrorDetails(
        exception: error,
        stack: stack,
        library: 'usage analytics',
        context: ErrorDescription(operation),
      ),
    );
  }
}

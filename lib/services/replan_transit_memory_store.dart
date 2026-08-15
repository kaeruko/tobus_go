import 'dart:convert';

import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../logic/replan_anchor.dart';
import '../logic/replan_transit_memory.dart';

class PersistedReplanTransitMemory {
  final String tripId;
  final String userId;
  final ReplanTransitPlace? lastConfirmedTransitPlace;
  final String? knownOnboardStepId;

  const PersistedReplanTransitMemory({
    required this.tripId,
    required this.userId,
    this.lastConfirmedTransitPlace,
    this.knownOnboardStepId,
  });

  ReplanTransitMemory toMemory() {
    return ReplanTransitMemory(
      lastConfirmedTransitPlace: lastConfirmedTransitPlace,
      knownOnboardStepId: knownOnboardStepId,
    );
  }
}

/// Persists only route-derived historical facts needed after an app restart.
///
/// Realtime forecasts themselves are deliberately not persisted because they
/// become stale while the app is closed. On restart, a remembered onboard step
/// blocks replanning until fresh realtime proves the current station/stop.
class ReplanTransitMemoryStore {
  static const int _schemaVersion = 1;
  static const String _keyPrefix = 'replan_transit_memory_v1';

  Future<PersistedReplanTransitMemory?> load({
    required String tripId,
    required String userId,
  }) async {
    final normalizedTripId = _requiredId(tripId, 'tripId');
    final normalizedUserId = _requiredId(userId, 'userId');
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key(normalizedTripId, normalizedUserId));
    if (raw == null) return null;

    final decoded = jsonDecode(raw);
    if (decoded is! Map<String, dynamic>) {
      throw StateError('保存済み再探索履歴がobjectではありません');
    }
    if (decoded['schemaVersion'] != _schemaVersion) {
      throw StateError(
        '保存済み再探索履歴のschemaVersionが不正です: '
        '${decoded['schemaVersion']}',
      );
    }
    if (decoded['tripId'] != normalizedTripId ||
        decoded['userId'] != normalizedUserId) {
      throw StateError('保存済み再探索履歴のTrip/Userが一致しません');
    }

    final knownOnboardStepId = _optionalNonEmptyString(
      decoded['knownOnboardStepId'],
      'knownOnboardStepId',
    );
    final place = _decodePlace(decoded['lastConfirmedTransitPlace']);

    return PersistedReplanTransitMemory(
      tripId: normalizedTripId,
      userId: normalizedUserId,
      lastConfirmedTransitPlace: place,
      knownOnboardStepId: knownOnboardStepId,
    );
  }

  Future<void> save({
    required String tripId,
    required String userId,
    required ReplanTransitMemory memory,
  }) async {
    final normalizedTripId = _requiredId(tripId, 'tripId');
    final normalizedUserId = _requiredId(userId, 'userId');
    final prefs = await SharedPreferences.getInstance();
    final key = _key(normalizedTripId, normalizedUserId);

    final place = memory.lastConfirmedTransitPlace;
    final onboard = memory.knownOnboardStepId;
    if (place == null && onboard == null) {
      await prefs.remove(key);
      return;
    }

    final payload = <String, dynamic>{
      'schemaVersion': _schemaVersion,
      'tripId': normalizedTripId,
      'userId': normalizedUserId,
      'knownOnboardStepId': onboard,
      'lastConfirmedTransitPlace': place == null
          ? null
          : <String, dynamic>{
              'name': place.name,
              'stopId': place.stopId,
              'latitude': place.point.latitude,
              'longitude': place.point.longitude,
            },
    };
    await prefs.setString(key, jsonEncode(payload));
  }

  Future<void> clear({
    required String tripId,
    required String userId,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key(
      _requiredId(tripId, 'tripId'),
      _requiredId(userId, 'userId'),
    ));
  }

  static ReplanTransitPlace? _decodePlace(dynamic raw) {
    if (raw == null) return null;
    if (raw is! Map<String, dynamic>) {
      throw StateError('保存済み最終確定地点がobjectではありません');
    }
    final name = raw['name'];
    if (name is! String || name.trim().isEmpty) {
      throw StateError('保存済み最終確定地点のnameが不正です: $name');
    }
    final stopId = _optionalNonEmptyString(raw['stopId'], 'stopId');
    final latitude = raw['latitude'];
    final longitude = raw['longitude'];
    if (latitude is! num || longitude is! num) {
      throw StateError('保存済み最終確定地点の座標が数値ではありません');
    }
    final lat = latitude.toDouble();
    final lon = longitude.toDouble();
    if (!lat.isFinite || !lon.isFinite || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      throw StateError('保存済み最終確定地点の座標が不正です: $lat,$lon');
    }
    return ReplanTransitPlace(
      name: name,
      stopId: stopId,
      point: LatLng(lat, lon),
    );
  }

  static String _requiredId(String value, String field) {
    final normalized = value.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(value, field, 'must not be empty');
    }
    return normalized;
  }

  static String? _optionalNonEmptyString(dynamic value, String field) {
    if (value == null) return null;
    if (value is! String || value.trim().isEmpty) {
      throw StateError('保存済み再探索履歴の$fieldが不正です: $value');
    }
    return value.trim();
  }

  static String _key(String tripId, String userId) =>
      '$_keyPrefix::$userId::$tripId';
}

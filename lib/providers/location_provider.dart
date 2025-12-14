import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';

class LocationOverrideNotifier extends StateNotifier<LatLng?> {
  LocationOverrideNotifier() : super(null) {
    _load();
  }

  static const _key = 'manual_location_override';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_key);
    if (saved == null) return;

    final parts = saved.split(',');
    if (parts.length != 2) return;

    final lat = double.tryParse(parts[0]);
    final lon = double.tryParse(parts[1]);
    if (lat == null || lon == null) return;

    state = LatLng(lat, lon);
  }

  Future<void> setOverride(LatLng? value) async {
    state = value;

    final prefs = await SharedPreferences.getInstance();
    if (value == null) {
      await prefs.remove(_key);
    } else {
      await prefs.setString(_key, '${value.latitude},${value.longitude}');
    }
  }

  Future<void> clearOverride() => setOverride(null);
}

final locationOverrideProvider =
    StateNotifierProvider<LocationOverrideNotifier, LatLng?>(
  (ref) => LocationOverrideNotifier(),
);

final locationStreamProvider = StreamProvider.autoDispose<Position>((ref) async* {
  // Check permissions (simplified, assuming handled elsewhere or best effort)
  final serviceEnabled = await Geolocator.isLocationServiceEnabled();
  if (!serviceEnabled) {
    throw Exception('Location services are disabled.');
  }

  var permission = await Geolocator.checkPermission();
  if (permission == LocationPermission.denied) {
    permission = await Geolocator.requestPermission();
    if (permission == LocationPermission.denied) {
      throw Exception('Location permissions are denied');
    }
  }
  
  if (permission == LocationPermission.deniedForever) {
    throw Exception('Location permissions are permanently denied, we cannot request permissions.');
  }

  // Stream location
  yield* Geolocator.getPositionStream(
    locationSettings: const LocationSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 10,
    ),
  );
});

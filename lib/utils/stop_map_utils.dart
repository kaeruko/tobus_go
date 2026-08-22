bool hasUsableTransitCoordinate(double latitude, double longitude) {
  if (!latitude.isFinite || !longitude.isFinite) return false;
  if (latitude < -90 || latitude > 90) return false;
  if (longitude < -180 || longitude > 180) return false;

  // StopPoint currently represents a missing coordinate as (0, 0).
  // Do not silently turn that placeholder into a real map destination.
  if (latitude == 0.0 && longitude == 0.0) return false;

  return true;
}

Uri buildGoogleMapsCoordinateUri({
  required double latitude,
  required double longitude,
}) {
  if (!hasUsableTransitCoordinate(latitude, longitude)) {
    throw ArgumentError.value(
      '$latitude,$longitude',
      'coordinate',
      'A valid transit stop coordinate is required',
    );
  }

  return Uri.https('www.google.com', '/maps/search/', {
    'api': '1',
    'query': '$latitude,$longitude',
  });
}

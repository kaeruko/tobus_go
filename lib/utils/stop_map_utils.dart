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

/// Opens a map view centered on the route area without inventing a place pin.
/// Google Maps URLs support integer zoom levels from 0 to 21.
Uri buildGoogleMapsMapViewUri({
  required double latitude,
  required double longitude,
  required int zoom,
}) {
  if (!hasUsableTransitCoordinate(latitude, longitude)) {
    throw ArgumentError.value(
      '$latitude,$longitude',
      'coordinate',
      'A valid map center coordinate is required',
    );
  }
  if (zoom < 0 || zoom > 21) {
    throw RangeError.range(zoom, 0, 21, 'zoom');
  }

  return Uri.https('www.google.com', '/maps/@', {
    'api': '1',
    'map_action': 'map',
    'center': '$latitude,$longitude',
    'zoom': '$zoom',
  });
}

/// Shows the area around a transit stop so people can choose a nearby
/// attraction and read that attraction's reviews in Google Maps.
/// This is not a direct link to a specific business or its reviews.
Uri buildGoogleMapsNearbyAreaUri({
  required double latitude,
  required double longitude,
}) {
  if (!hasUsableTransitCoordinate(latitude, longitude)) {
    throw ArgumentError.value(
      '$latitude,$longitude',
      'coordinate',
      'A valid transit stop coordinate is required for nearby Google Maps',
    );
  }

  return Uri.https('www.google.com', '/maps/@', {
    'api': '1',
    'map_action': 'map',
    'center': '$latitude,$longitude',
    'zoom': '16',
  });
}

Uri buildGoogleMapsWalkingDirectionsUri({
  required double originLatitude,
  required double originLongitude,
  required double destinationLatitude,
  required double destinationLongitude,
}) {
  for (final coordinate in [
    (originLatitude, originLongitude),
    (destinationLatitude, destinationLongitude),
  ]) {
    if (!hasUsableTransitCoordinate(coordinate.$1, coordinate.$2)) {
      throw ArgumentError.value(
        '${coordinate.$1},${coordinate.$2}',
        'coordinate',
        'Two valid transit stop coordinates are required for walking directions',
      );
    }
  }

  return Uri.https('www.google.com', '/maps/dir/', {
    'api': '1',
    'origin': '$originLatitude,$originLongitude',
    'destination': '$destinationLatitude,$destinationLongitude',
    'travelmode': 'walking',
  });
}

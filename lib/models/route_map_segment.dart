import 'package:google_maps_flutter/google_maps_flutter.dart';

/// Geometry for one walking or transit leg. OSM walks carry source attribution.
class RouteMapSegment {
  final String kind; // walk, bus, rail
  final List<LatLng> points;
  final String? source;

  RouteMapSegment({required this.kind, required List<LatLng> points, this.source})
      : points = List<LatLng>.unmodifiable(points) {
    if (kind != 'walk' && kind != 'bus' && kind != 'rail') {
      throw FormatException('Unknown route geometry kind: $kind');
    }
    if (source != null && (source != 'openstreetmap' || kind != 'walk')) {
      throw FormatException('Invalid route geometry source for $kind: $source');
    }
    if (points.length < 2) {
      throw FormatException(
        'Route geometry requires at least two coordinates: kind=$kind',
      );
    }
    for (final point in points) {
      final latitude = point.latitude;
      final longitude = point.longitude;
      if (!latitude.isFinite ||
          !longitude.isFinite ||
          latitude < -90 ||
          latitude > 90 ||
          longitude < -180 ||
          longitude > 180 ||
          (latitude == 0 && longitude == 0)) {
        throw FormatException(
          'Invalid route geometry coordinate: kind=$kind point=$point',
        );
      }
    }
  }

  factory RouteMapSegment.fromJson(Object? raw) {
    if (raw is! Map) {
      throw FormatException('route_geometry entry must be an object: $raw');
    }
    final kind = raw['kind'];
    final rawPoints = raw['points'];
    final source = raw['source'];
    if (source != null && source is! String) {
      throw FormatException('Invalid route geometry source: $source');
    }
    if (kind is! String || rawPoints is! List) {
      throw FormatException('route_geometry requires kind and points: $raw');
    }
    final points = <LatLng>[];
    for (final rawPoint in rawPoints) {
      if (rawPoint is! List ||
          rawPoint.length != 2 ||
          rawPoint[0] is! num ||
          rawPoint[1] is! num) {
        throw FormatException('route_geometry contains invalid point: $rawPoint');
      }
      points.add(
        LatLng(
          (rawPoint[0] as num).toDouble(),
          (rawPoint[1] as num).toDouble(),
        ),
      );
    }
    return RouteMapSegment(kind: kind, points: points, source: source as String?);
  }

  static List<RouteMapSegment> listFromJson(Object? raw) {
    if (raw is! List) {
      throw FormatException('route_geometry must be a list: $raw');
    }
    return List<RouteMapSegment>.unmodifiable(
      raw.map(RouteMapSegment.fromJson),
    );
  }

  Map<String, Object> toJson() => {
        'kind': kind,
        if (source != null) 'source': source!,
        'points': points
            .map((point) => <double>[point.latitude, point.longitude])
            .toList(),
      };
}

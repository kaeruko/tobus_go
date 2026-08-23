import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

class RouteMapPreview extends StatelessWidget {
  final List<LatLng> points;
  const RouteMapPreview({super.key, required this.points});

  LatLng _centerOf(List<LatLng> values) {
    var minLat = values.first.latitude;
    var maxLat = values.first.latitude;
    var minLon = values.first.longitude;
    var maxLon = values.first.longitude;

    for (final point in values.skip(1)) {
      minLat = math.min(minLat, point.latitude);
      maxLat = math.max(maxLat, point.latitude);
      minLon = math.min(minLon, point.longitude);
      maxLon = math.max(maxLon, point.longitude);
    }

    return LatLng(
      (minLat + maxLat) / 2,
      (minLon + maxLon) / 2,
    );
  }

  double _zoomFor(List<LatLng> values) {
    if (values.length == 1) return 15;

    var minLat = values.first.latitude;
    var maxLat = values.first.latitude;
    var minLon = values.first.longitude;
    var maxLon = values.first.longitude;

    for (final point in values.skip(1)) {
      minLat = math.min(minLat, point.latitude);
      maxLat = math.max(maxLat, point.latitude);
      minLon = math.min(minLon, point.longitude);
      maxLon = math.max(maxLon, point.longitude);
    }

    final span = math.max(maxLat - minLat, maxLon - minLon);
    if (span <= 0.003) return 16;
    if (span <= 0.008) return 15;
    if (span <= 0.02) return 14;
    if (span <= 0.05) return 13;
    if (span <= 0.10) return 12;
    if (span <= 0.20) return 11;
    if (span <= 0.40) return 10;
    return 9;
  }

  @override
  Widget build(BuildContext context) {
    final decoration = BoxDecoration(
      color: CupertinoColors.systemGrey6,
      borderRadius: BorderRadius.circular(12),
    );

    if (points.isEmpty) {
      return Container(
        height: 200,
        margin: const EdgeInsets.symmetric(horizontal: 16),
        decoration: decoration,
        alignment: Alignment.center,
        child: const Text(
          '地図情報がありません',
          style: TextStyle(color: CupertinoColors.systemGrey),
        ),
      );
    }

    final center = _centerOf(points);
    final zoom = _zoomFor(points);

    return Container(
      height: 200,
      margin: const EdgeInsets.symmetric(horizontal: 16),
      decoration: decoration,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: GoogleMap(
          initialCameraPosition: CameraPosition(
            target: center,
            zoom: zoom,
          ),
          polylines: points.length >= 2
              ? {
                  Polyline(
                    polylineId: const PolylineId('route'),
                    points: points,
                    color: CupertinoColors.activeBlue,
                    width: 5,
                  ),
                }
              : const {},
          markers: {
            Marker(
              markerId: const MarkerId('start'),
              position: points.first,
              infoWindow: const InfoWindow(title: 'Start'),
            ),
            if (points.length >= 2)
              Marker(
                markerId: const MarkerId('end'),
                position: points.last,
                infoWindow: const InfoWindow(title: 'End'),
              ),
          },
        ),
      ),
    );
  }
}

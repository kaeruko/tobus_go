import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

class RouteReplanComparisonMap extends StatelessWidget {
  final List<LatLng> originalPoints;
  final List<LatLng> newPoints;
  final LatLng anchor;
  final LatLng destination;

  const RouteReplanComparisonMap({
    super.key,
    required this.originalPoints,
    required this.newPoints,
    required this.anchor,
    required this.destination,
  });

  @override
  Widget build(BuildContext context) {
    final allPoints = <LatLng>[
      ...originalPoints,
      ...newPoints,
      anchor,
      destination,
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: SizedBox(
            height: 190,
            child: GoogleMap(
              initialCameraPosition: CameraPosition(
                target: anchor,
                zoom: 13,
              ),
              onMapCreated: (controller) => _fitBounds(controller, allPoints),
              polylines: {
                if (originalPoints.length >= 2)
                  Polyline(
                    polylineId: const PolylineId('original-route'),
                    points: originalPoints,
                    color: Colors.grey.shade600,
                    width: 5,
                  ),
                if (newPoints.length >= 2)
                  Polyline(
                    polylineId: const PolylineId('new-route'),
                    points: newPoints,
                    color: Colors.blue,
                    width: 6,
                  ),
              },
              markers: {
                Marker(
                  markerId: const MarkerId('replan-anchor'),
                  position: anchor,
                  infoWindow: const InfoWindow(title: '経路見直し地点'),
                ),
                Marker(
                  markerId: const MarkerId('destination'),
                  position: destination,
                  infoWindow: const InfoWindow(title: '目的地'),
                ),
              },
              zoomControlsEnabled: false,
              myLocationButtonEnabled: false,
              mapToolbarEnabled: false,
              compassEnabled: false,
              scrollGesturesEnabled: false,
              zoomGesturesEnabled: false,
              rotateGesturesEnabled: false,
              tiltGesturesEnabled: false,
            ),
          ),
        ),
        const SizedBox(height: 8),
        const Wrap(
          spacing: 16,
          runSpacing: 6,
          children: [
            _Legend(color: Colors.grey, label: '現在の予定'),
            _Legend(color: Colors.blue, label: '新しい経路'),
          ],
        ),
      ],
    );
  }

  void _fitBounds(GoogleMapController controller, List<LatLng> points) {
    if (points.isEmpty) return;

    var minLat = points.first.latitude;
    var maxLat = points.first.latitude;
    var minLon = points.first.longitude;
    var maxLon = points.first.longitude;
    for (final point in points.skip(1)) {
      if (point.latitude < minLat) minLat = point.latitude;
      if (point.latitude > maxLat) maxLat = point.latitude;
      if (point.longitude < minLon) minLon = point.longitude;
      if (point.longitude > maxLon) maxLon = point.longitude;
    }

    if ((maxLat - minLat).abs() < 0.000001 &&
        (maxLon - minLon).abs() < 0.000001) {
      controller.moveCamera(CameraUpdate.newLatLngZoom(points.first, 15));
      return;
    }

    controller.moveCamera(
      CameraUpdate.newLatLngBounds(
        LatLngBounds(
          southwest: LatLng(minLat, minLon),
          northeast: LatLng(maxLat, maxLon),
        ),
        32,
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  final Color color;
  final String label;

  const _Legend({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 18,
          height: 4,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 6),
        Text(label, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}

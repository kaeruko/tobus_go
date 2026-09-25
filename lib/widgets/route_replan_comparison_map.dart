import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

class RouteReplanComparisonMap extends StatefulWidget {
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
  State<RouteReplanComparisonMap> createState() =>
      _RouteReplanComparisonMapState();
}

class _RouteReplanComparisonMapState extends State<RouteReplanComparisonMap> {
  GoogleMapController? _controller;

  @override
  void didUpdateWidget(covariant RouteReplanComparisonMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_sameGeometry(oldWidget, widget)) return;

    final controller = _controller;
    if (controller == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !identical(_controller, controller)) return;
      _fitBounds(controller, _allPoints(widget));
    });
  }

  @override
  void dispose() {
    _controller?.dispose();
    _controller = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final allPoints = _allPoints(widget);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: SizedBox(
            height: 190,
            child: GoogleMap(
              initialCameraPosition: CameraPosition(
                target: widget.anchor,
                zoom: 13,
              ),
              onMapCreated: (controller) {
                if (_controller != null) {
                  controller.dispose();
                  throw StateError(
                    '経路比較MapのGoogleMapControllerが重複生成されました',
                  );
                }
                _controller = controller;
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (!mounted || !identical(_controller, controller)) return;
                  _fitBounds(controller, allPoints);
                });
              },
              polylines: {
                if (widget.originalPoints.length >= 2)
                  Polyline(
                    polylineId: const PolylineId('original-route'),
                    points: widget.originalPoints,
                    color: Colors.grey.shade600,
                    width: 5,
                  ),
                if (widget.newPoints.length >= 2)
                  Polyline(
                    polylineId: const PolylineId('new-route'),
                    points: widget.newPoints,
                    color: Colors.blue,
                    width: 6,
                  ),
              },
              markers: {
                Marker(
                  markerId: const MarkerId('replan-anchor'),
                  position: widget.anchor,
                  infoWindow: const InfoWindow(title: '経路見直し地点'),
                ),
                Marker(
                  markerId: const MarkerId('destination'),
                  position: widget.destination,
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

  static List<LatLng> _allPoints(RouteReplanComparisonMap value) {
    return <LatLng>[
      ...value.originalPoints,
      ...value.newPoints,
      value.anchor,
      value.destination,
    ];
  }

  static bool _sameGeometry(
    RouteReplanComparisonMap a,
    RouteReplanComparisonMap b,
  ) {
    return _samePoints(a.originalPoints, b.originalPoints) &&
        _samePoints(a.newPoints, b.newPoints) &&
        a.anchor == b.anchor &&
        a.destination == b.destination;
  }

  static bool _samePoints(List<LatLng> a, List<LatLng> b) {
    if (identical(a, b)) return true;
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
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

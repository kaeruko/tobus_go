import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

class RouteMapPreview extends StatelessWidget {
  final List<LatLng> points;
  const RouteMapPreview({super.key, required this.points});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 200,
      margin: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: CupertinoColors.systemGrey6,
        borderRadius: BorderRadius.circular(12),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: GoogleMap(
          initialCameraPosition: CameraPosition(
            target: points.isNotEmpty ? points.first : const LatLng(35.681236, 139.767125),
            zoom: 13,
          ),
          polylines: {
            Polyline(
              polylineId: const PolylineId('route'),
              points: points,
              color: CupertinoColors.activeBlue,
              width: 5,
            ),
          },
          markers: {
            if (points.isNotEmpty) ...[
              Marker(markerId: const MarkerId('start'), position: points.first, infoWindow: const InfoWindow(title: 'Start')),
              Marker(markerId: const MarkerId('end'), position: points.last, infoWindow: const InfoWindow(title: 'End')),
            ],
          },
        ),
      ),
    );
  }
}

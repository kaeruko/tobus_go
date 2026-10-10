import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/app_localizations.dart';
import '../models/route_map_segment.dart';
import '../utils/stop_map_utils.dart';

class RouteMapPreview extends StatefulWidget {
  final List<LatLng> points;
  final List<RouteMapSegment>? routeGeometry;
  final LatLng? vehiclePosition;
  final bool showOpenButton;
  final double height;
  final EdgeInsetsGeometry margin;
  final bool interactive;
  final bool openExternalOnTap;
  final bool rotateGesturesEnabled;
  final bool tiltGesturesEnabled;
  final bool showUserLocation;

  const RouteMapPreview({
    super.key,
    required this.points,
    this.routeGeometry,
    this.vehiclePosition,
    this.showOpenButton = true,
    this.height = 200,
    this.margin = const EdgeInsets.symmetric(horizontal: 16),
    this.interactive = true,
    this.openExternalOnTap = true,
    this.rotateGesturesEnabled = true,
    this.tiltGesturesEnabled = true,
    this.showUserLocation = false,
  }) : assert(height > 0);

  @override
  State<RouteMapPreview> createState() => _RouteMapPreviewState();
}

class _RouteMapPreviewState extends State<RouteMapPreview> {
  LatLng? _cameraTarget;
  bool _openingMaps = false;

  Future<void> _openGoogleMaps(LatLng point) async {
    if (_openingMaps) return;
    final uri = buildGoogleMapsCoordinateUri(
      latitude: point.latitude,
      longitude: point.longitude,
    );
    setState(() => _openingMaps = true);
    try {
      final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!opened) {
        throw StateError('Google Maps launch returned false: uri=$uri');
      }
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: 'route_map_preview',
          context: ErrorDescription('opening Google Maps: uri=$uri'),
        ),
      );
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      await showCupertinoDialog<void>(
        context: context,
        builder: (dialogContext) => CupertinoAlertDialog(
          title: Text(l10n.googleMapsOpenFailed),
          content: Text('$error\n$uri'),
          actions: [
            CupertinoDialogAction(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: Text(l10n.close),
            ),
          ],
        ),
      );
    } finally {
      if (mounted) setState(() => _openingMaps = false);
    }
  }

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

    return LatLng((minLat + maxLat) / 2, (minLon + maxLon) / 2);
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

  Set<Polyline> _routePolylines(List<LatLng> points) {
    final geometry = widget.routeGeometry;
    if (geometry == null) {
      // Other-city and pre-segmented API responses keep their existing map.
      return points.length >= 2
          ? {
              Polyline(
                polylineId: const PolylineId('route'),
                points: points,
                color: CupertinoColors.activeBlue,
                width: 5,
              ),
            }
          : const {};
    }
    if (geometry.isEmpty && points.length >= 2) {
      throw StateError('Provided route_geometry cannot be empty for a route');
    }
    return {
      for (var index = 0; index < geometry.length; index++)
        Polyline(
          polylineId: PolylineId('route_leg_$index'),
          points: geometry[index].points,
          color: CupertinoColors.activeBlue,
          width: geometry[index].kind == 'walk' ? 4 : 5,
          patterns: geometry[index].kind == 'walk'
              ? <PatternItem>[PatternItem.dash(12), PatternItem.gap(8)]
              : const <PatternItem>[],
        ),
    };
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final points = widget.points;
    final vehiclePosition = widget.vehiclePosition;
    final decoration = BoxDecoration(
      color: CupertinoColors.systemGrey6,
      borderRadius: BorderRadius.circular(12),
    );

    if (points.isEmpty) {
      return Container(
        height: widget.height,
        margin: widget.margin,
        decoration: decoration,
        alignment: Alignment.center,
        child: Text(
          l10n.routeMapUnavailable,
          style: const TextStyle(color: CupertinoColors.systemGrey),
        ),
      );
    }

    final cameraPoints = <LatLng>[
      ...points,
      if (vehiclePosition != null) vehiclePosition,
    ];
    final center = _centerOf(cameraPoints);
    final zoom = _zoomFor(cameraPoints);

    return Container(
      height: widget.height,
      margin: widget.margin,
      decoration: decoration,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Stack(
          fit: StackFit.expand,
          children: [
            GoogleMap(
              gestureRecognizers: widget.interactive
                  ? <Factory<OneSequenceGestureRecognizer>>{
                      Factory<EagerGestureRecognizer>(
                        EagerGestureRecognizer.new,
                      ),
                    }
                  : const <Factory<OneSequenceGestureRecognizer>>{},
              onCameraMove: widget.interactive
                  ? (position) => _cameraTarget = position.target
                  : null,
              onTap: widget.interactive && widget.openExternalOnTap
                  ? _openGoogleMaps
                  : null,
              mapToolbarEnabled: false,
              myLocationEnabled: widget.showUserLocation,
              myLocationButtonEnabled: widget.showUserLocation,
              scrollGesturesEnabled: widget.interactive,
              zoomGesturesEnabled: widget.interactive,
              rotateGesturesEnabled:
                  widget.interactive && widget.rotateGesturesEnabled,
              tiltGesturesEnabled:
                  widget.interactive && widget.tiltGesturesEnabled,
              initialCameraPosition: CameraPosition(target: center, zoom: zoom),
              polylines: _routePolylines(points),
              markers: {
                Marker(
                  markerId: const MarkerId('start'),
                  position: points.first,
                  onTap: widget.interactive && widget.openExternalOnTap
                      ? () => _openGoogleMaps(points.first)
                      : null,
                  consumeTapEvents:
                      widget.interactive && widget.openExternalOnTap,
                  infoWindow: InfoWindow(title: l10n.routeMapStart),
                ),
                if (points.length >= 2)
                  Marker(
                    markerId: const MarkerId('end'),
                    position: points.last,
                    onTap: widget.interactive && widget.openExternalOnTap
                        ? () => _openGoogleMaps(points.last)
                        : null,
                    consumeTapEvents:
                        widget.interactive && widget.openExternalOnTap,
                    infoWindow: InfoWindow(title: l10n.routeMapEnd),
                  ),
                if (vehiclePosition != null)
                  Marker(
                    markerId: const MarkerId('realtime_vehicle'),
                    position: vehiclePosition,
                    onTap: widget.interactive && widget.openExternalOnTap
                        ? () => _openGoogleMaps(vehiclePosition)
                        : null,
                    consumeTapEvents:
                        widget.interactive && widget.openExternalOnTap,
                    infoWindow: InfoWindow(title: l10n.busCurrentPosition),
                    icon: BitmapDescriptor.defaultMarkerWithHue(
                      BitmapDescriptor.hueAzure,
                    ),
                  ),
              },
            ),
            if (widget.showOpenButton && widget.interactive)
              Positioned(
                top: 8,
                right: 8,
                child: CupertinoButton(
                  color: CupertinoColors.systemBackground.resolveFrom(context),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                  onPressed: _openingMaps
                      ? null
                      : () => _openGoogleMaps(_cameraTarget ?? center),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(
                        CupertinoIcons.arrow_up_right_square,
                        size: 18,
                      ),
                      const SizedBox(width: 6),
                      Text(l10n.openInGoogleMaps),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

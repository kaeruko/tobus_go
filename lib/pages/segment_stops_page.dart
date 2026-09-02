import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/route_models.dart';
import '../utils/stop_map_utils.dart';

class SegmentStopsPage extends StatelessWidget {
  final StepSeg segment;

  const SegmentStopsPage({
    super.key,
    required this.segment,
  });

  void _popToPreviousAppPage(BuildContext context) {
    final navigator = Navigator.of(context);
    if (!navigator.canPop()) {
      throw StateError(
        'SegmentStopsPage must be pushed onto a Navigator stack with a '
        'previous app route: stepId=${segment.stepId}',
      );
    }
    navigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        automaticallyImplyLeading: false,
        leading: CupertinoNavigationBarBackButton(
          key: const ValueKey('segment-stops-back'),
          onPressed: () => _popToPreviousAppPage(context),
        ),
        middle: Text(
          segment.title.isEmpty ? segment.mainTitle : segment.title,
        ),
      ),
      child: SafeArea(
        child: ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          itemCount: segment.stops.length,
          itemBuilder: (context, index) {
            final stop = segment.stops[index];
            final isFirst = index == 0;
            final isLast = index == segment.stops.length - 1;

            return _StopRow(
              stop: stop,
              isFirst: isFirst,
              isLast: isLast,
            );
          },
        ),
      ),
    );
  }
}

class _StopRow extends StatelessWidget {
  final StopPoint stop;
  final bool isFirst;
  final bool isLast;

  const _StopRow({
    required this.stop,
    required this.isFirst,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final hasMap = hasUsableTransitCoordinate(stop.lat, stop.lon);
    final nameStyle = TextStyle(
      fontSize: 16,
      fontWeight:
          (stop.isOrigin || stop.isDestination)
              ? FontWeight.w600
              : FontWeight.w400,
    );

    final row = Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 32,
          child: Column(
            children: [
              Container(
                width: 20,
                height: 20,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: CupertinoColors.activeGreen,
                    width: 2,
                  ),
                  color:
                      stop.isOrigin || stop.isDestination
                          ? CupertinoColors.activeGreen
                          : CupertinoColors.white,
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 42,
                  color: CupertinoColors.systemGrey4,
                ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(stop.name, style: nameStyle),
                if (stop.isOrigin || stop.isDestination) ...[
                  const SizedBox(height: 2),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: CupertinoColors.systemGrey5,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      stop.isOrigin
                          ? '乗車'
                          : (stop.isDestination ? '降車' : ''),
                      style: const TextStyle(
                        fontSize: 10,
                        color: CupertinoColors.inactiveGray,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        if (hasMap)
          const Padding(
            padding: EdgeInsets.only(top: 1),
            child: Icon(
              CupertinoIcons.map,
              size: 18,
              color: CupertinoColors.systemGrey,
            ),
          ),
      ],
    );

    if (!hasMap) return row;

    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => _showStopMap(context, stop),
      child: row,
    );
  }
}

Future<void> _showStopMap(BuildContext context, StopPoint stop) {
  if (!hasUsableTransitCoordinate(stop.lat, stop.lon)) {
    throw StateError(
      'Cannot show stop map without a valid coordinate: '
      'stop=${stop.name}, lat=${stop.lat}, lon=${stop.lon}',
    );
  }

  return showCupertinoModalPopup<void>(
    context: context,
    builder: (context) => _StopMapSheet(stop: stop),
  );
}

class _StopMapSheet extends StatelessWidget {
  final StopPoint stop;

  const _StopMapSheet({required this.stop});

  Future<void> _openGoogleMaps(BuildContext context) async {
    final uri = buildGoogleMapsCoordinateUri(
      latitude: stop.lat,
      longitude: stop.lon,
    );
    final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (opened || !context.mounted) return;

    await showCupertinoDialog<void>(
      context: context,
      builder: (dialogContext) => CupertinoAlertDialog(
        title: const Text('Google Mapsを開けませんでした'),
        content: Text(uri.toString()),
        actions: [
          CupertinoDialogAction(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('閉じる'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final target = LatLng(stop.lat, stop.lon);

    return CupertinoPopupSurface(
      isSurfacePainted: true,
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 430,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 8, 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        stop.name,
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    CupertinoButton(
                      padding: const EdgeInsets.all(8),
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Icon(CupertinoIcons.xmark_circle_fill),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: GoogleMap(
                      initialCameraPosition: CameraPosition(
                        target: target,
                        zoom: 17,
                      ),
                      markers: {
                        Marker(
                          markerId: MarkerId(stop.stopId ?? stop.name),
                          position: target,
                          infoWindow: InfoWindow(title: stop.name),
                        ),
                      },
                      myLocationEnabled: false,
                      myLocationButtonEnabled: false,
                      mapToolbarEnabled: false,
                      zoomControlsEnabled: false,
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                child: SizedBox(
                  width: double.infinity,
                  child: CupertinoButton.filled(
                    onPressed: () => _openGoogleMaps(context),
                    child: const Text('Google Mapsで開く'),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

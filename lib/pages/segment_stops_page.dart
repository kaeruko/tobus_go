import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/app_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../models/route_models.dart';
import '../utils/stop_map_utils.dart';
import '../widgets/route_map_preview.dart';
import '../widgets/timetable_view.dart';

class SegmentStopsPage extends StatefulWidget {
  final StepSeg segment;

  const SegmentStopsPage({
    super.key,
    required this.segment,
  });

  @override
  State<SegmentStopsPage> createState() => _SegmentStopsPageState();
}

class _SegmentStopsPageState extends State<SegmentStopsPage> {
  bool _expanded = true;

  void _popToPreviousAppPage(BuildContext context) {
    final navigator = Navigator.of(context);
    if (!navigator.canPop()) {
      throw StateError(
        'SegmentStopsPage must be pushed onto a Navigator stack with a '
        'previous app route: stepId=${widget.segment.stepId}',
      );
    }
    navigator.pop();
  }

  List<LatLng> get _mapPoints => widget.segment.stops
      .where((stop) => hasUsableTransitCoordinate(stop.lat, stop.lon))
      .map((stop) => LatLng(stop.lat, stop.lon))
      .toList(growable: false);

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);

    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        automaticallyImplyLeading: false,
        leading: CupertinoNavigationBarBackButton(
          key: const ValueKey('segment-stops-back'),
          onPressed: () => _popToPreviousAppPage(context),
        ),
        middle: Text(l10n.segmentGuideTitle),
      ),
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            CupertinoButton(
              key: const ValueKey('segment-guide-toggle'),
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
              onPressed: () => setState(() => _expanded = !_expanded),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      localizedRideTitle(locale, widget.segment),
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                        color: CupertinoColors.label,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Icon(
                    _expanded
                        ? CupertinoIcons.chevron_up
                        : CupertinoIcons.chevron_down,
                    size: 20,
                    color: CupertinoColors.secondaryLabel,
                  ),
                ],
              ),
            ),
            Container(
              height: 0.5,
              color: CupertinoColors.separator,
            ),
            if (_expanded) ...[
              const SizedBox(height: 12),
              KeyedSubtree(
                key: const ValueKey('segment-route-map'),
                child: RouteMapPreview(
                  points: _mapPoints,
                  showOpenButton: false,
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
                child: _SegmentSummary(segment: widget.segment),
              ),
              Container(
                height: 0.5,
                margin: const EdgeInsets.symmetric(horizontal: 16),
                color: CupertinoColors.separator,
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
                child: Column(
                  children: [
                    for (var index = 0;
                        index < widget.segment.stops.length;
                        index++)
                      _StopRow(
                        segment: widget.segment,
                        stop: widget.segment.stops[index],
                        isFirst: index == 0,
                        isLast: index == widget.segment.stops.length - 1,
                      ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SegmentSummary extends StatelessWidget {
  final StepSeg segment;

  const _SegmentSummary({required this.segment});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final departure = segment.departureTime?.trim();
    final arrival = segment.arrivalTime?.trim();
    final hasDeparture = departure != null && departure.isNotEmpty;
    final hasArrival = arrival != null && arrival.isNotEmpty;

    return Row(
      children: [
        if (hasDeparture)
          Text(
            l10n.segmentDepartureAt(departure),
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
            ),
          ),
        Expanded(
          child: Text(
            l10n.segmentRideSummary(segment.minutes, segment.stops.length),
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 13,
              color: CupertinoColors.secondaryLabel,
            ),
          ),
        ),
        if (hasArrival)
          Text(
            l10n.segmentArrivalAt(arrival),
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
            ),
          ),
      ],
    );
  }
}

class _StopRow extends StatelessWidget {
  final StepSeg segment;
  final StopPoint stop;
  final bool isFirst;
  final bool isLast;

  const _StopRow({
    required this.segment,
    required this.stop,
    required this.isFirst,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final stopName = localizedStopName(locale, stop);
    final hasMap = hasUsableTransitCoordinate(stop.lat, stop.lon);
    final routeId = segment.routeId?.trim();
    final stopId = stop.stopId?.trim();
    final hasTimetable =
        segment.kind == 'bus' &&
        routeId != null &&
        routeId.isNotEmpty &&
        stopId != null &&
        stopId.isNotEmpty;
    final isEndpoint = isFirst || isLast;
    final endpointTime = isFirst
        ? segment.departureTime?.trim()
        : (isLast ? segment.arrivalTime?.trim() : null);
    final endpointTimeLabel =
        endpointTime == null || endpointTime.isEmpty
            ? null
            : (isFirst
                  ? l10n.segmentDepartureAt(endpointTime)
                  : l10n.segmentArrivalAt(endpointTime));

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 30,
            child: Stack(
              alignment: Alignment.topCenter,
              children: [
                if (!isFirst)
                  const Positioned(
                    top: 0,
                    height: 10,
                    child: SizedBox(
                      width: 2,
                      child: ColoredBox(color: CupertinoColors.systemGrey4),
                    ),
                  ),
                if (!isLast)
                  const Positioned(
                    top: 10,
                    bottom: 0,
                    child: SizedBox(
                      width: 2,
                      child: ColoredBox(color: CupertinoColors.systemGrey4),
                    ),
                  ),
                Positioned(
                  top: 1,
                  child: Container(
                    width: isEndpoint ? 20 : 14,
                    height: isEndpoint ? 20 : 14,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: CupertinoColors.activeGreen,
                        width: 2,
                      ),
                      color: isEndpoint
                          ? CupertinoColors.activeGreen
                          : CupertinoColors.systemBackground,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: isLast ? 0 : 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (isEndpoint) ...[
                    Row(
                      children: [
                        Container(
                          width: 22,
                          height: 22,
                          decoration: BoxDecoration(
                            color: CupertinoColors.activeBlue.withValues(
                              alpha: 0.12,
                            ),
                            borderRadius: BorderRadius.circular(5),
                          ),
                          alignment: Alignment.center,
                          child: const Icon(
                            CupertinoIcons.bus,
                            size: 15,
                            color: CupertinoColors.activeBlue,
                          ),
                        ),
                        const SizedBox(width: 7),
                        Text(
                          isFirst ? l10n.boarding : l10n.alighting,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: CupertinoColors.secondaryLabel,
                          ),
                        ),
                        const Spacer(),
                        if (endpointTimeLabel != null)
                          Text(
                            endpointTimeLabel,
                            style: const TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: CupertinoColors.label,
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 4),
                  ],
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          stopName,
                          style: TextStyle(
                            fontSize: isEndpoint ? 17 : 15,
                            fontWeight:
                                isEndpoint ? FontWeight.w700 : FontWeight.w400,
                            color: CupertinoColors.label,
                          ),
                        ),
                      ),
                      if (hasTimetable)
                        CupertinoButton(
                          key: ValueKey('stop-timetable-${stop.stopId}'),
                          minSize: 30,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 5,
                            vertical: 2,
                          ),
                          onPressed: () => _showStopTimetable(
                            context,
                            segment: segment,
                            stop: stop,
                          ),
                          child: const Icon(
                            CupertinoIcons.clock,
                            size: 18,
                            color: CupertinoColors.systemGrey,
                          ),
                        ),
                      if (hasMap)
                        CupertinoButton(
                          key: ValueKey(
                            'stop-map-${stop.stopId ?? stop.name}',
                          ),
                          minSize: 30,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 5,
                            vertical: 2,
                          ),
                          onPressed: () => _showStopMap(context, stop),
                          child: const Icon(
                            CupertinoIcons.map,
                            size: 18,
                            color: CupertinoColors.systemGrey,
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

Future<void> _showStopTimetable(
  BuildContext context, {
  required StepSeg segment,
  required StopPoint stop,
}) {
  final routeId = segment.routeId?.trim();
  final stopId = stop.stopId?.trim();
  if (segment.kind != 'bus' ||
      routeId == null ||
      routeId.isEmpty ||
      stopId == null ||
      stopId.isEmpty) {
    throw StateError(
      'Cannot show stop timetable without bus route/stop IDs: '
      'stepId=${segment.stepId}, routeId=${segment.routeId}, '
      'stopId=${stop.stopId}',
    );
  }

  final targetPoleId = segment.stops.isEmpty
      ? null
      : segment.stops.last.stopId?.trim();

  return showCupertinoModalPopup<void>(
    context: context,
    builder: (context) => _StopTimetableSheet(
      segment: segment,
      stop: stop,
      routeId: routeId,
      stopId: stopId,
      targetPoleId:
          targetPoleId == null || targetPoleId.isEmpty ? null : targetPoleId,
    ),
  );
}

class _StopTimetableSheet extends StatelessWidget {
  final StepSeg segment;
  final StopPoint stop;
  final String routeId;
  final String stopId;
  final String? targetPoleId;

  const _StopTimetableSheet({
    required this.segment,
    required this.stop,
    required this.routeId,
    required this.stopId,
    required this.targetPoleId,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final stopName = localizedStopName(locale, stop);

    return CupertinoPopupSurface(
      isSurfacePainted: true,
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * 0.78,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            l10n.timetableAtStop(stopName),
                            style: const TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            localizedRideTitle(locale, segment),
                            style: const TextStyle(
                              fontSize: 13,
                              color: CupertinoColors.secondaryLabel,
                            ),
                          ),
                        ],
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
              Container(
                height: 0.5,
                color: CupertinoColors.separator,
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
                  child: TimetableView(
                    routeId: routeId,
                    stopId: stopId,
                    targetPoleId: targetPoleId,
                    limit: 3,
                    showEmptyState: true,
                    showFullDay: true,
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
      builder: (dialogContext) {
        final l10n = AppLocalizations.of(dialogContext);
        return CupertinoAlertDialog(
          title: Text(l10n.googleMapsOpenFailed),
          content: Text(uri.toString()),
          actions: [
            CupertinoDialogAction(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: Text(l10n.close),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context);
    final stopName = localizedStopName(locale, stop);
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
                        stopName,
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
                          infoWindow: InfoWindow(title: stopName),
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
                    child: Text(AppLocalizations.of(context).openInGoogleMaps),
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

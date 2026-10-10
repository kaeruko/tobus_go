import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/transit_name_localizations.dart';
import '../logic/transfer_walk_details.dart';
import '../models/route_models.dart';
import '../utils/stop_map_utils.dart';

Future<void> showTransferWalkSheet(
  BuildContext context,
  TransferWalkDetails transfer,
) {
  return showCupertinoModalPopup<void>(
    context: context,
    builder: (context) => _TransferWalkSheet(transfer: transfer),
  );
}

class _TransferWalkSheet extends StatelessWidget {
  final TransferWalkDetails transfer;

  const _TransferWalkSheet({required this.transfer});

  Future<void> _openWalkingDirections(BuildContext context) async {
    final uri = buildGoogleMapsWalkingDirectionsUri(
      originLatitude: transfer.alightingStop.lat,
      originLongitude: transfer.alightingStop.lon,
      destinationLatitude: transfer.boardingStop.lat,
      destinationLongitude: transfer.boardingStop.lon,
    );
    try {
      final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!opened) {
        throw StateError('Google Maps walking directions launch failed: $uri');
      }
    } catch (error, stackTrace) {
      FlutterError.reportError(FlutterErrorDetails(
        exception: error,
        stack: stackTrace,
        library: 'transfer_walk_sheet',
        context: ErrorDescription('opening transfer walking directions: $uri'),
      ));
      if (!context.mounted) return;
      await showCupertinoDialog<void>(
        context: context,
        builder: (dialogContext) => CupertinoAlertDialog(
          title: Text(_label(dialogContext, '地図を開けませんでした', 'Could not open maps')),
          content: Text('$error\n$uri'),
          actions: [
            CupertinoDialogAction(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: Text(_label(dialogContext, '閉じる', 'Close')),
            ),
          ],
        ),
      );
    }
  }

  static String _label(BuildContext context, String ja, String en) {
    return Localizations.localeOf(context).languageCode == 'ja' ? ja : en;
  }

  Widget _stopSummary(
    BuildContext context, {
    required StopPoint stop,
    required String clock,
    required StepSeg ride,
    required String labelJa,
    required String labelEn,
    required Color color,
  }) {
    final locale = Localizations.localeOf(context);
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _label(context, labelJa, labelEn),
            style: const TextStyle(fontSize: 12, color: CupertinoColors.systemGrey),
          ),
          Text(
            clock,
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.bold,
              color: color,
            ),
          ),
          Text(
            localizedStopName(locale, stop),
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 3),
          Text(
            localizedRideTitle(locale, ride),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 12, color: CupertinoColors.systemGrey),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final a = transfer.alightingStop;
    final b = transfer.boardingStop;
    final boundsSpan = math.max(
      (a.lat - b.lat).abs(),
      (a.lon - b.lon).abs(),
    );
    final zoom = boundsSpan < 0.001
        ? 17.0
        : boundsSpan < 0.003
            ? 16.0
            : boundsSpan < 0.008
                ? 15.0
                : boundsSpan < 0.02
                    ? 14.0
                    : 12.0;

    return CupertinoPopupSurface(
      isSurfacePainted: true,
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: math.min(650, MediaQuery.sizeOf(context).height * 0.85),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        _label(context, '乗換案内', 'Transfer guide'),
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                      ),
                    ),
                    CupertinoButton(
                      padding: const EdgeInsets.all(4),
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Icon(CupertinoIcons.xmark_circle_fill),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _stopSummary(
                      context,
                      stop: a,
                      clock: transfer.alightingTime,
                      ride: transfer.arrivingRide,
                      labelJa: '降車予定',
                      labelEn: 'Get off',
                      color: CupertinoColors.systemOrange,
                    ),
                    const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 16),
                      child: Icon(CupertinoIcons.arrow_right, size: 18),
                    ),
                    _stopSummary(
                      context,
                      stop: b,
                      clock: transfer.boardingTime,
                      ride: transfer.departingRide,
                      labelJa: '乗車予定',
                      labelEn: 'Board',
                      color: CupertinoColors.activeGreen,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  _label(
                    context,
                    '🚶 約${transfer.walkingStep.minutes}分'
                        '${transfer.waitingStep == null ? '' : ' ・ 🕒 約${transfer.waitingStep!.minutes}分'}',
                    '🚶 ~${transfer.walkingStep.minutes} min'
                        '${transfer.waitingStep == null ? '' : ' · 🕒 ~${transfer.waitingStep!.minutes} min'}',
                  ),
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: GoogleMap(
                      initialCameraPosition: CameraPosition(
                        target: LatLng((a.lat + b.lat) / 2, (a.lon + b.lon) / 2),
                        zoom: zoom,
                      ),
                      markers: {
                        Marker(
                          markerId: const MarkerId('transfer_alight'),
                          position: LatLng(a.lat, a.lon),
                          icon: BitmapDescriptor.defaultMarkerWithHue(
                            BitmapDescriptor.hueOrange,
                          ),
                          infoWindow: InfoWindow(
                            title: localizedStopName(Localizations.localeOf(context), a),
                          ),
                        ),
                        Marker(
                          markerId: const MarkerId('transfer_board'),
                          position: LatLng(b.lat, b.lon),
                          icon: BitmapDescriptor.defaultMarkerWithHue(
                            BitmapDescriptor.hueGreen,
                          ),
                          infoWindow: InfoWindow(
                            title: localizedStopName(Localizations.localeOf(context), b),
                          ),
                        ),
                      },
                      // Do not draw a straight line and misrepresent it as a
                      // pedestrian route; Google Maps handles actual directions.
                      myLocationEnabled: false,
                      myLocationButtonEnabled: false,
                      mapToolbarEnabled: false,
                      zoomControlsEnabled: false,
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                CupertinoButton.filled(
                  onPressed: () => _openWalkingDirections(context),
                  child: Text(_label(
                    context,
                    'Googleマップで徒歩ルートを見る',
                    'Walking directions in Google Maps',
                  )),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

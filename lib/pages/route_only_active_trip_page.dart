import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../core/api_client.dart';
import '../core/city_profile.dart';
import '../models/route_models.dart';
import '../widgets/route_map_preview.dart';

class RouteOnlyActiveTripPage extends StatefulWidget {
  final Candidate candidate;

  const RouteOnlyActiveTripPage({
    super.key,
    required this.candidate,
  });

  @override
  State<RouteOnlyActiveTripPage> createState() =>
      _RouteOnlyActiveTripPageState();
}

class _RouteOnlyActiveTripPageState extends State<RouteOnlyActiveTripPage> {
  Timer? _timer;
  Map<String, dynamic>? _vehicle;
  String? _realtimeMessage;
  bool _loadingRealtime = false;

  StepSeg? get _trackedBusStep {
    for (final step in widget.candidate.steps) {
      if (step.kind == 'bus' &&
          step.routeId != null &&
          step.routeId!.isNotEmpty &&
          step.tripId != null &&
          step.tripId!.isNotEmpty) {
        return step;
      }
    }
    return null;
  }

  bool get _supportsVehiclePosition =>
      configuredCityProfile.capabilities.realtime.vehiclePosition;

  LatLng? get _vehiclePosition {
    final vehicle = _vehicle;
    if (vehicle == null) return null;
    final lat = vehicle['vehicle_lat'];
    final lon = vehicle['vehicle_lon'];
    if (lat is! num || lon is! num) return null;
    return LatLng(lat.toDouble(), lon.toDouble());
  }

  @override
  void initState() {
    super.initState();
    if (_supportsVehiclePosition && _trackedBusStep != null) {
      _refreshRealtime(forceRefresh: true);
      _timer = Timer.periodic(
        const Duration(seconds: 30),
        (_) => _refreshRealtime(),
      );
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refreshRealtime({bool forceRefresh = false}) async {
    final step = _trackedBusStep;
    if (step == null || !_supportsVehiclePosition || _loadingRealtime) return;

    setState(() {
      _loadingRealtime = true;
    });
    try {
      final payload = await ApiClient.fetchBusLocation(
        routeId: step.routeId!,
        tripId: step.tripId!,
        forceRefresh: forceRefresh,
      );
      _validateVehiclePayload(payload);
      if (!mounted) return;
      setState(() {
        _vehicle = payload;
        _realtimeMessage = null;
        _loadingRealtime = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _vehicle = null;
        _loadingRealtime = false;
        if (error.statusCode == 404) {
          _realtimeMessage = 'この便のリアルタイム位置はまだ見つかりません';
        } else {
          _realtimeMessage = 'リアルタイム取得エラー: $error';
        }
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _vehicle = null;
        _loadingRealtime = false;
        _realtimeMessage = 'リアルタイム応答エラー: $error';
      });
    }
  }

  void _validateVehiclePayload(Map<String, dynamic> payload) {
    final vehicleId = payload['vehicle_id'] ?? payload['odpt:bus'];
    final lat = payload['vehicle_lat'];
    final lon = payload['vehicle_lon'];
    final tripId = payload['trip_id'];
    final step = _trackedBusStep;

    if (vehicleId is! String || vehicleId.isEmpty) {
      throw const FormatException('vehicle_id is missing');
    }
    if (lat is! num || lon is! num) {
      throw const FormatException('vehicle latitude/longitude are missing');
    }
    if (!lat.toDouble().isFinite || !lon.toDouble().isFinite) {
      throw const FormatException('vehicle latitude/longitude are not finite');
    }
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      throw const FormatException('vehicle latitude/longitude are out of range');
    }
    if (lat == 0 && lon == 0) {
      throw const FormatException('vehicle latitude/longitude must not be (0,0)');
    }
    if (step == null || tripId != step.tripId) {
      throw FormatException(
        'vehicle trip_id mismatch: expected=${step?.tripId} actual=$tripId',
      );
    }
  }

  Widget _realtimeCard(BuildContext context) {
    final step = _trackedBusStep;
    if (step == null) {
      return _messageCard(context, 'この経路には追跡できるバス便がありません');
    }
    if (!_supportsVehiclePosition) {
      return _messageCard(
        context,
        '${configuredCityProfile.appName}ではバス現在位置は未対応です',
      );
    }
    if (_loadingRealtime && _vehicle == null) {
      return const Padding(
        padding: EdgeInsets.all(20),
        child: Center(child: CupertinoActivityIndicator()),
      );
    }
    final message = _realtimeMessage;
    if (message != null) {
      return _messageCard(context, message);
    }
    final vehicle = _vehicle;
    if (vehicle == null) {
      return _messageCard(context, 'リアルタイム位置を取得していません');
    }

    final lat = (vehicle['vehicle_lat'] as num).toDouble();
    final lon = (vehicle['vehicle_lon'] as num).toDouble();
    final vehicleId = (vehicle['vehicle_id'] ?? vehicle['odpt:bus']).toString();
    final stopName = vehicle['raw_stop_name']?.toString();
    final beforeFirstStop = vehicle['before_first_stop'] == true;
    final serverNow = vehicle['server_now']?.toString();

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGreen.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'バス現在位置',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 6),
            Text('車両 $vehicleId'),
            if (beforeFirstStop)
              const Text('バスは始発停留所へ向かっています'),
            if (!beforeFirstStop && stopName != null && stopName.isNotEmpty)
              Text('現在の停留所付近: $stopName'),
            if (beforeFirstStop && stopName != null && stopName.isNotEmpty)
              Text('始発停留所: $stopName'),
            Text('緯度 ${lat.toStringAsFixed(5)} / 経度 ${lon.toStringAsFixed(5)}'),
            if (serverNow != null) Text('取得時刻 $serverNow'),
            const SizedBox(height: 8),
            const Text(
              '30秒ごとに更新します',
              style: TextStyle(color: CupertinoColors.systemGrey, fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }

  Widget _messageCard(BuildContext context, String message) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6.resolveFrom(context),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(message),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(middle: Text('移動中')),
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.only(top: 16, bottom: 32),
          children: [
            if (widget.candidate.points.isNotEmpty) ...[
              RouteMapPreview(
                points: widget.candidate.points,
                vehiclePosition: _vehiclePosition,
              ),
              const SizedBox(height: 16),
            ],
            _realtimeCard(context),
            if (_supportsVehiclePosition && _trackedBusStep != null) ...[
              const SizedBox(height: 8),
              Center(
                child: CupertinoButton(
                  onPressed: _loadingRealtime
                      ? null
                      : () => _refreshRealtime(forceRefresh: true),
                  child: const Text('現在位置を更新'),
                ),
              ),
            ],
            const SizedBox(height: 12),
            for (final step in widget.candidate.steps)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 5, 16, 5),
                child: Text(
                  '${step.mainTitle}${step.subTitle == null ? '' : '  ${step.subTitle}'}',
                ),
              ),
            const SizedBox(height: 20),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: CupertinoButton.filled(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('移動を終了'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

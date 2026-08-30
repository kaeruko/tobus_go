import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../core/city_profile.dart';
import '../models/route_models.dart';
import '../services/bus_location_source.dart';
import '../widgets/route_map_preview.dart';

class RouteOnlyActiveTripPage extends StatefulWidget {
  final Candidate candidate;
  final BusLocationSource? busLocationSource;

  const RouteOnlyActiveTripPage({
    super.key,
    required this.candidate,
    this.busLocationSource,
  });

  @override
  State<RouteOnlyActiveTripPage> createState() =>
      _RouteOnlyActiveTripPageState();
}

class _RouteOnlyActiveTripPageState extends State<RouteOnlyActiveTripPage> {
  Timer? _timer;
  BusLocation? _vehicle;
  String? _realtimeMessage;
  bool _loadingRealtime = false;

  BusLocationSource get _busLocationSource =>
      widget.busLocationSource ?? const RealtimeBusLocationSource();

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
    final lat = vehicle.vehicleLat;
    final lon = vehicle.vehicleLon;
    if (lat == null || lon == null) {
      throw StateError(
        'BusLocationSource returned a vehicle without latitude/longitude',
      );
    }
    return LatLng(lat, lon);
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
      final location = await _busLocationSource.fetch(
        routeId: step.routeId!,
        tripId: step.tripId!,
        forceRefresh: forceRefresh,
      );
      if (location.vehicleLat == null || location.vehicleLon == null) {
        throw StateError(
          'BusLocationSource returned a vehicle without latitude/longitude',
        );
      }
      if (!mounted) return;
      setState(() {
        _vehicle = location;
        _realtimeMessage = null;
        _loadingRealtime = false;
      });
    } on BusLocationNotAvailableException catch (_) {
      if (!mounted) return;
      setState(() {
        _vehicle = null;
        _loadingRealtime = false;
        _realtimeMessage = 'この便のリアルタイム位置はまだ見つかりません';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _vehicle = null;
        _loadingRealtime = false;
        _realtimeMessage = 'リアルタイム取得エラー: $error';
      });
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

    final lat = vehicle.vehicleLat!;
    final lon = vehicle.vehicleLon!;
    final stopName = vehicle.rawStopName;

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
            Text('車両 ${vehicle.vehicleId}'),
            if (vehicle.beforeFirstStop)
              const Text('バスは始発停留所へ向かっています'),
            if (!vehicle.beforeFirstStop &&
                stopName != null &&
                stopName.isNotEmpty)
              Text('現在の停留所付近: $stopName'),
            if (vehicle.beforeFirstStop &&
                stopName != null &&
                stopName.isNotEmpty)
              Text('始発停留所: $stopName'),
            Text('緯度 ${lat.toStringAsFixed(5)} / 経度 ${lon.toStringAsFixed(5)}'),
            if (vehicle.serverNow != null) Text('取得時刻 ${vehicle.serverNow}'),
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

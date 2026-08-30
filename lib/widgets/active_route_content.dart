import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../core/city_profile.dart';
import '../models/route_models.dart';
import '../services/bus_location_source.dart';
import 'route_detail_widgets.dart';
import 'route_map_preview.dart';

class ActiveRouteContent extends StatefulWidget {
  final Candidate candidate;
  final CityProfile cityProfile;
  final BusLocationSource? busLocationSource;
  final VoidCallback? onEnd;

  const ActiveRouteContent({
    super.key,
    required this.candidate,
    required this.cityProfile,
    this.busLocationSource,
    this.onEnd,
  });

  @override
  State<ActiveRouteContent> createState() => _ActiveRouteContentState();
}

class _ActiveRouteContentState extends State<ActiveRouteContent> {
  Timer? _timer;
  BusLocation? _vehicle;
  String? _realtimeMessage;
  bool _loadingRealtime = false;

  BusLocationSource get _source =>
      widget.busLocationSource ??
      RealtimeBusLocationSource(cityProfile: widget.cityProfile);

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
      widget.cityProfile.capabilities.realtime.vehiclePosition;

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

    setState(() => _loadingRealtime = true);
    try {
      final location = await _source.fetch(
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
    } on BusLocationNotAvailableException {
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

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.only(top: 16, bottom: 32),
      children: [
        if (widget.candidate.points.isNotEmpty) ...[
          RouteMapPreview(
            points: widget.candidate.points,
            vehiclePosition: _vehiclePosition,
          ),
          const SizedBox(height: 16),
        ],
        BusRealtimeCard(
          cityProfile: widget.cityProfile,
          trackedBusStep: _trackedBusStep,
          vehicle: _vehicle,
          loading: _loadingRealtime,
          message: _realtimeMessage,
        ),
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
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: RouteStepTile(segment: step),
          ),
        if (widget.onEnd != null) ...[
          const SizedBox(height: 4),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: CupertinoButton.filled(
              onPressed: widget.onEnd,
              child: const Text('移動を終了'),
            ),
          ),
        ],
      ],
    );
  }
}

class BusRealtimeCard extends StatelessWidget {
  final CityProfile cityProfile;
  final StepSeg? trackedBusStep;
  final BusLocation? vehicle;
  final bool loading;
  final String? message;

  const BusRealtimeCard({
    super.key,
    required this.cityProfile,
    required this.trackedBusStep,
    required this.vehicle,
    required this.loading,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    if (trackedBusStep == null) {
      return _messageCard(context, 'この経路には追跡できるバス便がありません');
    }
    if (!cityProfile.capabilities.realtime.vehiclePosition) {
      return _messageCard(context, '${cityProfile.appName}ではバス現在位置は未対応です');
    }
    if (loading && vehicle == null) {
      return const Padding(
        padding: EdgeInsets.all(20),
        child: Center(child: CupertinoActivityIndicator()),
      );
    }
    if (message != null) return _messageCard(context, message!);
    final current = vehicle;
    if (current == null) {
      return _messageCard(context, 'リアルタイム位置を取得していません');
    }

    final lat = current.vehicleLat;
    final lon = current.vehicleLon;
    if (lat == null || lon == null) {
      throw StateError(
        'BusRealtimeCard received a vehicle without latitude/longitude',
      );
    }

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
            Text('車両 ${current.vehicleId}'),
            Text(busRealtimeStatusText(current)),
            Text('緯度 ${lat.toStringAsFixed(5)} / 経度 ${lon.toStringAsFixed(5)}'),
            if (current.serverNow != null) Text('取得時刻 ${current.serverNow}'),
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

  Widget _messageCard(BuildContext context, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6.resolveFrom(context),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(text),
      ),
    );
  }
}

String busRealtimeStatusText(BusLocation vehicle) {
  final stopName = vehicle.rawStopName?.trim();
  if (vehicle.beforeFirstStop) {
    return stopName == null || stopName.isEmpty
        ? '始発停留所へ向かっています'
        : '$stopName（始発停留所）へ向かっています';
  }
  if (stopName == null || stopName.isEmpty) {
    throw StateError('realtime vehicle is missing raw stop name');
  }
  switch (vehicle.currentStatus) {
    case 'STOPPED_AT':
    case '1':
      return '$stopNameに停車中';
    case 'IN_TRANSIT_TO':
    case 'INCOMING_AT':
    case '0':
    case '2':
      return '$stopNameへ向かっています';
    default:
      throw StateError(
        'Unsupported realtime current_status: ${vehicle.currentStatus}',
      );
  }
}

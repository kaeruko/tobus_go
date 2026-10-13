import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

import '../constants.dart';
import '../core/city_profile.dart';
import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../models/route_models.dart';
import '../services/bus_location_source.dart';
import 'route_detail_widgets.dart';
import 'route_map_preview.dart';

StepSeg? resolveTrackableBusStep(Candidate candidate) {
  StepSeg? firstBus;
  for (final step in candidate.steps) {
    if (step.kind != 'bus') continue;

    final routeId = step.routeId?.trim();
    if (routeId == null || routeId.isEmpty) {
      throw StateError(
        '追跡対象bus stepにrouteIdがありません: '
        'candidateId=${candidate.id}, stepId=${step.stepId}',
      );
    }

    final tripId = step.tripId?.trim();
    if (tripId == null || tripId.isEmpty) {
      throw StateError(
        '追跡対象bus stepにtripIdがありません: '
        'candidateId=${candidate.id}, stepId=${step.stepId}',
      );
    }

    firstBus ??= step;
  }
  return firstBus;
}

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
  DateTime _scheduledNow = DateTime.now();

  BusLocationSource get _source =>
      widget.busLocationSource ??
      RealtimeBusLocationSource(cityProfile: widget.cityProfile);

  StepSeg? get _trackedBusStep => resolveTrackableBusStep(widget.candidate);

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
    if (widget.cityProfile.city == AppCity.yokohama) {
      _timer = Timer.periodic(const Duration(seconds: 30), (_) {
        if (mounted) setState(() => _scheduledNow = DateTime.now());
      });
    } else if (_supportsVehiclePosition && _trackedBusStep != null) {
      _refreshRealtime(forceRefresh: true);
      _timer = Timer.periodic(
        kRealtimePollInterval,
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
      final l10n = AppLocalizations.of(context);
      setState(() {
        _vehicle = null;
        _loadingRealtime = false;
        _realtimeMessage = l10n.realtimeNotAvailable;
      });
    } catch (error) {
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      setState(() {
        _vehicle = null;
        _loadingRealtime = false;
        _realtimeMessage = l10n.realtimeFetchError(error.toString());
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
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
        if (widget.cityProfile.city == AppCity.yokohama)
          ScheduledRideCard(candidate: widget.candidate, now: _scheduledNow)
        else
          BusRealtimeCard(
            cityProfile: widget.cityProfile,
            trackedBusStep: _trackedBusStep,
            vehicle: _vehicle,
            loading: _loadingRealtime,
            message: _realtimeMessage,
          ),
        if (widget.cityProfile.city != AppCity.yokohama &&
            _supportsVehiclePosition && _trackedBusStep != null) ...[
          const SizedBox(height: 8),
          Center(
            child: CupertinoButton(
              onPressed: _loadingRealtime
                  ? null
                  : () => _refreshRealtime(forceRefresh: true),
              child: Text(l10n.refreshVehiclePosition),
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
              child: Text(l10n.endTrip),
            ),
          ),
        ],
      ],
    );
  }
}

DateTime? scheduledRideDepartureAt(Candidate candidate, StepSeg ride) {
  if (!ride.isRide) {
    throw ArgumentError('scheduledRideDepartureAt expects a bus or rail step');
  }
  final baseDate = candidate.departureDate;
  final clock = ride.departureTime;
  if (baseDate == null || clock == null) return null;
  final match = RegExp(r'^([0-9]{2,}):([0-5][0-9])$').firstMatch(clock);
  if (match == null) {
    throw FormatException('Invalid scheduled ride departure_time: $clock');
  }
  final localDate = baseDate.toLocal();
  return DateTime(localDate.year, localDate.month, localDate.day).add(
    Duration(
      hours: int.parse(match.group(1)!),
      minutes: int.parse(match.group(2)!),
    ),
  );
}

class ScheduledRideCard extends StatelessWidget {
  final Candidate candidate;
  final DateTime now;

  const ScheduledRideCard({
    super.key,
    required this.candidate,
    required this.now,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final rides = candidate.steps.where((step) => step.isRide);
    final ride = rides.isEmpty ? null : rides.first;
    final scheduled = ride == null
        ? null
        : scheduledRideDepartureAt(candidate, ride);
    String status;
    if (ride == null) {
      status = l10n.scheduleWalkOnly;
    } else if (scheduled == null) {
      status = l10n.scheduleDepartureUnknown;
    } else if (!now.isBefore(scheduled)) {
      status = l10n.scheduleDeparturePassed;
    } else {
      final remaining = scheduled.difference(now).inSeconds;
      status = l10n.scheduleMinutesUntil((remaining + 59) ~/ 60);
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6.resolveFrom(context),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l10n.scheduleCardTitle,
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            if (ride != null) ...[
              Text(ride.title),
              if (ride.toName != null) Text(ride.toName!),
              if (ride.departureTime != null)
                Text(l10n.scheduleDeparturePlanned(ride.departureTime!)),
            ],
            Text(status),
            const SizedBox(height: 8),
            Text(
              l10n.scheduleDelayDisclaimer,
              style: const TextStyle(
                color: CupertinoColors.systemGrey,
                fontSize: 13,
              ),
            ),
          ],
        ),
      ),
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
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    if (trackedBusStep == null) {
      return _messageCard(context, l10n.noTrackableBus);
    }
    if (!cityProfile.capabilities.realtime.vehiclePosition) {
      return _messageCard(
        context,
        l10n.vehiclePositionUnsupported(
          localizedCityAppName(l10n, cityProfile.city),
        ),
      );
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
      return _messageCard(context, l10n.realtimeNotLoaded);
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
            Text(
              l10n.busCurrentPosition,
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 6),
            Text(l10n.vehicleLabel(current.vehicleId)),
            Text(
              busRealtimeStatusText(
                current,
                l10n: l10n,
                locale: locale,
              ),
            ),
            Text(
              l10n.latLonLabel(
                lat.toStringAsFixed(5),
                lon.toStringAsFixed(5),
              ),
            ),
            if (current.serverNow != null)
              Text(l10n.fetchedAt(current.serverNow!)),
            const SizedBox(height: 8),
            Text(
              l10n.refreshEvery30Seconds,
              style: const TextStyle(
                color: CupertinoColors.systemGrey,
                fontSize: 13,
              ),
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

String busRealtimeStatusText(
  BusLocation vehicle, {
  required AppLocalizations l10n,
  required Locale locale,
}) {
  final rawStopName = vehicle.rawStopName?.trim();
  var stopName = rawStopName;
  if (isEnglishTransitLocale(locale) &&
      rawStopName != null &&
      rawStopName.isNotEmpty) {
    stopName = localizedTransitName(
      locale,
      japanese: rawStopName,
      english: vehicle.rawStopNameEn,
      field: 'raw_stop_name_en',
      identity: 'stopId=${vehicle.rawStopId ?? '<unknown>'}',
    );
  }

  if (vehicle.beforeFirstStop) {
    return stopName == null || stopName.isEmpty
        ? l10n.headingToFirstStop
        : l10n.headingToNamedFirstStop(stopName);
  }
  if (stopName == null || stopName.isEmpty) {
    throw StateError('realtime vehicle is missing raw stop name');
  }
  switch (vehicle.currentStatus) {
    case 'STOPPED_AT':
    case '1':
      return l10n.stoppedAt(stopName);
    case 'IN_TRANSIT_TO':
    case 'INCOMING_AT':
    case '0':
    case '2':
      return l10n.headingToStop(stopName);
    default:
      throw StateError(
        'Unsupported realtime current_status: ${vehicle.currentStatus}',
      );
  }
}


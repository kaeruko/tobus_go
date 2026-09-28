import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../l10n/trip_display_localizations.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';
import '../widgets/route_map_preview.dart';
import 'ride_stops_navigation.dart';

class SoloTripDetailPage extends StatelessWidget {
  final Trip trip;

  const SoloTripDetailPage({super.key, required this.trip});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final tripTitle = localizedSoloTripTitle(locale, trip);
    if (!trip.isSolo || trip.legs.length != 1) {
      throw StateError(
        'SoloTripDetailPage requires a single-leg solo trip: '
        'tripId=${trip.id}, type=${trip.tripType.name}, legs=${trip.legs.length}',
      );
    }
    final routePoints = trip.legs.single.candidate.points;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.soloTripDetailTitle)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 6),
                  Text(
                    tripTitle,
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    '${_formatDate(trip.date)} · '
                    '${_phaseLabel(l10n, trip.travelPhase)}',
                  ),
                ],
              ),
            ),
          ),
          if (routePoints.isNotEmpty) ...[
            const SizedBox(height: 12),
            RouteMapPreview(
              key: ValueKey(Object.hashAll(routePoints)),
              points: routePoints,
              showOpenButton: false,
              height: 150,
              margin: EdgeInsets.zero,
              interactive: false,
            ),
          ],
          const SizedBox(height: 16),
          Text(
            l10n.soloTripRouteAndSchedule,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          ...trip.schedule.map(
            (entry) => Card(
              child: ListTile(
                leading: CircleAvatar(
                  child: Icon(_entryIcon(entry.itemKind), size: 20),
                ),
                title: Text(
                  localizedSoloScheduleEntryLabel(
                    locale,
                    trip: trip,
                    entry: entry,
                  ),
                ),
                subtitle: _localizedDescription(l10n, locale, entry),
                trailing: Text(_formatTime(entry.plannedAt)),
                onTap: entry.itemKind == ScheduleEntryKind.ride
                    ? () => openRideStops(
                        context: context,
                        trip: trip,
                        entry: entry,
                      )
                    : null,
              ),
            ),
          ),
        ],
      ),
    );
  }

  static String _formatDate(DateTime value) =>
      '${value.year}/${value.month}/${value.day}';

  static String _formatTime(DateTime value) =>
      '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';

  static String _phaseLabel(AppLocalizations l10n, TravelPhase phase) {
    switch (phase) {
      case TravelPhase.planning:
        return l10n.travelPhasePlanning;
      case TravelPhase.active:
        return l10n.travelPhaseActive;
      case TravelPhase.completed:
        return l10n.travelPhaseCompleted;
      case TravelPhase.cancelled:
        return l10n.travelPhaseCancelled;
    }
  }

  static Widget? _localizedDescription(
    AppLocalizations l10n,
    Locale locale,
    ScheduleEntry entry,
  ) {
    if (entry.description.isEmpty) return null;
    if (locale.languageCode == 'en' &&
        entry.generatedBy == ScheduleEntrySource.route &&
        entry.itemKind == ScheduleEntryKind.goal) {
      return Text(l10n.navTripEndedSub);
    }
    return Text(entry.description);
  }

  static IconData _entryIcon(ScheduleEntryKind kind) {
    switch (kind) {
      case ScheduleEntryKind.meeting:
        return Icons.groups;
      case ScheduleEntryKind.departure:
        return Icons.near_me;
      case ScheduleEntryKind.ride:
        return Icons.directions_bus;
      case ScheduleEntryKind.walk:
        return Icons.directions_walk;
      case ScheduleEntryKind.arrival:
        return Icons.check_circle;
      case ScheduleEntryKind.goal:
        return Icons.flag;
      case ScheduleEntryKind.event:
        return Icons.event;
    }
  }
}

import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../l10n/trip_display_localizations.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';
import '../services/user_service.dart';
import 'ride_stops_navigation.dart';
import 'trip_report_page.dart';

class GroupTripDetailPage extends StatelessWidget {
  final Trip trip;

  const GroupTripDetailPage({super.key, required this.trip});

  @override
  Widget build(BuildContext context) {
    if (trip.isSolo || trip.travelPhase != TravelPhase.completed) {
      throw StateError('GroupTripDetailPage requires a completed group trip: ${trip.id}');
    }
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final isLeader = UserService().currentUserId == trip.leaderId;
    final start = trip.actualDepartureAt ?? trip.plannedDepartureAt;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.soloTripDetailTitle)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                children: [
                  Icon(Icons.check_circle_outline, size: 48,
                      color: Theme.of(context).colorScheme.primary),
                  const SizedBox(height: 12),
                  Text(l10n.navTripEndedSub,
                      style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 8),
                  Text(localizedTripTitle(locale, trip),
                      style: Theme.of(context).textTheme.titleLarge),
                  Text('${trip.date.year}/${trip.date.month}/${trip.date.day}'),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          if (start != null)
            ListTile(
              leading: const Icon(Icons.schedule),
              title: Text(l10n.groupReportStart),
              trailing: Text(_time(start)),
            ),
          ListTile(
            leading: const Icon(Icons.people_outline),
            title: Text(l10n.historyParticipants(trip.participants.length)),
            subtitle: Text(trip.participants.map((p) => p.name).join('、')),
          ),
          const SizedBox(height: 16),
          Text(l10n.soloTripRouteAndSchedule,
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          for (final entry in trip.schedule)
            Card(
              child: ListTile(
                title: Text(entry.label),
                subtitle: entry.description.isEmpty ? null : Text(entry.description),
                trailing: Text(_time(entry.plannedAt)),
                onTap: entry.itemKind == ScheduleEntryKind.ride
                    ? () => openRideStops(context: context, trip: trip, entry: entry)
                    : null,
              ),
            ),
          const SizedBox(height: 16),
          if (isLeader)
            TextButton.icon(
              key: const ValueKey('group-trip-open-report'),
              icon: const Icon(Icons.description_outlined),
              label: Text(l10n.groupReportTitle),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => TripReportPage(trip: trip)),
              ),
            ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(l10n.close),
          ),
        ],
      ),
    );
  }

  static String _time(DateTime value) =>
      '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
}

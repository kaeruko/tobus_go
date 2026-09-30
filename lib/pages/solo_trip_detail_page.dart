import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../l10n/app_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../l10n/trip_display_localizations.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../providers/navigation_provider.dart';
import '../providers/route_search_provider.dart';
import '../widgets/route_map_preview.dart';
import 'ride_stops_navigation.dart';

class SoloTripDetailPage extends ConsumerWidget {
  final Trip trip;

  const SoloTripDetailPage({super.key, required this.trip});

  void _planAgain(
    BuildContext context,
    WidgetRef ref,
    Candidate candidate,
  ) {
    final origin = candidate.originCoords;
    final destination = candidate.destinationCoords;
    if (origin == null || destination == null) {
      throw StateError(
        '履歴経路に再検索用の始点・終点座標がありません: '
        'candidateId=${candidate.id}, '
        'originCoords=$origin, destinationCoords=$destination',
      );
    }

    final originJa = candidate.originName?.trim();
    final destinationJa = candidate.destinationName?.trim();
    if (originJa == null || originJa.isEmpty) {
      throw StateError(
        '履歴経路に出発地名がありません: candidateId=${candidate.id}',
      );
    }
    if (destinationJa == null || destinationJa.isEmpty) {
      throw StateError(
        '履歴経路に到着地名がありません: candidateId=${candidate.id}',
      );
    }

    final originEn = candidate.originNameEn?.trim();
    final destinationEn = candidate.destinationNameEn?.trim();
    final english = isEnglishTransitLocale(Localizations.localeOf(context));
    final originDisplay = english && originEn != null && originEn.isNotEmpty
        ? originEn
        : originJa;
    final destinationDisplay =
        english && destinationEn != null && destinationEn.isNotEmpty
            ? destinationEn
            : destinationJa;
    final preference = candidate.preference?.trim();

    ref.read(routeSearchProvider.notifier).prepareSavedRoute(
      from: '${origin.latitude},${origin.longitude}',
      to: '${destination.latitude},${destination.longitude}',
      fromName: originDisplay,
      toName: destinationDisplay,
      fromNameJa: originJa,
      toNameJa: destinationJa,
      fromNameEn: originEn ?? '',
      toNameEn: destinationEn ?? '',
      startTime: appClock.now(),
      preference: preference == null || preference.isEmpty ? null : preference,
    );

    Navigator.of(context).popUntil((route) => route.isFirst);
    ref.read(tabIndexProvider.notifier).state = 0;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final tripTitle = localizedSoloTripTitle(locale, trip);
    if (!trip.isSolo || trip.legs.length != 1) {
      throw StateError(
        'SoloTripDetailPage requires a single-leg solo trip: '
        'tripId=${trip.id}, type=${trip.tripType.name}, legs=${trip.legs.length}',
      );
    }
    final candidate = trip.legs.single.candidate;
    final routePoints = candidate.points;

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
              interactive: true,
              openExternalOnTap: false,
              rotateGesturesEnabled: false,
              tiltGesturesEnabled: false,
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
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const ValueKey('history-plan-route-button'),
              onPressed: () => _planAgain(context, ref, candidate),
              child: Text(l10n.planSavedRoute),
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
    if (isEnglishTransitLocale(locale) &&
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

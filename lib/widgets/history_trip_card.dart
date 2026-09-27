import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../l10n/trip_display_localizations.dart';
import '../models/trip_models.dart';

class HistoryTripCard extends StatelessWidget {
  final Trip trip;
  final VoidCallback onTap;

  const HistoryTripCard({
    super.key,
    required this.trip,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final title = trip.isSolo
        ? localizedSoloTripTitle(locale, trip)
        : trip.displayTitle;
    final routeLines = _localizedRouteLines(locale, trip);
    final startAt = trip.plannedDepartureAt;
    final endAt = _routeEndAt(trip);
    final meta = _metaLine(l10n, trip, startAt: startAt, endAt: endAt);
    final summary = _summaryLine(l10n, trip);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _StatusIcon(phase: trip.travelPhase),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      meta,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    if (routeLines.isNotEmpty) ...[
                      const SizedBox(height: 5),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.route, size: 15),
                          const SizedBox(width: 5),
                          Expanded(
                            child: Text(
                              routeLines.join(' → '),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                        ],
                      ),
                    ],
                    if (summary.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        summary,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 4),
              const Padding(
                padding: EdgeInsets.only(top: 2),
                child: Icon(Icons.chevron_right, size: 22),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static List<String> _localizedRouteLines(Locale locale, Trip trip) {
    final lines = <String>[];
    for (final leg in trip.legs) {
      for (final line in localizedCandidateLines(locale, leg.candidate)) {
        if (!lines.contains(line)) lines.add(line);
      }
    }
    return lines;
  }

  static String _metaLine(
    AppLocalizations l10n,
    Trip trip, {
    required DateTime? startAt,
    required DateTime? endAt,
  }) {
    final parts = <String>[_formatDate(trip.date)];
    if (startAt != null) {
      if (endAt != null) {
        if (endAt.isBefore(startAt)) {
          throw StateError(
            '履歴の終了時刻が開始時刻より前です: '
            'tripId=${trip.id}, start=$startAt, end=$endAt',
          );
        }
        final minutes = endAt.difference(startAt).inMinutes;
        parts.add(
          '${_formatTime(startAt)} → ${_formatTime(endAt)} · '
          '${l10n.minutesValue(minutes)}',
        );
      } else {
        parts.add(_formatTime(startAt));
      }
    }
    return parts.join(' · ');
  }

  static DateTime? _routeEndAt(Trip trip) {
    DateTime? latest;
    for (final entry in trip.schedule) {
      if (entry.generatedBy.name != 'route') continue;
      if (latest == null || entry.plannedAt.isAfter(latest)) {
        latest = entry.plannedAt;
      }
    }
    return latest;
  }

  static String _summaryLine(AppLocalizations l10n, Trip trip) {
    var transfers = 0;
    var walkMinutes = 0;
    for (final leg in trip.legs) {
      transfers += leg.candidate.transfers;
      for (final step in leg.candidate.steps) {
        if (step.kind == 'walk') walkMinutes += step.minutes;
      }
    }

    final parts = <String>[];
    if (transfers > 0) {
      parts.add(l10n.historyTransfers(transfers));
    }
    if (walkMinutes > 0) {
      parts.add(l10n.historyWalkMinutes(walkMinutes));
    }
    if (!trip.isSolo && trip.participants.isNotEmpty) {
      parts.add(l10n.historyParticipants(trip.participants.length));
    }
    return parts.join(' · ');
  }

  static String _formatDate(DateTime value) =>
      '${value.year}/${value.month}/${value.day}';

  static String _formatTime(DateTime value) =>
      '${value.hour.toString().padLeft(2, '0')}:'
      '${value.minute.toString().padLeft(2, '0')}';
}

class _StatusIcon extends StatelessWidget {
  final TravelPhase phase;

  const _StatusIcon({required this.phase});

  @override
  Widget build(BuildContext context) {
    final (icon, color) = switch (phase) {
      TravelPhase.active => (Icons.directions_bus, Colors.green),
      TravelPhase.completed => (Icons.check_circle, Colors.green),
      TravelPhase.planning => throw StateError(
          '履歴カードにplanning状態が渡されました',
        ),
      TravelPhase.cancelled => throw StateError(
          '履歴カードにcancelled状態が渡されました',
        ),
    };

    return Container(
      width: 38,
      height: 38,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        shape: BoxShape.circle,
      ),
      child: Icon(icon, size: 21, color: color),
    );
  }
}

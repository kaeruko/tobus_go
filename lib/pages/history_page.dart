import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import '../widgets/history_trip_card.dart';
import 'solo_trip_detail_page.dart';
import 'trip_page.dart';
import 'trip_report_page.dart';

class HistoryPage extends StatefulWidget {
  const HistoryPage({super.key});

  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  final TripService _tripService = TripService();
  late Future<List<Trip>> _tripsFuture;
  final Set<String> _openingTripIds = <String>{};

  @override
  void initState() {
    super.initState();
    _tripsFuture = _tripService.getAllTrips();
  }

  void _reload() {
    setState(() {
      _tripsFuture = _tripService.getAllTrips();
    });
  }

  Future<void> _openTrip(Trip snapshotTrip) async {
    if (_openingTripIds.contains(snapshotTrip.id)) {
      debugPrint(
        '[HistoryNavigation] duplicate tap ignored tripId=${snapshotTrip.id}',
      );
      return;
    }

    _openingTripIds.add(snapshotTrip.id);
    try {
      debugPrint(
        '[HistoryNavigation] resolving trip before open '
        'tripId=${snapshotTrip.id} '
        'snapshotPhase=${snapshotTrip.travelPhase.name}',
      );
      final latestTrip = await _tripService.getTrip(snapshotTrip.id);
      if (latestTrip == null) {
        throw StateError(
          '履歴から開くおでかけが存在しません: ${snapshotTrip.id}',
        );
      }

      debugPrint(
        '[HistoryNavigation] resolved trip before open '
        'tripId=${latestTrip.id} '
        'latestPhase=${latestTrip.travelPhase.name}',
      );
      if (!mounted) return;

      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => _historyDestination(latestTrip),
        ),
      );
      if (!mounted) return;

      // HistoryPage is kept alive by CupertinoTabView. Refresh after returning
      // so a trip that completed while another tab/page was open cannot remain
      // displayed as active.
      _reload();
    } catch (error, stackTrace) {
      debugPrint(
        '[HistoryNavigation] open failed '
        'tripId=${snapshotTrip.id}: $error',
      );
      debugPrintStack(stackTrace: stackTrace);
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l10n.historyLoadFailed(error.toString()))),
      );
    } finally {
      _openingTripIds.remove(snapshotTrip.id);
    }
  }

  Future<bool> _confirmAndDelete(Trip trip) async {
    if (trip.travelPhase != TravelPhase.completed) {
      throw StateError(
        '完了していない履歴に削除操作が表示されました: '
        'tripId=${trip.id}, phase=${trip.travelPhase.name}',
      );
    }

    final l10n = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(l10n.historyDeleteTitle),
        content: Text(l10n.historyDeleteMessage),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(l10n.cancel),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: Text(l10n.delete),
          ),
        ],
      ),
    );
    if (confirmed != true) return false;

    try {
      await _tripService.hideCompletedTripFromHistory(trip.id);
      return true;
    } catch (error) {
      if (!mounted) return false;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l10n.historyDeleteFailed('$error'))),
      );
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: Text(l10n.historyTitle),
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.transparent,
      ),
      body: ColoredBox(
        color: Colors.white,
        child: FutureBuilder<List<Trip>>(
          future: _tripsFuture,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }

            if (snapshot.hasError) {
              return Center(
                child: Text(l10n.historyLoadFailed('${snapshot.error}')),
              );
            }

            final trips = (snapshot.data ?? [])
                .where(
                  (trip) =>
                      trip.travelPhase == TravelPhase.active ||
                      trip.travelPhase == TravelPhase.completed,
                )
                .toList();

            if (trips.isEmpty) {
              return Center(
                child: Text(
                  l10n.historyEmpty,
                  style: const TextStyle(color: Colors.grey),
                ),
              );
            }

            return ListView.builder(
              itemCount: trips.length,
              itemBuilder: (context, index) {
                final trip = trips[index];
                final card = HistoryTripCard(
                  trip: trip,
                  onTap: () => _openTrip(trip),
                );

                if (trip.travelPhase != TravelPhase.completed) {
                  return card;
                }

                return Dismissible(
                  key: ValueKey('history-trip:${trip.id}'),
                  direction: DismissDirection.endToStart,
                  confirmDismiss: (_) => _confirmAndDelete(trip),
                  onDismissed: (_) => _reload(),
                  background: Container(
                    margin: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 8,
                    ),
                    padding: const EdgeInsets.only(right: 24),
                    alignment: Alignment.centerRight,
                    decoration: BoxDecoration(
                      color: Colors.red,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(
                      Icons.delete,
                      color: Colors.white,
                    ),
                  ),
                  child: card,
                );
              },
            );
          },
        ),
      ),
    );
  }

  Widget _historyDestination(Trip trip) {
    switch (trip.travelPhase) {
      case TravelPhase.active:
        return TripPage(tripId: trip.id);
      case TravelPhase.completed:
        return trip.isSolo
            ? SoloTripDetailPage(trip: trip)
            : TripReportPage(trip: trip);
      case TravelPhase.planning:
      case TravelPhase.cancelled:
        throw StateError(
          '履歴画面から開けない状態です: ${trip.travelPhase.name}',
        );
    }
  }
}

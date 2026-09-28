import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import '../widgets/history_trip_card.dart';
import 'solo_trip_detail_page.dart';
import 'trip_page.dart';
import 'trip_report_page.dart';

class HistoryPage extends StatelessWidget {
  const HistoryPage({super.key});

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
        future: TripService().getAllTrips(),
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(
              child: CircularProgressIndicator(),
            );
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

              return HistoryTripCard(
                trip: trip,
                onTap: () {
                  Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => _historyDestination(trip),
                    ),
                  );
                },
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
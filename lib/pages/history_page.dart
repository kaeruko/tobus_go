import 'package:flutter/material.dart';

import '../models/trip_models.dart';
import '../services/trip_service.dart';
import 'trip_page.dart';
class HistoryPage extends StatelessWidget {
  const HistoryPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('履歴')),
      body: FutureBuilder<List<Trip>>(
        future: TripService().getAllTrips(),
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(
              child: CircularProgressIndicator(),
            );
          }

          if (snapshot.hasError) {
            return Center(
              child: Text('エラーが発生しました: ${snapshot.error}'),
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
            return const Center(
              child: Text(
                '履歴はありません',
                style: TextStyle(color: Colors.grey),
              ),
            );
          }

          return ListView.builder(
            itemCount: trips.length,
            itemBuilder: (context, index) {
              final trip = trips[index];

              return Card(
                margin: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 8,
                ),
                child: ListTile(
                  leading: Text(
                    _statusEmoji(trip.travelPhase),
                    style: const TextStyle(fontSize: 24),
                  ),
                  title: Text(trip.displayTitle),
                  subtitle: Text(
                    '${trip.date.year}/${trip.date.month}/${trip.date.day}',
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => TripPage(tripId: trip.id),
                      ),
                    );
                  },

                ),
              );
            },
          );
        },
      ),
    );
  }

  String _statusEmoji(TravelPhase phase) {
    switch (phase) {
      case TravelPhase.active:
        return '🚌';
      case TravelPhase.completed:
        return '✅';
      case TravelPhase.planning:
      case TravelPhase.cancelled:
        throw StateError(
          '履歴画面に表示対象外の状態が渡されました: ${phase.name}',
        );
    }
  }
}
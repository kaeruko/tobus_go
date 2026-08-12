import 'package:flutter/material.dart';
import '../services/trip_service.dart';
import '../models/trip_models.dart';
import 'group_detail_page.dart';
import 'solo_trip_detail_page.dart';

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
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text("エラーが発生しました: ${snapshot.error}"));
          }

          final trips = snapshot.data ?? [];

          if (trips.isEmpty) {
            return const Center(
              child: Text("履歴はありません", style: TextStyle(color: Colors.grey)),
            );
          }

          return ListView.builder(
            itemCount: trips.length,
            itemBuilder: (context, index) {
              final trip = trips[index];
              return Card(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: ListTile(
                  leading: Icon(
                    _statusIcon(trip.travelPhase),
                    color: _statusColor(trip.travelPhase),
                  ),
                  title: Text(trip.displayTitle),
                  subtitle: Text(
                    "${trip.isSolo ? '移動 ・ 1人' : 'おでかけ ・ ${trip.participants.length}人'}\n"
                    "${trip.date.year}/${trip.date.month}/${trip.date.day} ・ ${_statusLabel(trip.travelPhase)}",
                  ),
                  isThreeLine: true,
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => trip.isSolo
                            ? SoloTripDetailPage(trip: trip)
                            : GroupDetailPage(trip: trip),
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

  String _statusLabel(TravelPhase phase) {
    switch (phase) {
      case TravelPhase.planning:
        return '計画中';
      case TravelPhase.active:
        return '移動中';
      case TravelPhase.completed:
        return '完了';
      case TravelPhase.cancelled:
        return '中止';
    }
  }

  IconData _statusIcon(TravelPhase phase) {
    switch (phase) {
      case TravelPhase.planning:
        return Icons.schedule;
      case TravelPhase.active:
        return Icons.directions_bus;
      case TravelPhase.completed:
        return Icons.check_circle;
      case TravelPhase.cancelled:
        return Icons.cancel;
    }
  }

  Color _statusColor(TravelPhase phase) {
    switch (phase) {
      case TravelPhase.planning:
        return Colors.orange;
      case TravelPhase.active:
        return Colors.blue;
      case TravelPhase.completed:
        return Colors.green;
      case TravelPhase.cancelled:
        return Colors.grey;
    }
  }
}

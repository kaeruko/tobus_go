
import 'package:flutter/material.dart';
import '../services/trip_service.dart';
import '../models/trip_models.dart';
import 'group_detail_page.dart';

class HistoryPage extends StatelessWidget {
  const HistoryPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('履歴'),
      ),
      body: FutureBuilder<List<Trip>>(
        future: TripService().getCompletedTrips(),
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
              child: Text(
                "履歴はありません",
                style: TextStyle(color: Colors.grey),
              ),
            );
          }

          return ListView.builder(
            itemCount: trips.length,
            itemBuilder: (context, index) {
              final trip = trips[index];
              return Card(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: ListTile(
                  leading: const Icon(Icons.history, color: Colors.grey),
                  title: Text(trip.title),
                  subtitle: Text("${trip.date.year}/${trip.date.month}/${trip.date.day}"),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => GroupDetailPage(trip: trip),
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
}

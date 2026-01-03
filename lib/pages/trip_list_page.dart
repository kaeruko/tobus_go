import 'package:flutter/material.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import 'trip_report_page.dart';  // 次に作るファイル

class TripListPage extends StatefulWidget {
  const TripListPage({super.key});

  @override
  State<TripListPage> createState() => _TripListPageState();
}

class _TripListPageState extends State<TripListPage> {
  final _tripService = TripService();
  List<Trip>? _trips;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadTrips();
  }

  Future<void> _loadTrips() async {
    try {
      final trips = await _tripService.getAllTrips();
      if (mounted) {
        setState(() {
          _trips = trips;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('エラーが発生しました: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('お出かけ一覧'),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _trips == null || _trips!.isEmpty
              ? const Center(child: Text('お出かけの記録がありません'))
              : ListView.builder(
                  itemCount: _trips!.length,
                  itemBuilder: (context, index) {
                    final trip = _trips![index];
                    return _TripListItem(
                      trip: trip,
                      onTap: () {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => TripReportPage(trip: trip),
                          ),
                        );
                      },
                    );
                  },
                ),
    );
  }
}

class _TripListItem extends StatelessWidget {
  final Trip trip;
  final VoidCallback onTap;

  const _TripListItem({required this.trip, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final dateStr = '${trip.date.year}/${trip.date.month}/${trip.date.day}';
    final statusIcon = _getStatusIcon(trip.travelPhase);
    final statusColor = _getStatusColor(trip.travelPhase);

    return ListTile(
      leading: CircleAvatar(
        backgroundColor: statusColor.withOpacity(0.1),
        child: Icon(statusIcon, color: statusColor),
      ),
      title: Text(trip.title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text('$dateStr - ${trip.participants.length}名参加'),
      trailing: const Icon(Icons.arrow_forward_ios, size: 16),
      onTap: onTap,
    );
  }

  IconData _getStatusIcon(TravelPhase phase) {
    switch (phase) {
      case TravelPhase.planning: return Icons.edit;
      case TravelPhase.active: return Icons.directions_bus;
      case TravelPhase.completed: return Icons.check_circle;
      case TravelPhase.cancelled: return Icons.cancel;
    }
  }

  Color _getStatusColor(TravelPhase phase) {
    switch (phase) {
      case TravelPhase.planning: return Colors.orange;
      case TravelPhase.active: return Colors.green;
      case TravelPhase.completed: return Colors.blue;
      case TravelPhase.cancelled: return Colors.grey;
    }
  }
}

import 'package:flutter/material.dart';

import '../models/group_models.dart';
import '../models/trip_models.dart';
import 'segment_stops_page.dart';

class SoloTripDetailPage extends StatelessWidget {
  final Trip trip;

  const SoloTripDetailPage({super.key, required this.trip});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('移動の詳細')),
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
                    trip.displayTitle,
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    '${_formatDate(trip.date)} ・ ${_phaseLabel(trip.travelPhase)}',
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            '経路と予定',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          ...trip.schedule.map(
            (entry) => Card(
              child: ListTile(
                leading: CircleAvatar(
                  child: Icon(_entryIcon(entry.itemKind), size: 20),
                ),
                title: Text(entry.label),
                subtitle: entry.description.isEmpty
                    ? null
                    : Text(entry.description),
                trailing: Text(_formatTime(entry.plannedAt)),
                onTap: entry.itemKind == ScheduleEntryKind.ride
                    ? () => _openRideStops(context, entry)
                    : null,
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _openRideStops(BuildContext context, ScheduleEntry entry) {
    final stepId = entry.routeStepId;
    if (stepId == null || stepId.isEmpty) {
      throw StateError(
        '乗車予定にrouteStepIdがありません: entryId=${entry.id}, label=${entry.label}',
      );
    }

    final step = trip.stepsById[stepId];
    if (step == null) {
      throw StateError(
        '乗車予定が存在しないrouteStepIdを参照しています: '
        'entryId=${entry.id}, routeStepId=$stepId',
      );
    }
    if (!step.isRide) {
      throw StateError(
        '乗車予定のrouteStepIdが乗車ステップではありません: '
        'entryId=${entry.id}, routeStepId=$stepId, kind=${step.kind}',
      );
    }
    if (step.stops.isEmpty) {
      throw StateError(
        '乗車ステップに停留所情報がありません: '
        'entryId=${entry.id}, routeStepId=$stepId',
      );
    }

    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => SegmentStopsPage(segment: step),
      ),
    );
  }

  static String _formatDate(DateTime value) =>
      '${value.year}/${value.month}/${value.day}';

  static String _formatTime(DateTime value) =>
      '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';

  static String _phaseLabel(TravelPhase phase) {
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

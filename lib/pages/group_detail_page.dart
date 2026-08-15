import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../services/user_service.dart';

import 'group_leader_route_replan_page.dart';
import 'leader_mode_page.dart';
import 'member_mode_page.dart';
import 'ride_stops_navigation.dart';

class GroupDetailPage extends StatelessWidget {
  final Trip trip;

  const GroupDetailPage({super.key, required this.trip});

  DateTime _resolveStartDateTime() {
    final scheduledStart = trip.schedule.isNotEmpty
        ? trip.schedule
            .map((entry) => entry.plannedAt)
            .reduce((a, b) => a.isBefore(b) ? a : b)
        : null;
    return trip.plannedDepartureAt ?? scheduledStart ?? trip.date;
  }

  String _formatDateTime(DateTime dateTime) {
    final month = dateTime.month.toString().padLeft(2, '0');
    final day = dateTime.day.toString().padLeft(2, '0');
    final hour = dateTime.hour.toString().padLeft(2, '0');
    final minute = dateTime.minute.toString().padLeft(2, '0');
    return '$month/$day $hour:$minute';
  }

  String _formatScheduleTime(DateTime dt, bool showDate) {
    var time = '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    if (showDate) {
      return '${dt.month}/${dt.day} $time';
    }
    return time;
  }

  Future<void> _navigateToMode(BuildContext context) async {
    final uid = UserService().currentUserId;
    final isLeader = (uid == trip.leaderId);

    if (isLeader) {
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => LeaderModePage(tripId: trip.id)),
      );
    } else {
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const MemberModePage()),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final showDate = trip.schedule.isNotEmpty &&
        (trip.schedule.first.plannedAt.day != trip.schedule.last.plannedAt.day ||
            trip.schedule.first.plannedAt.month != trip.schedule.last.plannedAt.month);
    final currentUserId = UserService().currentUserId;
    final isLeader = currentUserId != null && currentUserId == trip.leaderId;
    final canReplan = isLeader && trip.travelPhase == TravelPhase.active;

    return Scaffold(
      appBar: AppBar(
        title: const Text('おでかけのしおり'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. タイトルとコード
            Card(
              elevation: 2,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    Text(
                      trip.title,
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                      decoration: BoxDecoration(
                        color: Colors.orange.shade50,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.orange.shade200),
                      ),
                      child: Column(
                        children: [
                          const Text("参加コード", style: TextStyle(fontSize: 12, color: Colors.grey)),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                trip.joinCode,
                                style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold, letterSpacing: 4),
                              ),
                              const SizedBox(width: 8),
                              IconButton(
                                icon: const Icon(Icons.copy, size: 20),
                                onPressed: () {
                                  Clipboard.setData(ClipboardData(text: trip.joinCode));
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    const SnackBar(content: Text('参加コードをコピーしました')),
                                  );
                                },
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),

            // 2. 基本情報
            const Text("基本情報", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            _InfoRow(icon: Icons.person, label: "リーダー", value: trip.participants.firstWhere((p) => p.isLeader, orElse: () => trip.participants.first).name),
            const SizedBox(height: 8),
            _InfoRow(
                icon: Icons.calendar_today,
                label: "実施日",
                value: _formatDateTime(_resolveStartDateTime())),

            const SizedBox(height: 24),

            // 3. 参加者
            const Text("参加者", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: trip.participants.map((p) {
                return Chip(
                  avatar: CircleAvatar(
                    backgroundColor: p.isLeader ? Colors.orange : Colors.blue.shade100,
                    child: Text(p.name[0], style: const TextStyle(fontSize: 12, color: Colors.white)),
                  ),
                  label: Text(p.name),
                  backgroundColor: Colors.white,
                  side: BorderSide(color: Colors.grey.shade300),
                );
              }).toList(),
            ),

            const SizedBox(height: 24),

            // 4. しおり（全件表示）
            const Text("しおり (予定)",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            ...trip.schedule.map((item) {
              return ListTile(
                leading: Text(
                  _formatScheduleTime(item.plannedAt, showDate),
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                title: Text(item.label),
                subtitle: Text(item.description,
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                contentPadding: EdgeInsets.zero,
                dense: true,
                onTap: item.itemKind == ScheduleEntryKind.ride
                    ? () => openRideStops(
                        context: context,
                        trip: trip,
                        entry: item,
                      )
                    : null,
              );
            }),

            const SizedBox(height: 40),

            // 下部の余白確保 (FABやBottomBarとかぶらないように)
            const SizedBox(height: 80),
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (canReplan) ...[
                SizedBox(
                  height: 50,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => GroupLeaderRouteReplanPage(
                          tripId: trip.id,
                        ),
                      ),
                    ),
                    icon: const Icon(Icons.alt_route),
                    label: const Text(
                      '移動中の経路を見直す',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
              ],
              SizedBox(
                height: 50,
                child: ElevatedButton.icon(
                  onPressed: () => _navigateToMode(context),
                  icon: const Icon(Icons.play_arrow),
                  label: const Text("おでかけ編集", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.orange,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  const _InfoRow({required this.icon, required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 20, color: Colors.grey),
        const SizedBox(width: 8),
        Text("$label: ", style: const TextStyle(fontWeight: FontWeight.bold)),
        Text(value),
      ],
    );
  }
}

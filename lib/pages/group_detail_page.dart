import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../services/trip_service.dart';
import '../services/user_service.dart';
import 'leader_mode_page.dart';
import 'member_mode_page.dart';
import 'schedule_page.dart'; // スケジュール表示用(簡易)

class GroupDetailPage extends StatelessWidget {
  final Trip trip;
  
  const GroupDetailPage({super.key, required this.trip});

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
    // スケジュールの概要（最初の3件くらい）
    final previewSchedule = trip.schedule.take(3).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('グループ詳細'),
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
            _InfoRow(icon: Icons.calendar_today, label: "実施日", value: "${trip.date.month}/${trip.date.day}"),

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

            // 4. しおり（簡易）
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("しおり (予定)", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                TextButton(
                  onPressed: () {
                    // スケジュール全画面へ (閲覧モードとして開く)
                     Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => SchedulePage(
                            tripId: trip.id,
                            isLeader: false, // 閲覧のみなのでfalse扱いでも良いが、保存ボタンが出ないように制御必要
                            initialSchedule: trip.schedule,
                          ),
                        ),
                      );
                  },
                  child: const Text("すべて見る"),
                ),
              ],
            ),
            ...previewSchedule.map((item) {
              return ListTile(
                leading: Text(
                  item.time,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                title: Text(item.title),
                subtitle: Text(item.description, maxLines: 1, overflow: TextOverflow.ellipsis),
                contentPadding: EdgeInsets.zero,
                dense: true,
              );
            }),

            const SizedBox(height: 40),

            // 5. アクションボタン
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton.icon(
                onPressed: () => _navigateToMode(context),
                icon: const Icon(Icons.play_arrow),
                label: const Text("グループモードを開く", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.orange,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ),
            const SizedBox(height: 40),
          ],
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

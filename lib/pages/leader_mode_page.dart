// lib/pages/leader_mode_page.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // クリップボード用
import '../models/trip_models.dart';
import '../services/trip_service.dart';

class LeaderModePage extends StatelessWidget {
  final String tripId;
  const LeaderModePage({super.key, required this.tripId});

  @override
  Widget build(BuildContext context) {
    final tripService = TripService();

    return StreamBuilder<Trip>(
      stream: tripService.streamTrip(tripId),
      builder: (context, snapshot) {
        if (snapshot.hasError) return Scaffold(body: Center(child: Text('エラー: ${snapshot.error}')));
        if (!snapshot.hasData) return const Scaffold(body: Center(child: CircularProgressIndicator()));

        final trip = snapshot.data!;
        
        return Scaffold(
          appBar: AppBar(
            title: const Text('引率モード'),
            backgroundColor: Colors.green,
            actions: [
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context), // 閉じて終了
              ),
            ],
          ),
          body: Column(
            children: [
              // --- 1. 参加コード表示エリア ---
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(24),
                color: Colors.green.shade50,
                child: Column(
                  children: [
                    const Text('参加コード', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.green)),
                    const SizedBox(height: 8),
                    InkWell(
                      onTap: () {
                        Clipboard.setData(ClipboardData(text: trip.joinCode));
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('コードをコピーしました')));
                      },
                      child: Text(
                        trip.joinCode,
                        style: const TextStyle(fontSize: 48, fontWeight: FontWeight.bold, letterSpacing: 8),
                      ),
                    ),
                    const Text('この数字をメンバーに伝えてください', style: TextStyle(color: Colors.grey)),
                  ],
                ),
              ),

              // --- 2. ステータス操作 ---
              Padding(
                padding: const EdgeInsets.all(16),
                child: trip.status == TripStatus.planning
                    ? ElevatedButton.icon(
                        icon: const Icon(Icons.directions_walk),
                        label: const Text('全員揃ったので出発する'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.orange,
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 16),
                        ),
                        onPressed: () async {
                          // TODO: TripServiceに updateStatus メソッドを追加して呼ぶ
                          // await tripService.updateStatus(tripId, TripStatus.active);
                        },
                      )
                    : Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(color: Colors.blue, borderRadius: BorderRadius.circular(8)),
                        child: const Text('移動中', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
              ),

              const Divider(),

              // --- 3. 参加者リスト (リアルタイム更新) ---
              const Padding(
                padding: EdgeInsets.only(left: 16, top: 8),
                child: Align(alignment: Alignment.centerLeft, child: Text('参加メンバー', style: TextStyle(fontWeight: FontWeight.bold))),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: trip.participants.length,
                  itemBuilder: (context, index) {
                    final member = trip.participants[index];
                    return ListTile(
                      leading: CircleAvatar(
                        backgroundColor: member.isLeader ? Colors.green : Colors.blue,
                        child: Icon(member.isLeader ? Icons.star : Icons.person, color: Colors.white),
                      ),
                      title: Text(member.name),
                      subtitle: Text(member.isLeader ? 'リーダー' : 'メンバー'),
                      trailing: member.sosCount != null && member.sosCount! > 0
                          ? const Icon(Icons.warning, color: Colors.red) // SOS履歴があれば表示
                          : null,
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
// lib/pages/leader_mode_page.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'dart:async'; // Timer用
import '../models/trip_models.dart';
import '../services/trip_service.dart';

class LeaderModePage extends StatefulWidget {
  final String tripId;
  const LeaderModePage({super.key, required this.tripId});

  @override
  State<LeaderModePage> createState() => _LeaderModePageState();
}

class _LeaderModePageState extends State<LeaderModePage> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // 1分ごとに画面を更新してカウントダウンを進める
    _timer = Timer.periodic(const Duration(minutes: 1), (timer) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  // スケジュールの最初から開始時刻を計算するヘルパー
  DateTime? _getStartTime(Trip trip) {
    if (trip.schedule.isEmpty) return null;
    
    // "10:00" などの文字列を取得
    final timeStr = trip.schedule.first.time;
    if (!timeStr.contains(':')) return null;

    final parts = timeStr.split(':');
    final hour = int.tryParse(parts[0]) ?? 0;
    final minute = int.tryParse(parts[1]) ?? 0;

    // Tripの日付データと組み合わせる
    final d = trip.date;
    return DateTime(d.year, d.month, d.day, hour, minute);
  }

  @override
  Widget build(BuildContext context) {
    final tripService = TripService();

    return StreamBuilder<Trip>(
      stream: tripService.streamTrip(widget.tripId),
      builder: (context, snapshot) {
        if (snapshot.hasError) return Scaffold(body: Center(child: Text('エラー: ${snapshot.error}')));
        if (!snapshot.hasData) return const Scaffold(body: Center(child: CircularProgressIndicator()));

        final trip = snapshot.data!;
        
        // カウントダウン計算
        final startTime = _getStartTime(trip);
        final now = DateTime.now();
        Duration? diff;
        if (startTime != null) {
          diff = startTime.difference(now);
        }

        return Scaffold(
          appBar: AppBar(
            title: const Text('引率モード'),
            backgroundColor: Colors.green,
            actions: [
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context),
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

              // --- 2. カウントダウン & ステータス操作 ---
              Padding(
                padding: const EdgeInsets.all(24),
                child: trip.status == TripStatus.planning
                    ? Column(
                        children: [
                          // カウントダウン表示
                          if (diff != null && !diff.isNegative) ...[
                            const Text('お出かけ開始まで', style: TextStyle(fontSize: 16, color: Colors.grey)),
                            const SizedBox(height: 4),
                            Text(
                              'あと ${diff.inHours}時間 ${diff.inMinutes % 60}分',
                              style: const TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: Colors.green),
                            ),
                          ] else ...[
                            const Text(
                              '出発予定時刻になりました',
                              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.orange),
                            ),
                          ],
                          
                          const SizedBox(height: 20),

                          // 出発ボタン
                          SizedBox(
                            width: double.infinity,
                            child: ElevatedButton.icon(
                              icon: const Icon(Icons.flag), // 旗アイコン
                              label: const Text('お出かけを開始する'), // 文言変更
                              style: ElevatedButton.styleFrom(
                                backgroundColor: Colors.orange,
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(vertical: 16),
                                textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                              ),
                              onPressed: () async {
                                // ステータスを active に更新
                                // ※TripServiceに updateStatus がなければ追加が必要
                                // await tripService.startTrip(trip.id); 
                              },
                            ),
                          ),
                          const SizedBox(height: 8),
                          const Text('※全員揃ったら押してください', style: TextStyle(fontSize: 12, color: Colors.grey)),
                        ],
                      )
                    : Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(color: Colors.blue, borderRadius: BorderRadius.circular(8)),
                        child: const Column(
                          children: [
                            Icon(Icons.directions_walk, color: Colors.white, size: 40),
                            SizedBox(height: 8),
                            Text('移動中', style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold)),
                            Text('安全運転で行きましょう', style: TextStyle(color: Colors.white)),
                          ],
                        ),
                      ),
              ),

              const Divider(),

              // --- 3. 参加者リスト ---
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
                      subtitle: Text(member.isLeader ? 'リーダー' : '参加済み'),
                      trailing: member.sosCount != null && member.sosCount! > 0
                          ? const Icon(Icons.warning, color: Colors.red)
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
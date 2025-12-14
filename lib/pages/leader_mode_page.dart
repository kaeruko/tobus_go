// lib/pages/leader_mode_page.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../services/trip_service.dart';
import 'schedule_page.dart';

class LeaderModePage extends StatefulWidget {
  final String tripId;
  const LeaderModePage({super.key, required this.tripId});

  @override
  State<LeaderModePage> createState() => _LeaderModePageState();
}

class _LeaderModePageState extends State<LeaderModePage> {
  static const int _thresholdMinutes = 5;
  bool _starting = false;

  Future<void> _handleStartTrip(Trip trip, TripService service) async {
    if (_starting) return;
    _starting = true;

    final now = DateTime.now();
    final planned = trip.plannedDepartureAt ??
        (trip.schedule.isNotEmpty ? trip.schedule.first.plannedAt : now);
    final deltaMinutes = now.difference(planned).inMinutes;

    await service.startTrip(trip.id, now);

    if (!mounted) return;

    if (deltaMinutes.abs() >= _thresholdMinutes) {
      _showRerouteDialog(trip, service, now, deltaMinutes);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('旅を開始しました')),
      );
    }
  }

  Future<void> _showRerouteDialog(
      Trip trip, TripService service, DateTime departure, int delta) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('再検索しますか？'),
        content: Text('予定より${delta.abs()}分ずれています。経路を再計算しますか？'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('そのまま続行')),
          ElevatedButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('再検索する')),
        ],
      ),
    );

    if (result == true) {
      await _rerouteOutward(trip, service, departure);
    }
  }

  Future<void> _rerouteOutward(
      Trip trip, TripService service, DateTime departure) async {
    Leg? outbound;
    for (final leg in trip.legs) {
      if (leg.direction == LegDirection.outbound) {
        outbound = leg;
        break;
      }
    }

    if (outbound == null) return;

    final newOutward = createScheduleFromRoute(
      outbound.candidate,
      startDateTime: departure,
      labelPrefix: '行き',
      legIndex: 0,
    );

    final updatedSchedule =
        service.applyRerouteOutwardOnly(trip.schedule, newOutward);

    await service.updateSchedule(trip.id, updatedSchedule);

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('行きの経路を更新しました')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tripService = TripService();

    return StreamBuilder<Trip>(
      stream: tripService.streamTrip(widget.tripId),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Scaffold(
              body: Center(child: Text('エラー: ${snapshot.error}')));
        }
        if (!snapshot.hasData) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }

        final trip = snapshot.data!;

        return Scaffold(
          appBar: AppBar(
            title: const Text('引率モード'),
            backgroundColor: Colors.green,
            actions: [
              IconButton(
                icon: const Icon(Icons.list_alt),
                tooltip: 'スケジュール管理',
                onPressed: () {
                  Navigator.of(context, rootNavigator: true).push(
                    MaterialPageRoute(
                      builder: (_) => SchedulePage(
                        tripId: trip.id,
                        isLeader: true,
                        initialSchedule: trip.schedule,
                      ),
                    ),
                  );
                },
              ),
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
          body: Column(
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(24),
                color: Colors.green.shade50,
                child: Column(
                  children: [
                    const Text('参加コード',
                        style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                            color: Colors.green)),
                    const SizedBox(height: 8),
                    InkWell(
                      onTap: () {
                        Clipboard.setData(ClipboardData(text: trip.joinCode));
                        ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('コードをコピーしました')));
                      },
                      child: Text(
                        trip.joinCode,
                        style: const TextStyle(
                            fontSize: 48,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 8),
                      ),
                    ),
                    const Text('この数字をメンバーに伝えてください',
                        style: TextStyle(color: Colors.grey)),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  children: [
                    if (trip.travelPhase == TravelPhase.planning) ...[
                      // 計画中: 開始ボタンを表示
                      const Text(
                        '準備ができたら開始ボタンを押してください',
                        style: TextStyle(color: Colors.grey),
                      ),
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: () => _handleStartTrip(trip, tripService),
                          icon: const Icon(Icons.play_arrow),
                          label: const Text('お出かけを開始する', style: TextStyle(fontSize: 18)),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.orange,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                          ),
                        ),
                      ),
                    ] else if (trip.travelPhase == TravelPhase.active) ...[
                      // 移動中: 大きな移動中表示 + 終了ボタン
                      Container(
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
                      const SizedBox(height: 24),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          // ここで確認ダイアログを呼び出す
                          onPressed: () => _showCompleteDialog(context, trip),
                          icon: const Icon(Icons.check_circle),
                          label: const Text('お出かけを終了する', style: TextStyle(fontSize: 16)),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.grey.shade600,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                          ),
                        ),
                      ),
                    ] else ...[
                      // その他 (completed, cancelled)
                      Text('状態: ${trip.travelPhase.name}', style: const TextStyle(fontSize: 18, color: Colors.grey)),
                    ],
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () {
                      Navigator.of(context, rootNavigator: true).push(
                        MaterialPageRoute(
                          builder: (_) => SchedulePage(
                            tripId: trip.id,
                            isLeader: true,
                            initialSchedule: trip.schedule,
                          ),
                        ),
                      );
                    },
                    icon: const Icon(Icons.list_alt),
                    label: const Text('スケジュールを確認・編集'),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                  ),
                ),
              ),
              const Divider(),
              const Padding(
                padding: EdgeInsets.only(left: 16, top: 8),
                child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text('参加メンバー',
                        style: TextStyle(fontWeight: FontWeight.bold))),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: trip.participants.length,
                  itemBuilder: (context, index) {
                    final member = trip.participants[index];
                    return ListTile(
                      leading: CircleAvatar(
                        backgroundColor:
                            member.isLeader ? Colors.green : Colors.blue,
                        child: Icon(member.isLeader ? Icons.star : Icons.person,
                            color: Colors.white),
                      ),
                      title: Text(member.name),
                      subtitle:
                          Text(member.isLeader ? 'リーダー' : '参加済み'),
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

  void _showCompleteDialog(BuildContext context, Trip trip) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('お出かけ終了'),
        content: const Text('本当に終了しますか?\nメンバーの画面も「終了」に切り替わります。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('キャンセル'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.green,
              foregroundColor: Colors.white,
            ),
            onPressed: () async {
              Navigator.pop(ctx); // ダイアログを閉じる
              try {
                // 終了処理を実行
                await TripService().completeTrip(trip.id);
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('お出かけを終了しました')),
                  );
                  Navigator.pop(context); // リーダー画面を閉じる
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('終了処理に失敗しました: $e')),
                  );
                }
              }
            },
            child: const Text('終了する'),
          ),
        ],
      ),
    );
  }
}

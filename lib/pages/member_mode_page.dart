// lib/pages/member_mode_page.dart
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import '../data/global_state.dart';
import '../models/group_models.dart';
import '../services/group_service.dart';
import 'root_tabs.dart'; // 通常モードに戻るため
import 'schedule_page.dart'; // スケジュール画面

class MemberModePage extends StatefulWidget {
  const MemberModePage({super.key});

  @override
  State<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends State<MemberModePage> {
  final _groupService = GroupService();
  List<ScheduleItem> _schedule = [];
  ScheduleItem? _nextTask;

  @override
  void initState() {
    super.initState();
    _loadSchedule();
  }

  // スケジュールを読み込む
  Future<void> _loadSchedule() async {
    if (kCurrentGroupId == null) return;

    try {
      final doc = await FirebaseFirestore.instance
          .collection('groups')
          .doc(kCurrentGroupId)
          .get();

      if (doc.exists) {
        final scheduleData = doc.data()?['schedule'] as List<dynamic>? ?? [];
        setState(() {
          _schedule = scheduleData
              .map((e) => ScheduleItem.fromJson(e as Map<String, dynamic>))
              .toList();
          _updateNextTask();
        });
      }
    } catch (e) {
      print('スケジュール読み込みエラー: $e');
    }
  }

  // 次のタスクを更新
  void _updateNextTask() {
    // 未完了のタスクを探す
    _nextTask = _schedule.firstWhere(
      (item) => !item.isCompleted,
      orElse: () => _schedule.isNotEmpty
          ? _schedule.last
          : ScheduleItem(time: '', title: 'スケジュールなし'),
    );
  }

  // グループを抜けて通常モードに戻る処理
  Future<void> _leaveGroup(BuildContext context) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('groupId');
    await prefs.setBool('isMemberMode', false); // フラグを消す

    kCurrentGroupId = null;
    kIsMemberMode = false;

    // アプリのルートを通常モード(RootTabs)に差し替える
    if (context.mounted) {
      Navigator.of(context, rootNavigator: true).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const RootTabs()),
        (route) => false,
      );
    }
  }

  // スケジュール画面を開く
  void _openSchedule() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => SchedulePage(
          isLeader: false,
          initialSchedule: _schedule,
        ),
      ),
    ).then((_) => _loadSchedule()); // 戻ってきたら再読み込み
  }

  @override
  Widget build(BuildContext context) {
    // 画面全体を黄色っぽくして「モードが違う」ことをわかりやすくする
    return Scaffold(
      backgroundColor: Colors.yellow[50],
      appBar: AppBar(
        title: const Text('えんそくモード'),
        automaticallyImplyLeading: false, // 戻るボタンを消す
        actions: [
          // スケジュール表示ボタン
          IconButton(
            icon: const Icon(Icons.list),
            onPressed: _openSchedule,
          ),
          // 抜けるための小さなボタン
          IconButton(
            icon: const Icon(Icons.exit_to_app),
            onPressed: () => showDialog(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('モード終了'),
                content: const Text('通常モードに戻りますか?'),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text('いいえ'),
                  ),
                  TextButton(
                    onPressed: () {
                      Navigator.pop(ctx);
                      _leaveGroup(context);
                    },
                    child: const Text('はい'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text("つぎは", style: TextStyle(fontSize: 20)),
            const SizedBox(height: 10),
            // 次のタスクのタイトルを表示
            Text(
              _nextTask?.title ?? "スケジュールを確認してね",
              style: const TextStyle(
                fontSize: 40,
                fontWeight: FontWeight.bold,
                color: Colors.blue,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 10),
            // 時刻を表示
            if (_nextTask != null && _nextTask!.time.isNotEmpty)
              Text(
                _nextTask!.time,
                style: const TextStyle(fontSize: 24, color: Colors.grey),
              ),
            const SizedBox(height: 10),
            // 説明を表示
            if (_nextTask != null && _nextTask!.description.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Text(
                  _nextTask!.description,
                  style: const TextStyle(fontSize: 18),
                  textAlign: TextAlign.center,
                ),
              ),

            const SizedBox(height: 50),

            // SOSボタン
            SizedBox(
              width: 150,
              height: 150,
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red,
                  shape: const CircleBorder(),
                ),
                onPressed: () {
                  // ヘルプカード表示処理
                  showDialog(
                    context: context,
                    builder: (ctx) => AlertDialog(
                      title: const Text('SOS'),
                      content: const Text('引率者に通知を送りますか?'),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(ctx),
                          child: const Text('キャンセル'),
                        ),
                        ElevatedButton(
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.red,
                          ),
                          onPressed: () {
                            // TODO: 引率者に通知を送る処理
                            Navigator.pop(ctx);
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('引率者に通知しました')),
                            );
                          },
                          child: const Text('通知する'),
                        ),
                      ],
                    ),
                  );
                },
                child: const Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.sos, size: 50, color: Colors.white),
                    Text(
                      "たすけて",
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
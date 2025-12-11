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
  void _openSchedule(List<ScheduleItem> schedule) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => SchedulePage(
          isLeader: false,
          initialSchedule: schedule,
        ),
      ),
    );
  }

  // SOS送信
  Future<void> _sendSOS() async {
    if (kCurrentGroupId == null) return;

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
            onPressed: () async {
              Navigator.pop(ctx);
              // SOS送信
              await _groupService.sendSOS(
                kCurrentGroupId!,
                'member_user', // TODO: 実際のユーザーIDを使用
                'メンバー',
              );

              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('引率者に通知しました!')),
                );
              }
            },
            child: const Text('通知する'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (kCurrentGroupId == null) {
      return const Scaffold(
        body: Center(child: Text('グループIDが設定されていません')),
      );
    }

    // StreamBuilderでFirestoreを常時監視
    return StreamBuilder<DocumentSnapshot>(
      stream: _groupService.streamGroup(kCurrentGroupId!),
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        // データが来たらスケジュールを更新
        final data = snapshot.data!.data() as Map<String, dynamic>?;
        
        // ★修正: データがない場合(デバッグIDなど)は空のリストではなくダミーを表示するか、
        // 少なくとも「データなし」エラーで止まらないようにする
        final scheduleRaw = (data != null && data.containsKey('schedule')) 
            ? data['schedule'] as List<dynamic>
            : [];
            
        final schedule = scheduleRaw
            .map((e) => ScheduleItem.fromJson(e as Map<String, dynamic>))
            .toList();

        // スケジュールが空の場合のダミーデータ(デバッグ用)
        if (schedule.isEmpty) {
          schedule.add(ScheduleItem(
            time: '10:00',
            title: 'えんそく開始',
            description: 'リーダーがスケジュールを作るとここに表示されます',
            type: ScheduleType.meeting,
          ));
        }

        // 次のタスクを計算
        final nextTask = schedule.firstWhere(
          (item) => !item.isCompleted,
          orElse: () => schedule.isNotEmpty
              ? schedule.last
              : ScheduleItem(time: '', title: 'スケジュールを確認してね'),
        );

        return Scaffold(
          backgroundColor: Colors.yellow[50],
          appBar: AppBar(
            title: const Text('えんそくモード'),
            automaticallyImplyLeading: false, // 戻るボタンを消す
            actions: [
              // スケジュール表示ボタン
              IconButton(
                icon: const Icon(Icons.list),
                onPressed: () => _openSchedule(schedule),
              ),
              // 抜けるためのボタン (文字付きで分かりやすく)
              TextButton.icon(
                style: TextButton.styleFrom(
                  foregroundColor: Colors.red,
                ),
                icon: const Icon(Icons.exit_to_app),
                label: const Text('終了'),
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
                  nextTask.title,
                  style: const TextStyle(
                    fontSize: 40,
                    fontWeight: FontWeight.bold,
                    color: Colors.blue,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 10),
                // 時刻を表示
                if (nextTask.time.isNotEmpty)
                  Text(
                    nextTask.time,
                    style: const TextStyle(fontSize: 24, color: Colors.grey),
                  ),
                const SizedBox(height: 10),
                // 説明を表示
                if (nextTask.description.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 32),
                    child: Text(
                      nextTask.description,
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
                    onPressed: _sendSOS,
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
      },
    );
  }
}
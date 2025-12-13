import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart'; // Material for AlertDialog
import 'package:shared_preferences/shared_preferences.dart';
import '../data/global_state.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import '../models/group_models.dart'; // ScheduleItem用
import 'root_tabs.dart'; // 通常モードに戻るため
import 'schedule_page.dart'; // スケジュール画面

class MemberModePage extends StatefulWidget {
  const MemberModePage({super.key});

  @override
  State<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends State<MemberModePage> {
  final _tripService = TripService();

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
        CupertinoPageRoute(builder: (_) => const RootTabs()),
        (route) => false,
      );
    }
  }

  // スケジュール画面を開く
  void _openSchedule(String tripId, List<ScheduleItem> schedule) {
    Navigator.of(context, rootNavigator: true).push(
      CupertinoPageRoute(
        builder: (_) => SchedulePage(
          tripId: tripId,
          isLeader: false,
          initialSchedule: schedule,
        ),
      ),
    );
  }

  // SOS送信
  Future<void> _sendSOS() async {
    if (kCurrentGroupId == null) return;

    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('SOS'),
        content: const Text('引率者に通知を送りますか?'),
        actions: [
          CupertinoDialogAction(
            child: const Text('キャンセル'),
            onPressed: () => Navigator.pop(ctx),
          ),
          CupertinoDialogAction(
            isDestructiveAction: true,
            onPressed: () async {
              Navigator.pop(ctx);
              // SOS送信
              await _tripService.sendSOS(kCurrentGroupId!);

              if (mounted) {
                showCupertinoDialog(
                  context: context,
                  builder: (ctx2) => CupertinoAlertDialog(
                    content: const Text('引率者に通知しました!'),
                    actions: [
                       CupertinoDialogAction(
                         child: const Text('OK'),
                         onPressed: () => Navigator.pop(ctx2),
                       ),
                    ],
                  ),
                );
              }
            },
            child: const Text('通知する'),
          ),
        ],
      ),
    );
  }
  
  void _showCancelledDialog(BuildContext context) {
    showDialog(
      context: context,
      barrierDismissible: false, // 枠外タップで閉じさせない
      builder: (ctx) => AlertDialog(
        title: const Text('お知らせ'),
        content: const Text('ホストによりグループが解散されました。'),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx); // ダイアログ閉じる
              _leaveGroup(context); // 退出処理（データ削除＆ホームへ）
            },
            child: const Text('OK'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (kCurrentGroupId == null) {
      return const CupertinoPageScaffold(
        navigationBar: CupertinoNavigationBar(middle: Text('エラー')),
        child: Center(child: Text('グループIDが設定されていません')),
      );
    }

    // StreamBuilderでFirestoreを常時監視
    return StreamBuilder<Trip>(
      stream: _tripService.streamTrip(kCurrentGroupId!),
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
           return const CupertinoPageScaffold(
             navigationBar: CupertinoNavigationBar(middle: Text('読み込み中...')),
             child: Center(child: CupertinoActivityIndicator()),
           );
        }

        final trip = snapshot.data!;

        // ★追加: 中止されていたら強制退去
        if (trip.status == TripStatus.cancelled) {
          // ビルド完了後にダイアログを出すためのハック
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (context.mounted) {
              _showCancelledDialog(context);
            }
          });
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
            
        final schedule = trip.schedule;

        // 次のタスクを計算
        // 未完了の最初のものを探す、なければ最後のもの、それもなければデフォルト
        final nextTask = schedule.firstWhere(
          (item) => !item.isCompleted,
          orElse: () => schedule.isNotEmpty
              ? schedule.last
              : ScheduleItem(time: '', title: 'スケジュールを確認してね'),
        );

        return CupertinoPageScaffold(
          backgroundColor: const Color(0xFFFFFDE7), // Colors.yellow[50] replacement
          navigationBar: CupertinoNavigationBar(
            middle: const Text('えんそくモード'),
            automaticallyImplyLeading: false, // 戻るボタンを消す
            leading: CupertinoButton(
              padding: EdgeInsets.zero,
              child: const Icon(CupertinoIcons.list_bullet),
              onPressed: () => _openSchedule(trip.id, schedule),
            ),
            trailing: CupertinoButton(
               padding: EdgeInsets.zero,
               child: const Text('終了', style: TextStyle(color: CupertinoColors.destructiveRed)),
               onPressed: () => showCupertinoDialog(
                  context: context,
                  builder: (ctx) => CupertinoAlertDialog(
                    title: const Text('モード終了'),
                    content: const Text('通常モードに戻りますか?'),
                    actions: [
                      CupertinoDialogAction(
                        child: const Text('いいえ'),
                        onPressed: () => Navigator.pop(ctx),
                      ),
                      CupertinoDialogAction(
                        isDestructiveAction: true,
                        child: const Text('はい'),
                        onPressed: () {
                          Navigator.pop(ctx);
                          _leaveGroup(context);
                        },
                      ),
                    ],
                  ),
               ),
            ),
          ),
          child: SafeArea(
            child: Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Text("つぎは", style: TextStyle(fontSize: 20)),
                  const SizedBox(height: 10),
                  // 次のタスクのタイトルを表示
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16.0),
                    child: Text(
                      nextTask.title,
                      style: const TextStyle(
                        fontSize: 32, // Slightly smaller than 40 to fit better
                        fontWeight: FontWeight.bold,
                        color: CupertinoColors.activeBlue,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ),
                  const SizedBox(height: 10),
                  // 時刻を表示
                  if (nextTask.time.isNotEmpty)
                    Text(
                      nextTask.time,
                      style: const TextStyle(fontSize: 24, color: CupertinoColors.systemGrey),
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
                  GestureDetector(
                    onTap: _sendSOS,
                    child: Container(
                      width: 150,
                      height: 150,
                      decoration: const BoxDecoration(
                        color: CupertinoColors.systemRed,
                        shape: BoxShape.circle,
                        boxShadow: [
                          BoxShadow(
                            color: Color(0x42000000), 
                            blurRadius: 10,
                            offset: Offset(0, 4),
                          )
                        ]
                      ),
                      child: const Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(CupertinoIcons.speaker_2_fill, size: 50, color: CupertinoColors.white), // Similar to SOS
                          Text(
                            "たすけて",
                            style: TextStyle(
                              color: CupertinoColors.white,
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
          ),
        );
      },
    );
  }
}
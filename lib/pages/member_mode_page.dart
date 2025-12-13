import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart'; // Material for AlertDialog & Scaffold
import 'package:google_maps_flutter/google_maps_flutter.dart'; // LatLng
import 'package:shared_preferences/shared_preferences.dart';
import '../data/global_state.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import '../models/group_models.dart'; // ScheduleItem用
import 'root_tabs.dart'; // 通常モードに戻るため
import 'schedule_page.dart'; // スケジュール画面
import '../logic/trip_navigator.dart'; // ★Navigation Logic

class MemberModePage extends StatefulWidget {
  const MemberModePage({super.key});

  @override
  State<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends State<MemberModePage> {
  final _tripService = TripService();
  
  // ★進捗状態を保持する変数
  int _currentStepIndex = 0;
  int _nextStopIndex = 0;

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
      return const Scaffold(
        appBar: CupertinoNavigationBar(middle: Text('エラー')),
        body: Center(child: Text('グループIDが設定されていません')),
      );
    }

    // StreamBuilderでFirestoreを常時監視
    return StreamBuilder<Trip>(
      stream: _tripService.streamTrip(kCurrentGroupId!),
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
           return const Scaffold(
             body: Center(child: CircularProgressIndicator()),
           );
        }

        final trip = snapshot.data!;

        // 中止されていたら強制退去
        if (trip.status == TripStatus.cancelled) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (context.mounted) {
              _showCancelledDialog(context);
            }
          });
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
            
        final schedule = trip.schedule;

        // ★ TripNavigatorを使用して状態を判定
        // TODO: GPS統合時はここで本物のGPS座標を渡す
        final currentGpsLocation = const LatLng(35.6812, 139.7671); // 東京駅(仮)
        
        // ロジックを呼ぶ
        final navState = TripNavigator.updateState(
          trip, 
          currentGpsLocation, 
          _currentStepIndex, 
          _nextStopIndex
        );

        // ★重要: 計算結果のインデックスを保存（これが「経路を潰す」動作になる）
        // build中にsetStateは呼べないので、次回のために変数を更新しておく
        if (navState.currentStepIndex != _currentStepIndex || 
            navState.nextStopIndex != _nextStopIndex) {
            
            // 状態が進んだ！
            _currentStepIndex = navState.currentStepIndex;
            _nextStopIndex = navState.nextStopIndex;
        }

        return Scaffold(
          backgroundColor: navState.color, // ★背景色が状態によって変わる！
          appBar: AppBar(
            title: const Text('えんそくモード', style: TextStyle(color: Colors.black)),
            backgroundColor: navState.color, // AppBarも色を合わせる
            elevation: 0,
            iconTheme: const IconThemeData(color: Colors.black),
            leading: IconButton(
              icon: const Icon(CupertinoIcons.list_bullet),
              onPressed: () => _openSchedule(trip.id, schedule),
            ),
            actions: [
              TextButton(
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
                child: const Text('終了', style: TextStyle(color: CupertinoColors.destructiveRed)),
              ),
            ],
          ),
          body: Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  navState.subText,
                  style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 20),
                Text(
                  navState.mainText,
                  style: const TextStyle(
                    fontSize: 48, 
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                    shadows: [Shadow(blurRadius: 4, color: Colors.black26, offset: Offset(2, 2))],
                  ),
                ),
          
                const SizedBox(height: 50),
          
                // SOSボタン (既存のデザインを維持)
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
        );
      },
    );
  }
}
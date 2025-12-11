import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:math';
import '../services/group_service.dart';
import '../data/global_state.dart';
import '../models/group_models.dart'; // ★追加
import 'member_mode_page.dart'; // ★追加

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  final _groupService = GroupService();
  final _joinIdController = TextEditingController(); // 入力用
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _loadGroupId();
  }

  // 保存されたグループIDを読み込む
  Future<void> _loadGroupId() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      kCurrentGroupId = prefs.getString('groupId');
    });
  }

  // グループ作成(リーダー)
  Future<void> _createGroup() async {
    setState(() => _isLoading = true);
    
    // ランダムな4桁の数字IDを生成
    final newGroupId = (Random().nextInt(9000) + 1000).toString();
    
    // ★追加: 保存されたルートがあればスケジュールを自動生成
    List<ScheduleItem> initialSchedule = [];
    Map<String, dynamic> routeData = {};
    
    if (kSavedRoutes.isNotEmpty) {
      final targetRoute = kSavedRoutes.first; // 最初のルートを使用
      routeData = targetRoute.toJson();
      initialSchedule = createScheduleFromRoute(targetRoute);
    }
    
    // Firestoreに保存
    await _groupService.createGroup(
      newGroupId, 
      'LeaderUser', 
      routeData,
      schedule: initialSchedule, // ★スケジュールを渡す
    );

    // スマホ本体にIDを保存
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('groupId', newGroupId);

    setState(() {
      kCurrentGroupId = newGroupId;
      _isLoading = false;
    });
  }

  // グループ参加(メンバー)
  Future<void> _joinGroup() async {
    final inputId = _joinIdController.text;
    if (inputId.length != 4) return;

    setState(() => _isLoading = true);

    // 本当はここでIDが存在するかチェックすると親切
    await _groupService.joinGroup(inputId, 'MemberUser', 'メンバー');

    // 保存処理
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('groupId', inputId);
    await prefs.setBool('isMemberMode', true); // ★これを保存！

    setState(() {
      kCurrentGroupId = inputId;
      kIsMemberMode = true; // ★グローバル変数も更新
      _isLoading = false;
    });

    // ★ここがポイント！
    // 画面を「MemberModePage」に強制的に差し替える
    if (mounted) {
      Navigator.of(context, rootNavigator: true).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const MemberModePage()),
        (route) => false,
      );
    }
  }

  // グループ離脱
  Future<void> _leaveGroup() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('groupId');
    setState(() {
      kCurrentGroupId = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('設定')),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                const Text('グループ活動', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                const SizedBox(height: 10),
                
                // --- グループ未参加の場合 ---
                if (kCurrentGroupId == null) ...[
                  const Text('引率者の方はこちら'),
                  ElevatedButton.icon(
                    icon: const Icon(Icons.group_add),
                    label: const Text('新しいグループを作成する'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.orange,
                      foregroundColor: Colors.white,
                    ),
                    onPressed: _createGroup,
                  ),
                  const Divider(height: 40),
                  const Text('メンバーの方はこちら'),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _joinIdController,
                          decoration: const InputDecoration(
                            labelText: '4桁のIDを入力',
                            border: OutlineInputBorder(),
                          ),
                          keyboardType: TextInputType.number,
                        ),
                      ),
                      const SizedBox(width: 10),
                      ElevatedButton(
                        onPressed: _joinGroup,
                        child: const Text('参加'),
                      ),
                    ],
                  ),
                  const Divider(height: 40),
                  // --- デバッグ用ボタン ---
                  const Text('デバッグ用', style: TextStyle(fontSize: 12, color: Colors.grey)),
                  ElevatedButton(
                    onPressed: () async {
                      // Firebaseを使わず、ローカルにダミーIDを保存
                      final debugGroupId = 'DEBUG_${Random().nextInt(9000) + 1000}';
                      final prefs = await SharedPreferences.getInstance();
                      await prefs.setString('groupId', debugGroupId);
                      await prefs.setBool('isMemberMode', true); // ★追加
                      
                      setState(() {
                        kCurrentGroupId = debugGroupId;
                        kIsMemberMode = true; // ★追加
                      });
                      
                      // ★メンバーモード画面に切り替え
                      if (mounted) {
                        Navigator.of(context, rootNavigator: true).pushAndRemoveUntil(
                          MaterialPageRoute(builder: (_) => const MemberModePage()),
                          (route) => false,
                        );
                      }
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.grey,
                      foregroundColor: Colors.white,
                    ),
                    child: const Text('【DEBUG】即座にグループ参加状態にする'),
                  ),
                ] 
                // --- グループ参加中の場合 ---
                else ...[
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: Colors.green.shade50,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: Colors.green),
                    ),
                    child: Column(
                      children: [
                        const Text('現在参加中のグループID', style: TextStyle(color: Colors.green)),
                        Text(
                          kCurrentGroupId!,
                          style: const TextStyle(fontSize: 40, fontWeight: FontWeight.bold, letterSpacing: 5),
                        ),
                        const SizedBox(height: 10),
                        const Text('このIDをメンバーに教えてください'),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  OutlinedButton(
                    onPressed: _leaveGroup,
                    style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
                    child: const Text('グループから抜ける(一人モードに戻る)'),
                  ),
                ],
              ],
            ),
    );
  }
}

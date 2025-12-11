import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:math';
import '../services/group_service.dart';
import '../data/global_state.dart';

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
    
    // Firestoreに保存 (ルート情報はとりあえず空で作成)
    // ※実際はここで kSavedRoutes の中身などを渡すと良い
    await _groupService.createGroup(newGroupId, 'LeaderUser', {});

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

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('groupId', inputId);

    setState(() {
      kCurrentGroupId = inputId;
      _isLoading = false;
    });
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

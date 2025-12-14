import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:cloud_firestore/cloud_firestore.dart'; // 追加
import 'package:flutter/services.dart';
import '../services/user_service.dart';
import '../services/trip_service.dart'; // Added
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_session_provider.dart';
// import 'member_mode_page.dart'; // Unused
import 'leader_mode_page.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  bool _isStaffMode = false;
  String? _userId;
  String _userName = '';

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    
    // ユーザー情報の取得
    await UserService().initialize();
    final name = await UserService().getUserName();
    final uid = UserService().currentUserId;

    setState(() {
      _isStaffMode = prefs.getBool('isStaffMode') ?? false;
      _userName = name;
      _userId = uid;
    });
  }

  Future<void> _updateUserName() async {
    final controller = TextEditingController(text: _userName);
    await showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('ユーザー名の変更'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(labelText: '新しい名前'),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('キャンセル'),
          ),
          TextButton(
            onPressed: () async {
              final newName = controller.text.trim();
              if (newName.isNotEmpty) {
                await UserService().updateUserName(newName);
                setState(() {
                  _userName = newName;
                });
              }
              if (context.mounted) Navigator.pop(context);
            },
            child: const Text('保存'),
          ),
        ],
      ),
    );
  }

  Future<void> _toggleStaffMode(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('isStaffMode', value);
    setState(() {
      _isStaffMode = value;
      // グローバル変数を更新するならここで (今回は設定だけ)
    });
  }

  // ★追加: 最新のTripIDを取得してリーダー画面を開く
  Future<void> _openLatestTripAsLeader() async {
    try {
      String? tripId;
      
      // 1. まず現在のアクティブなTripを確認
      final sessionTripId = ref.read(appSessionProvider).currentTripId;
      if (sessionTripId != null) {
        tripId = sessionTripId;
      } else {
        // 2. セッションになくてもFirestore上でアクティブなものがあるか確認
        final activeTrip = await TripService().getActiveTrip();
        if (activeTrip != null) {
          tripId = activeTrip.id;
        }
      }

      // 3. アクティブなものがなければ、自分がメンバーになっている最新の旅を探す
      if (tripId == null) {
        final uid = UserService().currentUserId;
        if (uid != null) {
          final snapshot = await FirebaseFirestore.instance
              .collection('trips')
              .where('memberIds', arrayContains: uid)
              .orderBy('date', descending: true)
              .limit(1)
              .get();
          
          if (snapshot.docs.isNotEmpty) {
            tripId = snapshot.docs.first.id;
          }
        }
      }
      
      if (tripId != null) {
        // update session (optional but good for consistency)
        await ref.read(appSessionProvider.notifier).updateTripId(tripId);

        if (mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => LeaderModePage(tripId: tripId!)),
          );
        }
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Tripが見つかりません。まずは作成してください。')),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('エラー: $e')));
      }
    }
  }

  // ★追加: 最新のTripIDを取得してメンバー画面を開く
  Future<void> _openLatestTripAsMember() async {
    try {
      String? tripId;
      
      // 1. まず現在のアクティブなTripを確認
      final sessionTripId = ref.read(appSessionProvider).currentTripId;
      if (sessionTripId != null) {
        tripId = sessionTripId;
      } else {
        final activeTrip = await TripService().getActiveTrip();
        if (activeTrip != null) {
          tripId = activeTrip.id;
        }
      }

      // 2. なければ最新の履歴から
      if (tripId == null) {
        final uid = UserService().currentUserId;
        if (uid != null) {
          final snapshot = await FirebaseFirestore.instance
              .collection('trips')
              .where('memberIds', arrayContains: uid)
              .orderBy('date', descending: true)
              .limit(1)
              .get();
          
          if (snapshot.docs.isNotEmpty) {
            tripId = snapshot.docs.first.id;
          }
        }
      }

      if (tripId != null) {
        // Note: enterMemberMode will update session and persist it.
        await ref.read(appSessionProvider.notifier).enterMemberMode(tripId);
        
        if (mounted) {
           ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('メンバーモードに切り替わりました')));
        }
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('参加可能なTripが見つかりません')),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('エラー: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('設定')),
      body: ListView(
        children: [
          // --- ユーザー情報 ---
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
            child: Text('ユーザー情報',
                style: TextStyle(
                    color: Colors.blueGrey,
                    fontWeight: FontWeight.bold,
                    fontSize: 14)),
          ),
          ListTile(
            leading: const Icon(Icons.account_circle),
            title: const Text('ユーザー名'),
            subtitle: Text(_userName.isEmpty ? 'ゲスト' : _userName),
            trailing: const Icon(Icons.edit, size: 20),
            onTap: _updateUserName,
          ),
          ListTile(
            leading: const Icon(Icons.fingerprint),
            title: const Text('ユーザーID'),
            subtitle: Text(_userId ?? '読み込み中...',
                style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
            trailing: IconButton(
              icon: const Icon(Icons.copy, size: 20),
              onPressed: () {
                if (_userId != null) {
                  Clipboard.setData(ClipboardData(text: _userId!));
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('IDをコピーしました')),
                  );
                }
              },
            ),
          ),
          const Divider(),

          // --- 既存の設定 ---
          SwitchListTile(
            title: const Text('職員・管理者向け機能を有効にする'),
            subtitle: const Text('報告書作成や詳細な管理機能を表示します'),
            value: _isStaffMode,
            onChanged: _toggleStaffMode,
          ),
          
          const Divider(),
          
          // --- ★デバッグ用エリア (開発中のみ表示してもOK) ---
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('【デバッグメニュー】', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
          ),
          
          ListTile(
            leading: const Icon(Icons.star, color: Colors.green),
            title: const Text('最新の旅を「リーダー」として開く'),
            subtitle: const Text('最後に作成されたTripの管理画面を表示'),
            onTap: _openLatestTripAsLeader,
          ),
          
          ListTile(
            leading: const Icon(Icons.person, color: Colors.blue),
            title: const Text('最新の旅を「メンバー」として開く'),
            subtitle: const Text('最後に作成されたTripの参加者画面を表示'),
            onTap: _openLatestTripAsMember,
          ),
        ],
      ),
    );
  }
}

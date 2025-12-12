import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:cloud_firestore/cloud_firestore.dart'; // 追加
import '../data/global_state.dart';
import 'member_mode_page.dart';
import 'leader_mode_page.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool _isStaffMode = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _isStaffMode = prefs.getBool('isStaffMode') ?? false;
    });
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
      // 自分が作った最新のTripを探す
      // (本来はuidで絞り込むべきですが、テスト用なので全件から最新を取得でもOK)
      final snapshot = await FirebaseFirestore.instance
          .collection('trips')
          .orderBy('createdAt', descending: true)
          .limit(1)
          .get();

      if (snapshot.docs.isNotEmpty) {
        final tripId = snapshot.docs.first.id;
        if (mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => LeaderModePage(tripId: tripId)),
          );
        }
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Tripが見つかりません。まずは作成してください。')),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('エラー: $e')));
    }
  }

  // ★追加: 最新のTripIDを取得してメンバー画面を開く
  Future<void> _openLatestTripAsMember() async {
    try {
      final snapshot = await FirebaseFirestore.instance
          .collection('trips')
          .orderBy('createdAt', descending: true)
          .limit(1)
          .get();

      if (snapshot.docs.isNotEmpty) {
        final tripId = snapshot.docs.first.id;
        
        // グローバル変数を強制セット (デバッグ用)
        kCurrentGroupId = tripId;
        
        if (mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => const MemberModePage()),
          );
        }
      }
    } catch (e) {
      print(e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('設定')),
      body: ListView(
        children: [
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

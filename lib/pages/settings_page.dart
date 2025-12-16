import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/services.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../services/user_service.dart';
import '../services/trip_service.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_session_provider.dart';
import '../providers/location_provider.dart';
import '../widgets/place_field.dart';
import 'leader_mode_page.dart';
import '../core/app_clock.dart'; // 追加
import '../providers/minute_ticker_provider.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  bool _isStaffMode = false;
  String? _userId;
  String _userName = '';
  String _manualLocationInput = '';

  @override
  void initState() {
    super.initState();
    _loadSettings();
    
    // Initialize manual input with current override if exists
    final override = ref.read(locationOverrideProvider);
    if (override != null) {
      _manualLocationInput = '${override.latitude},${override.longitude}';
    }
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
    });
  }

  void _updateManualLocation(String value, String desc) {
    setState(() => _manualLocationInput = value);

    final parts = value.split(',');
    if (parts.length != 2) {
      return;
    }

    final lat = double.tryParse(parts[0].trim());
    final lon = double.tryParse(parts[1].trim());
    if (lat == null || lon == null) {
      return;
    }

    ref.read(locationOverrideProvider.notifier).setOverride(LatLng(lat, lon));
  }

  Future<void> _clearManualLocation() async {
    await ref.read(locationOverrideProvider.notifier).clearOverride();
  }

  // ★追加: 時間オフセットの設定ダイアログ
  Future<void> _updateTimeOffset() async {
    final currentOffset = AppClock.instance.offset;
    // 初期値設定
    final hController = TextEditingController(text: currentOffset.inHours.toString());
    final mController = TextEditingController(text: (currentOffset.inMinutes.remainder(60)).toString());

    await showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('時間オフセット設定'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('現在時刻を指定した時間だけずらします（デバッグ用）', style: TextStyle(fontSize: 12)),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: hController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '時間 (Hours)',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: mController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '分 (Minutes)',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              AppClock.instance.resetOffset();
              ref.invalidate(minuteTickerProvider); // Force immediate time update
              setState(() {}); // 画面更新
              Navigator.pop(context);
            },
            child: const Text('リセット', style: TextStyle(color: Colors.red)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('キャンセル'),
          ),
          FilledButton(
            onPressed: () {
              final h = int.tryParse(hController.text) ?? 0;
              final m = int.tryParse(mController.text) ?? 0;
              AppClock.instance.setOffset(Duration(hours: h, minutes: m));
              ref.invalidate(minuteTickerProvider); // Force immediate time update
              setState(() {}); // 画面更新
              Navigator.pop(context);
            },
            child: const Text('設定'),
          ),
        ],
      ),
    );
  }

  Future<void> _openLatestTripAsLeader() async {
    try {
      String? tripId;
      final sessionTripId = ref.read(appSessionProvider).currentTripId;
      if (sessionTripId != null) {
        tripId = sessionTripId;
      } else {
        final activeTrip = await TripService().getActiveTrip();
        if (activeTrip != null) {
          tripId = activeTrip.id;
        }
      }

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

  Future<void> _openLatestTripAsMember() async {
    try {
      String? tripId;
      final sessionTripId = ref.read(appSessionProvider).currentTripId;
      if (sessionTripId != null) {
        tripId = sessionTripId;
      } else {
        final activeTrip = await TripService().getActiveTrip();
        if (activeTrip != null) {
          tripId = activeTrip.id;
        }
      }

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

  // 時刻表示用のヘルパー
  String _formatTime(DateTime dt) {
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    // 修正: ref.listen は build メソッド内で呼び出す
    ref.listen<LatLng?>(locationOverrideProvider, (prev, next) {
      setState(() {
        _manualLocationInput = next != null ? '${next.latitude},${next.longitude}' : '';
      });
    });

    final manualOverride = ref.watch(locationOverrideProvider);
    final currentOffset = AppClock.instance.offset;
    final simulatedTime = AppClock.instance.now();

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

          const Padding(
            padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
            child: Text(
              '現在地を手動入力',
              style: TextStyle(
                color: Colors.blueGrey,
                fontWeight: FontWeight.bold,
                fontSize: 14,
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                PlaceField(
                  label: '位置を検索して設定',
                  value: _manualLocationInput,
                  displayValue: _manualLocationInput,
                  onChanged: _updateManualLocation,
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        manualOverride != null
                            ? '現在の設定: ${manualOverride.latitude.toStringAsFixed(5)}, ${manualOverride.longitude.toStringAsFixed(5)}'
                            : '現在の設定: GPSの値を使用中',
                      ),
                    ),
                    TextButton(
                      onPressed:
                          manualOverride != null ? _clearManualLocation : null,
                      child: const Text('クリアしてGPSに戻す'),
                    ),
                  ],
                ),
              ],
            ),
          ),

          const Divider(),

          // --- ★デバッグ用エリア ---
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text('【デバッグメニュー】', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
          ),
          
          // ★ここに追加: 時間オフセット設定
          ListTile(
            leading: const Icon(Icons.access_time, color: Colors.orange),
            title: const Text('時間オフセット設定'),
            subtitle: Text(
              currentOffset == Duration.zero
                  ? '設定なし (現在時刻: ${_formatTime(simulatedTime)})'
                  : 'Offset: +${currentOffset.inHours}h ${currentOffset.inMinutes % 60}m\nSimulated: ${_formatTime(simulatedTime)}',
            ),
            onTap: _updateTimeOffset,
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
          
          // 下部に余白を追加
          const SizedBox(height: 40),
        ],
      ),
    );
  }
}
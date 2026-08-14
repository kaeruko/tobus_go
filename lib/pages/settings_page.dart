import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/services.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../services/user_service.dart';
import '../services/trip_service.dart';
import '../models/trip_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_session_provider.dart';
import '../providers/location_provider.dart';
import '../widgets/place_field.dart';
import 'leader_mode_page.dart';
import '../core/app_clock.dart'; // 追加
import '../providers/minute_ticker_provider.dart';
import '../core/api_client.dart';
import '../models/leg_models.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import 'trip_list_page.dart';
import 'solo_trip_detail_page.dart';
import 'solo_trip_screen.dart';

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
    final hController = TextEditingController(
      text: currentOffset.inHours.toString(),
    );
    final mController = TextEditingController(
      text: (currentOffset.inMinutes.remainder(60)).toString(),
    );

    await showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('時間オフセット設定'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              '現在時刻を指定した時間だけずらします（デバッグ用）',
              style: TextStyle(fontSize: 12),
            ),
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
              ref.invalidate(
                minuteTickerProvider,
              ); // Force immediate time update
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
              ref.invalidate(
                minuteTickerProvider,
              ); // Force immediate time update
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
      debugPrint("[Settings] _openLatestTripAsLeader called");
      String? tripId;
      final sessionTripId = ref.read(appSessionProvider).currentTripId;
      debugPrint("[Settings] sessionTripId: $sessionTripId");

      if (sessionTripId != null) {
        tripId = sessionTripId;
        debugPrint("[Settings] Using sessionTripId: $tripId");
      } else {
        final activeTrip = await TripService().getActiveTrip();
        debugPrint("[Settings] activeTrip from Service: ${activeTrip?.id}");
        if (activeTrip != null) {
          tripId = activeTrip.id;
          debugPrint("[Settings] Using activeTripId: $tripId");
        }
      }

      if (tripId == null) {
        final uid = UserService().currentUserId;
        debugPrint("[Settings] Current User ID: $uid");
        if (uid != null) {
          debugPrint("[Settings] Querying Firestore for leader trips...");
          final snapshot = await FirebaseFirestore.instance
              .collection('trips')
              .where('memberIds', arrayContains: uid)
              .orderBy('date', descending: true)
              .limit(1)
              .get();

          debugPrint("[Settings] Snapshot docs count: ${snapshot.docs.length}");
          if (snapshot.docs.isNotEmpty) {
            final doc = snapshot.docs.first;
            final data = doc.data();
            debugPrint(
              "[Settings] Found Leader Trip: ${doc.id} | Status: ${data['travelPhase'] ?? data['status']} | Date: ${data['date']}",
            );
            tripId = doc.id;
          }
        } else {
          debugPrint("[Settings] UID is null, skipping Firestore query");
        }
      }

      if (tripId != null) {
        final trip = await TripService().getTrip(tripId);
        if (trip?.isSolo == true) {
          final soloTrip = trip!;
          if (mounted) {
            Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => soloTrip.travelPhase == TravelPhase.active
                    ? TripPage(tripId: soloTrip.id)
                    : SoloTripDetailPage(trip: soloTrip),
              ),
            );
          }
          return;
        }
        debugPrint(
          "[Settings] Attempting to open LeaderModePage for tripId: $tripId",
        );
        await ref.read(appSessionProvider.notifier).updateTripId(tripId);
        if (mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => LeaderModePage(tripId: tripId!)),
          );
        }
      } else {
        debugPrint("[Settings] No tripId found for Leader Mode.");
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Tripが見つかりません。まずは作成してください。')),
          );
        }
      }
    } catch (e) {
      debugPrint("[Settings] Error in _openLatestTripAsLeader: $e");
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('エラー: $e')));
      }
    }
  }

  Future<void> _openLatestTripAsMember() async {
    try {
      debugPrint("[Settings] _openLatestTripAsMember called");
      String? tripId;
      final sessionTripId = ref.read(appSessionProvider).currentTripId;
      debugPrint("[Settings] sessionTripId: $sessionTripId");

      if (sessionTripId != null) {
        // Verify the stored trip is still valid before reusing it
        final sessionTrip = await TripService().getTrip(sessionTripId);
        final uid = UserService().currentUserId;
        final isActive =
            sessionTrip != null &&
            (sessionTrip.travelPhase == TravelPhase.planning ||
                sessionTrip.travelPhase == TravelPhase.active);
        final isMember =
            sessionTrip != null &&
            uid != null &&
            sessionTrip.memberIds.contains(uid);

        if (isActive && isMember) {
          tripId = sessionTripId;
          debugPrint("[Settings] Using sessionTripId: $tripId");
        } else {
          debugPrint(
            "[Settings] Stored sessionTripId is invalid (active=$isActive, member=$isMember), clearing it",
          );
          await ref.read(appSessionProvider.notifier).leaveMemberMode();
        }
      }

      if (tripId == null) {
        final activeTrip = await TripService().getActiveTrip();
        debugPrint("[Settings] activeTrip from Service: ${activeTrip?.id}");
        if (activeTrip != null) {
          tripId = activeTrip.id;
          debugPrint("[Settings] Using activeTripId: $tripId");
        }
      }

      if (tripId == null) {
        final uid = UserService().currentUserId;
        debugPrint("[Settings] Current User ID: $uid");
        if (uid != null) {
          debugPrint("[Settings] Querying Firestore for member trips...");
          final snapshot = await FirebaseFirestore.instance
              .collection('trips')
              .where('memberIds', arrayContains: uid)
              .orderBy('date', descending: true)
              .limit(1)
              .get();

          debugPrint("[Settings] Snapshot docs count: ${snapshot.docs.length}");
          if (snapshot.docs.isNotEmpty) {
            final doc = snapshot.docs.first;
            final data = doc.data();
            debugPrint(
              "[Settings] Found Member Trip: ${doc.id} | Status: ${data['travelPhase'] ?? data['status']} | Date: ${data['date']}",
            );
            tripId = doc.id;
          }
        } else {
          debugPrint("[Settings] UID is null, skipping Firestore query");
        }
      }

      if (tripId != null) {
        final trip = await TripService().getTrip(tripId);
        if (trip?.isSolo == true) {
          final soloTrip = trip!;
          if (mounted) {
            Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => TripPage(tripId: soloTrip.id),
              ),
            );
          }
          return;
        }
        debugPrint(
          "[Settings] Attempting to enter Member Mode for tripId: $tripId",
        );
        await ref.read(appSessionProvider.notifier).enterMemberMode(tripId);
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(const SnackBar(content: Text('メンバーモードに切り替わりました')));
          // SettingsPageを閉じて、RootGateの切り替えを表示させる
          Navigator.of(context).pop();
        }
      } else {
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(const SnackBar(content: Text('参加可能なTripが見つかりません')));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('エラー: $e')));
      }
    }
  }

  // 時刻表示用のヘルパー
  String _formatTime(DateTime dt) {
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  Future<void> _createDebugTrip() async {
    try {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('デバッグ用Tripを作成中...')));

      final now = AppClock.instance.now();
      final outboundTime = now.add(const Duration(minutes: 15));
      final returnTime = now.add(const Duration(hours: 2));

      // 1. Search outbound (Higashi-Sumida -> Nakaibori)
      final outboundBody = {
        'alat': '35.718754',
        'alon': '139.834261',
        'blat': '35.713601',
        'blon': '139.827539',
        'pref': 'time', // fast
        'start_time':
            "${outboundTime.hour.toString().padLeft(2, '0')}:${outboundTime.minute.toString().padLeft(2, '0')}",
        'target_date_str':
            "${outboundTime.year}-${outboundTime.month.toString().padLeft(2, '0')}-${outboundTime.day.toString().padLeft(2, '0')}",
      };

      final rOut = await ApiClient.post('/route', body: outboundBody);
      final cOutList = rOut['candidates'] as List? ?? [];
      if (cOutList.isEmpty) throw Exception('行き(Outbound)のルートが見つかりません');

      final cOutMap = Map<String, dynamic>.from(cOutList.first as Map);
      // Hack names if missing
      cOutMap['origin_name'] = '東墨田三丁目';
      cOutMap['destination_name'] = '中居堀';
      final candidateOut = Candidate.fromJson(cOutMap);

      // 2. Search inbound (Nakaibori -> Higashi-Sumida)
      final inboundBody = {
        'alat': '35.713601',
        'alon': '139.827539',
        'blat': '35.718754',
        'blon': '139.834261',
        'pref': 'time',
        'start_time':
            "${returnTime.hour.toString().padLeft(2, '0')}:${returnTime.minute.toString().padLeft(2, '0')}",
        'target_date_str':
            "${returnTime.year}-${returnTime.month.toString().padLeft(2, '0')}-${returnTime.day.toString().padLeft(2, '0')}",
      };

      final rIn = await ApiClient.post('/route', body: inboundBody);
      final cInList = rIn['candidates'] as List? ?? [];
      if (cInList.isEmpty) throw Exception('帰り(Inbound)のルートが見つかりません');

      final cInMap = Map<String, dynamic>.from(cInList.first as Map);
      cInMap['origin_name'] = '中居堀';
      cInMap['destination_name'] = '東墨田三丁目';
      final candidateIn = Candidate.fromJson(cInMap);

      // 3. Create Legs and Schedule
      final legs = [
        Leg(
          direction: LegDirection.outbound,
          status: LegStatus.confirmed,
          candidate: candidateOut,
          confirmedAt: now,
        ),
        Leg(
          direction: LegDirection.inbound,
          status: LegStatus.confirmed,
          candidate: candidateIn,
          confirmedAt: now,
        ),
      ];

      final schedule = createScheduleFromLegs(
        legs,
        userSelectedStartTime: outboundTime,
        userSelectedReturnTime: returnTime,
      );

      // 4. Create Trip
      final tripId = await TripService().createTrip(legs, schedule);

      // 5. Open as Leader
      if (mounted) {
        await ref.read(appSessionProvider.notifier).updateTripId(tripId);
        if (!mounted) return;
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => LeaderModePage(tripId: tripId)),
        );
      }
    } catch (e) {
      debugPrint('Diff debug trip failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('エラー: $e')));
      }
    }
  }

  Future<void> _deleteAllTrips() async {
    try {
      if (!mounted) return;
      final confirm = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('全データ削除'),
          content: const Text(
            '全ての「おでかけ」データを削除します。\n本当によろしいですか？\n※この操作は取り消せません。',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('キャンセル'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              style: TextButton.styleFrom(foregroundColor: Colors.red),
              child: const Text('削除する'),
            ),
          ],
        ),
      );

      if (confirm != true) return;

      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('削除中...')));
      }

      final snapshot = await FirebaseFirestore.instance
          .collection('trips')
          .get();
      final batch = FirebaseFirestore.instance.batch();
      for (final doc in snapshot.docs) {
        batch.delete(doc.reference);
      }
      await batch.commit();

      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('全てのデータを削除しました')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('エラー: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // 修正: ref.listen は build メソッド内で呼び出す
    ref.listen<LatLng?>(locationOverrideProvider, (prev, next) {
      setState(() {
        _manualLocationInput = next != null
            ? '${next.latitude},${next.longitude}'
            : '';
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
            child: Text(
              'ユーザー情報',
              style: TextStyle(
                color: Colors.blueGrey,
                fontWeight: FontWeight.bold,
                fontSize: 14,
              ),
            ),
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
            subtitle: Text(
              _userId ?? '読み込み中...',
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
            trailing: IconButton(
              icon: const Icon(Icons.copy, size: 20),
              onPressed: () {
                if (_userId != null) {
                  Clipboard.setData(ClipboardData(text: _userId!));
                  ScaffoldMessenger.of(
                    context,
                  ).showSnackBar(const SnackBar(content: Text('IDをコピーしました')));
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
                      onPressed: manualOverride != null
                          ? _clearManualLocation
                          : null,
                      child: const Text('クリアしてGPSに戻す'),
                    ),
                  ],
                ),
              ],
            ),
          ),

          if (_isStaffMode) ...[
            const Divider(),
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                '【デバッグ・管理者メニュー】',
                style: TextStyle(
                  color: Colors.red,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),

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
              leading: const Icon(Icons.bug_report, color: Colors.purple),
              title: const Text('Debug: 東墨田3-中居堀ルート作成'),
              subtitle: const Text('行き:15分後, 帰り:2時間後\n東墨田三丁目 ⇔ 中居堀'),
              onTap: _createDebugTrip,
            ),

            ListTile(
              leading: const Icon(Icons.delete_forever, color: Colors.red),
              title: const Text('【危険】全おでかけデータ削除'),
              subtitle: const Text('Firestoreのtripsコレクションを空にします'),
              onTap: _deleteAllTrips,
            ),

            ListTile(
              leading: const Icon(Icons.star, color: Colors.green),
              title: const Text('最新の旅を「リーダー」として開く'),
              subtitle: const Text('最後に作成されたTripの管理画面を表示'),
              onTap: _openLatestTripAsLeader,
            ),

            ListTile(
              leading: const Icon(Icons.description, color: Colors.blueGrey),
              title: const Text('お出かけ一覧・実施報告書'),
              subtitle: const Text('過去の旅の確認と報告書作成'),
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const TripListPage()),
                );
              },
            ),
          ],

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

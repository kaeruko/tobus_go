import 'package:flutter/cupertino.dart';
import 'package:flutter/foundation.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../core/api_client.dart';
import '../core/utils.dart';
import '../models/route_models.dart';
import '../models/leg_models.dart';
import '../widgets/bus_loading_indicator.dart';
import '../widgets/place_field.dart';
import '../widgets/route_card.dart';
import 'map_picker_page.dart';
import 'route_detail_page.dart';
import '../services/trip_service.dart';
import 'member_mode_page.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_session_provider.dart';
import '../models/trip_models.dart'; // 追加
import 'leader_mode_page.dart';
import 'package:flutter/material.dart' show TextField, InputDecoration, OutlineInputBorder, Icons, ElevatedButton, Colors, TextInputType, MaterialPageRoute, ScaffoldMessenger, SnackBar, Divider; // Material components

enum Preference { fewTransfers, shortTime }

class HomePage extends ConsumerStatefulWidget {
  final String title;
  final ValueListenable<int>? tabIndexListenable;
  const HomePage({super.key, this.title = '都営でGO', this.tabIndexListenable});

  @override
  ConsumerState<HomePage> createState() => HomePageState();
}

class HomePageState extends ConsumerState<HomePage> {
  final _from = TextEditingController(
    text: '',
  );
  final _to = TextEditingController(text: '0');
  String? _fromDesc;
  String? _toDesc;
  Preference pref = Preference.fewTransfers;
  DateTime _startTime = DateTime.now();
  List<Candidate> candidates = [];
  RouteMeta? _routeMeta;

  bool _loading = false;

  String? _routeJobId;
  bool _polling = false;

  // ★ 追加: 進行中の旅データ
  Trip? _activeTrip;
  bool _isLoadingTrip = false;

  Map<String, String> _buildRouteParams(
    double alat,
    double alon,
    double blat,
    double blon,
  ) {
    return {
      'alat': '$alat',
      'alon': '$alon',
      'blat': '$blat',
      'blon': '$blon',
      'pref': pref == Preference.fewTransfers
          ? 'fewTransfers'
          : 'shortTime',
      'time': '${_startTime.hour.toString().padLeft(2, '0')}:${_startTime.minute.toString().padLeft(2, '0')}',
      'date': '${_startTime.year}-${_startTime.month.toString().padLeft(2, '0')}-${_startTime.day.toString().padLeft(2, '0')}',
    };
  }

  void _showTimePicker() {
    showCupertinoModalPopup(
      context: context,
      builder: (ctx) => Container(
        height: 250,
        color: CupertinoColors.systemBackground,
        child: Column(
          children: [
            SizedBox(
              height: 180,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.dateAndTime,
                initialDateTime: _startTime,
                use24hFormat: true,
                onDateTimeChanged: (val) {
                  setState(() => _startTime = val);
                },
              ),
            ),
            CupertinoButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('完了'),
            )
          ],
        ),
      ),
    );
  }

  List<Candidate> _parseCandidatesFromJson(Map<String, dynamic> j) {
    print('[DEBUG] _parseCandidatesFromJson input: $j');
    final raw = j['candidates'] as List?;
    if (raw == null) {
      print('[DEBUG] "candidates" key is null or missing');
      return const [];
    }
    print('[DEBUG] raw candidates length: ${raw.length}');

    final currentPref = pref == Preference.fewTransfers ? 'fewTransfers' : 'shortTime';

    final list = raw.map((e) {
      final map = e as Map<String, dynamic>;
      map['origin_name'] = _fromDesc;
      map['destination_name'] = _toDesc;
      map['preference'] = currentPref;
      return Candidate.fromJson(map);
    }).toList();

    for (var i = 0; i < list.length; i++) {
      final candidate = list[i];
      final lastStep = candidate.steps.isNotEmpty ? candidate.steps.last : null;
      final lastKind = lastStep?.kind ?? '(none)';
      final buffer = StringBuffer(
        '[DEBUG] Candidate[$i] destinationName=${candidate.destinationName} lastStep.to=${lastStep?.to} lastStep.kind=$lastKind',
      );
      if (lastStep != null && lastStep.kind != 'walk') {
        buffer.write(', lastStep.edges=${lastStep.edges}, lastStep.minutes=${lastStep.minutes}');
      }
      print(buffer.toString());
    }

    return list;
  }

  @override
  void initState() {
    super.initState();
    print('[DEBUG] initState called');
    _recompute();
    _checkActiveTrip(); // ★ 追加: 起動時にチェック
    widget.tabIndexListenable?.addListener(_handleTabChange);
    _from.addListener(() {
      print('[DEBUG] _from changed: ${_from.text}');
      _recompute();
    });
    _to.addListener(() {
      print('[DEBUG] _to changed: ${_to.text}');
      _recompute();
    });
  }

  @override
  void didUpdateWidget(covariant HomePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tabIndexListenable != widget.tabIndexListenable) {
      oldWidget.tabIndexListenable?.removeListener(_handleTabChange);
      widget.tabIndexListenable?.addListener(_handleTabChange);
    }
  }

  // ★ 追加: 現在進行中のグループがあるか確認する
  Future<void> _checkActiveTrip() async {
    setState(() => _isLoadingTrip = true);
    try {
      final trip = await TripService().getActiveTrip();

      if (mounted) {
        final shouldShow = trip != null &&
            trip.status != TripStatus.completed &&
            trip.status != TripStatus.cancelled;
        setState(() {
          _activeTrip = shouldShow ? trip : null;
        });
      }
    } catch (e) {
      print("[DEBUG] Failed to load active trip: $e");
    } finally {
      if (mounted) setState(() => _isLoadingTrip = false);
    }
  }

  void _handleTabChange() {
    if (widget.tabIndexListenable?.value == 0) {
      _checkActiveTrip();
    }
  }

  void _swap() {
    final a = _from.text;
    _from.text = _to.text;
    _to.text = a;
    final aDesc = _fromDesc;
    _fromDesc = _toDesc;
    _toDesc = aDesc;
  }

  Future<void> _openMap(bool forA) async {
    final res = await Navigator.of(context).push<LatLng>(
      CupertinoPageRoute(builder: (_) => const MapPickerPage(title: '地図から選ぶ')),
    );
    if (res == null) return;
    final s = "${res.latitude},${res.longitude}";
    if (forA) {
      _from.text = s;
      _fromDesc = '地図で選んだ地点';
    } else {
      _to.text = s;
      _toDesc = '地図で選んだ地点';
    }
  }

  Future<void> _recompute() async {
    print('[DEBUG] _recompute called: from=${_from.text}, to=${_to.text}');
    final a = parseLatLon(_from.text);
    final b = _to.text == '0' ? null : parseLatLon(_to.text);
    print('[DEBUG] parseLatLon results: a=$a, b=$b');

    setState(() {
      // _aErr = a == null ? '緯度,経度 で入力' : null;
      // _bErr = b == null ? '緯度,経度 で入力' : null;
    });

    if (a == null || b == null) {
      print('[DEBUG] Invalid coordinates, clearing candidates');
      if (mounted) {
        setState(() {
          candidates = [];
          _loading = false;
          _hasSearched = false;
          _routeMeta = null;
        });
      }
      _cancelPolling(); // 進行中のジョブがあれば止める
      return;
    }

    // 既存ジョブはキャンセルして、新しいジョブ開始
    print('[DEBUG] Starting route job...');
    print('[DEBUG] [RouteRequest] destination lat=${b.$1}, lon=${b.$2}');
    setState(() => _hasSearched = true);
    _cancelPolling();
    await _startRouteJob(a.$1, a.$2, b.$1, b.$2);
  }


  Future<void> _startRouteJob(
    double alat,
    double alon,
    double blat,
    double blon,
  ) async {
    print('[DEBUG] _startRouteJob called: ($alat, $alon) -> ($blat, $blon)');
    setState(() {
      _loading = true;
      candidates = [];
      _routeMeta = null;
    });

    try {
      final params = _buildRouteParams(alat, alon, blat, blon);
      print('[DEBUG] [RouteRequest] about to call /route with destination lat=$blat, lon=$blon');
      print('[DEBUG] Calling API /route with params: $params');
      final j = await ApiClient.post('/route', body: params);
      print('[DEBUG] API response: $j');
      
      final jobId = j['job_id']?.toString();
      if (jobId == null || jobId.isEmpty) {
        throw Exception('job_id が返ってきませんでした');
      }

      print('[DEBUG] Got job_id: $jobId, starting polling');
      _routeJobId = jobId;
      _polling = true;
      _pollRoute(jobId); // 非同期ポーリング開始
    } catch (e) {
      print('[DEBUG] Error in _startRouteJob: $e');
      if (!mounted) return;
      setState(() {
        _loading = false;
      });
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('経路検索を開始できませんでした: $e'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
    }
  }

  Future<void> _pollRoute(String jobId) async {
    print('[DEBUG] _pollRoute called for jobId: $jobId');
    // ジョブがキャンセルされていたり、別ジョブになっていたら終了
    if (!_polling || !mounted) {
      print('[DEBUG] Polling stopped: _polling=$_polling, mounted=$mounted');
      return;
    }
    if (_routeJobId != jobId) {
      print('[DEBUG] Job mismatch: current=$_routeJobId, requested=$jobId');
      return;
    }

    try {
      print('[DEBUG] Polling /route for jobId: $jobId');
      final j = await ApiClient.get('/route', params: {'job_id': jobId});
      final status = j['status']?.toString() ?? 'unknown';
      print('[DEBUG] Poll response status: $status');

      if (!mounted || !_polling || _routeJobId != jobId) return;

      if (status == 'pending' || status == 'running') {
        // まだ計算中 → 少し待ってから再度ポーリング
        Future.delayed(const Duration(seconds: 10), () {
          _pollRoute(jobId);
        });
        return;
      }

      if (status == 'done') {
        print('[DEBUG] Job done. Full response: $j');
        final result = j['result'];
        print('[DEBUG] Result part: $result');

        List<Candidate> list = const [];
        RouteMeta? meta;
        if (result is Map<String, dynamic>) {
          final metaJson = result['meta'];
          if (metaJson is Map<String, dynamic>) {
            meta = RouteMeta.fromJson(metaJson);
          }
          list = _parseCandidatesFromJson(result);
        } else {
          print('[DEBUG] result is NOT a Map<String, dynamic>: ${result.runtimeType}');
        }

        print('[DEBUG] Parsed candidates count: ${list.length}');

        setState(() {
          candidates = list;
          _routeMeta = meta;
          _loading = false;
        });
        _polling = false;
        return;
      }

      // error / unknown
      setState(() {
        _loading = false;
        _routeMeta = null;
      });
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('経路計算に失敗しました (Status: $status)'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
      _polling = false;
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _routeMeta = null;
      });
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('経路検索中にエラーが発生しました: $e'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
      _polling = false;
    }
  }

  void _cancelPolling() {
    _polling = false;
    _routeJobId = null;
  }

  bool _hasSearched = false;

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(widget.title),
      ),
      child: SafeArea(
        child: CustomScrollView(
          slivers: [
            // ★ 追加: 進行中の旅があればトップに表示
            if (_activeTrip != null)
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: _ActiveTripCard(
                    trip: _activeTrip!,
                    onTap: () {
                      // 詳細画面へ遷移
                      Navigator.push(
                        context,
                        CupertinoPageRoute(
                          builder: (_) => LeaderModePage(tripId: _activeTrip!.id),
                        ),
                      ).then((_) {
                        // 戻ってきたら状態を再確認（解散したかもしれないので）
                        _checkActiveTrip();
                      });
                    },
                  ),
                ),
              ),
            SliverToBoxAdapter(
              child: Column(
                children: [
                  const SizedBox(height: 8),

            // 出発Aの検索バー
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: PlaceField(
                label: '出発(検索)',
                onPicked: (lat, lon, desc) {
                  final txt = '$lat,$lon';
                  setState(() => _fromDesc = desc);
                  if (_from.text == txt) {
                    _recompute(); // 同じ場所でも再検索
                  } else {
                    _from.text = txt;
                  }
                },
              ),
            ),
            const SizedBox(height: 4),
            // 出発側のスワップ＋地図ボタン（フォームは出さない）
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  CupertinoButton(
                    padding: const EdgeInsets.all(8),
                    child: const Icon(CupertinoIcons.arrow_up_arrow_down),
                    onPressed: _swap,
                  ),
                  CupertinoButton(
                    padding: const EdgeInsets.all(8),
                    child: const Icon(CupertinoIcons.map_pin),
                    onPressed: () => _openMap(true),
                  ),
                ],
              ),
            ),

            const SizedBox(height: 8),

            // 到着Bの検索バー
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: PlaceField(
                label: '到着(検索)',
                onPicked: (lat, lon, desc) {
                  print(
                    '[DEBUG] Destination onPicked received desc=$desc, lat=$lat, lon=$lon',
                  );
                  final txt = '$lat,$lon';
                  setState(() => _toDesc = desc);
                  print('[DEBUG] _toDesc updated: $_toDesc');
                  if (_to.text == txt) {
                    _recompute();
                  } else {
                    _to.text = txt;
                  }
                  print('[DEBUG] _to.text updated: ${_to.text}');
                },
              ),
            ),
            const SizedBox(height: 4),
            // 到着側の地図ボタンだけ（フォームなし）
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: Align(
                alignment: Alignment.centerRight,
                child: CupertinoButton(
                  padding: const EdgeInsets.all(8),
                  child: const Icon(CupertinoIcons.map_pin),
                  onPressed: () => _openMap(false),
                ),
              ),
            ),

            const SizedBox(height: 4),

            // 乗換少ない／時間短い
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: CupertinoSlidingSegmentedControl<Preference>(
                groupValue: pref,
                children: const {
                  Preference.fewTransfers: Text('乗換少ない優先'),
                  Preference.shortTime: Text('時間短い優先'),
                },
                onValueChanged: (v) {
                  if (v == null) return;
                  setState(() {
                    pref = v;
                    _recompute();
                  });
                },
              ),
            ),
            
            // --- 日時選択 ---
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: GestureDetector(
                onTap: _showTimePicker,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                  decoration: BoxDecoration(
                    color: CupertinoColors.white,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: CupertinoColors.separator),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('出発日時', style: TextStyle(fontSize: 14)),
                      Text(
                        '${_startTime.month}/${_startTime.day} ${_startTime.hour.toString().padLeft(2, '0')}:${_startTime.minute.toString().padLeft(2, '0')}',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: CupertinoColors.activeBlue,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 24),

                  const SizedBox(height: 24),
                ],
              ),
            ),

            if (_routeMeta?.destinationReachable == false)
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
                  child: _FallbackNotice(meta: _routeMeta!),
                ),
              ),

            // 結果リスト
            if (_loading)
              SliverFillRemaining(
                hasScrollBody: false,
                child: Center(
                  child: Container(
                    width: 160,
                    height: 160,
                    decoration: BoxDecoration(
                      color: CupertinoColors.systemBackground,
                      borderRadius: BorderRadius.circular(16),
                      boxShadow: [
                        BoxShadow(
                          color: CupertinoColors.systemGrey.withOpacity(0.2), // withValues(alpha:0.2) is newer, stick to existing or standard
                          blurRadius: 10,
                          offset: const Offset(0, 4),
                        ),
                      ],
                    ),
                    child: const FittedBox(
                      fit: BoxFit.scaleDown,
                      child: BusLoadingIndicator(),
                    ),
                  ),
                ),
              )
            else if (candidates.isEmpty)
              SliverFillRemaining(
                hasScrollBody: false,
                child: Center(
                  child: Text(
                    _hasSearched ? '経路が見つかりませんでした' : '出発と到着を選択',
                    style: TextStyle(
                      color: _hasSearched ? CupertinoColors.systemRed : CupertinoColors.systemGrey,
                    ),
                  ),
                ),
              )
            else
              SliverList(
                delegate: SliverChildBuilderDelegate(
                  (context, i) {
                    final c = candidates[i];
                    return Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 6.0),
                      child: GestureDetector(
                        onTap: () {
                          Navigator.of(context).push(
                            CupertinoPageRoute(
                              builder: (_) => RouteDetailPage(candidate: c, meta: _routeMeta),
                            ),
                          );
                        },
                        child: RouteCard(candidate: c, rank: i + 1, meta: _routeMeta),
                      ),
                    );
                  },
                  childCount: candidates.length,
                ),
              ),
              
            // Bottom padding
            const SliverPadding(padding: EdgeInsets.only(bottom: 24)),
          ],
        ),
      ),
    );
  }

  
  Future<void> _joinTrip(BuildContext context, String code) async {
    if (code.length < 4) return; // 簡易チェック

    try {
      final tripService = TripService();
      // 参加処理 (Firestore更新)
      // 参加処理 (Firestore更新)
      final tripId = await tripService.joinTrip(code);

      // IDを保存してモード切り替え
      if (!context.mounted) return;
      await ref.read(appSessionProvider.notifier).enterMemberMode(tripId);

      // メンバー画面へGO! (RootGateが切り替えるので、ここでは何もしなくて良い)
      // Stackに残っているダイアログ等は RootGate の再構築で消えるはずだが、
      // 万が一残る場合は RootGate 側で key を変える等の対応が必要。
      // 現状はシンプルに何もしない。

    } catch (e) {
      if (!context.mounted) return;
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('参加できませんでした: $e'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
    }
  }

  @override
  void dispose() {
    _from.removeListener(_recompute);
    _to.removeListener(_recompute);
    widget.tabIndexListenable?.removeListener(_handleTabChange);
    _from.dispose();
    _to.dispose();
    _polling = false;
    _routeJobId = null;
    super.dispose();
  }
}

class _FallbackNotice extends StatelessWidget {
  final RouteMeta meta;
  const _FallbackNotice({required this.meta});

  @override
  Widget build(BuildContext context) {
    final stopName = meta.fallbackNodeName ?? '最寄り停留所';
    final walkMinutes = meta.fallbackWalkMinutes;
    final distance = meta.fallbackDistanceM;
    String walkText;
    if (walkMinutes != null) {
      walkText = '徒歩約${walkMinutes}分';
    } else if (distance != null) {
      final formatted = distance >= 1000
          ? '${(distance / 1000).toStringAsFixed(1)}km'
          : '${distance.toStringAsFixed(0)}m';
      walkText = '徒歩${formatted}程度';
    } else {
      walkText = '徒歩圏内';
    }

    final limitText = meta.walkLimitM != null
        ? '（徒歩上限${meta.walkLimitM}m内で探索）'
        : '';

    return Container(
      decoration: BoxDecoration(
        color: CupertinoColors.systemYellow.withOpacity(0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: CupertinoColors.systemYellow),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(CupertinoIcons.exclamationmark_triangle_fill,
                  color: CupertinoColors.systemOrange),
              SizedBox(width: 8),
              Text(
                '目的地までの都営経路が見つかりません',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  color: CupertinoColors.activeOrange,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '都営だけでは${meta.destinationLabel}の近くまで行けません。最寄りは「$stopName」で、ここから$walkText。',
            style: const TextStyle(fontSize: 14),
          ),
          const SizedBox(height: 4),
          Text(
            'それでもこの経路を使いますか？$limitText',
            style: const TextStyle(
              color: CupertinoColors.inactiveGray,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}

// ★ 追加: ホーム画面に表示する「進行中の旅」カード
class _ActiveTripCard extends StatelessWidget {
  final Trip trip;
  final VoidCallback onTap;

  const _ActiveTripCard({required this.trip, required this.onTap});

  @override
  Widget build(BuildContext context) {
    String displayTitle = trip.title;
    if (trip.legs.isNotEmpty) {
      final outbound = trip.legs.firstWhere(
        (l) => l.direction == LegDirection.outbound,
        orElse: () => trip.legs.first,
      );
      final dest = outbound.candidate.destinationName;
      if (dest != null && dest.isNotEmpty) {
        displayTitle = '$dest への遠足';
      }
    }

    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          // 目立つようにグラデーションや色をつける
          gradient: LinearGradient(
            colors: [Colors.orange.shade400, Colors.deepOrange.shade400],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(16),
          boxShadow: [
            BoxShadow(
              color: Colors.orange.withOpacity(0.3),
              blurRadius: 8,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          children: [
            const Icon(Icons.directions_bus_filled, color: Colors.white, size: 32),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "現在進行中のグループ",
                    style: TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    displayTitle,
                    style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: Colors.white.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          trip.status == TripStatus.planning ? "計画中" : "移動中",
                          style: const TextStyle(color: Colors.white, fontSize: 10),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        "${trip.participants.length}人が参加中",
                        style: const TextStyle(color: Colors.white, fontSize: 12),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_ios, color: Colors.white54, size: 16),
          ],
        ),
      ),
    );
  }
}

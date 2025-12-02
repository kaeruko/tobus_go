import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../core/api_client.dart';
import '../core/utils.dart';
import '../models/route_models.dart';
import '../widgets/bus_loading_indicator.dart';
import '../widgets/place_field.dart';
import '../widgets/route_card.dart';
import 'map_picker_page.dart';
import 'route_detail_page.dart';

enum Preference { fewTransfers, shortTime }

class HomePage extends StatefulWidget {
  final String title;
  const HomePage({super.key, this.title = '都営でGO'});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _from = TextEditingController(
    text: '',
  );
  final _to = TextEditingController(text: '35.700, 139.800'); // 錦糸町あたり
  Preference pref = Preference.fewTransfers;
  DateTime _startTime = DateTime.now();
  List<Candidate> candidates = [];

  bool _loading = false;

  String? _routeJobId;
  bool _polling = false;

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
    };
  }

  void _showTimePicker() {
    showCupertinoModalPopup(
      context: context,
      builder: (_) => Container(
        height: 250,
        color: CupertinoColors.systemBackground,
        child: Column(
          children: [
            SizedBox(
              height: 180,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.time,
                initialDateTime: _startTime,
                use24hFormat: true,
                onDateTimeChanged: (val) {
                  setState(() => _startTime = val);
                },
              ),
            ),
            CupertinoButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('完了'),
            )
          ],
        ),
      ),
    );
  }

  List<Candidate> _parseCandidatesFromJson(Map<String, dynamic> j) {
    final raw = j['candidates'] as List?;
    if (raw == null) return const [];

    final currentPref = pref == Preference.fewTransfers ? 'fewTransfers' : 'shortTime';

    return raw.map((e) {
      final map = e as Map<String, dynamic>;
      map['preference'] = currentPref;
      return Candidate.fromJson(map);
    }).toList();
  }

  @override
  void initState() {
    super.initState();
    _recompute();
    _from.addListener(_recompute);
    _to.addListener(_recompute);
  }

  void _swap() {
    final a = _from.text;
    _from.text = _to.text;
    _to.text = a;
  }

  Future<void> _openMap(bool forA) async {
    final res = await Navigator.of(context).push<LatLng>(
      CupertinoPageRoute(builder: (_) => const MapPickerPage(title: '地図から選ぶ')),
    );
    if (res == null) return;
    final s = "${res.latitude},${res.longitude}";
    if (forA) {
      _from.text = s;
    } else {
      _to.text = s;
    }
  }

  Future<void> _recompute() async {
    final a = parseLatLon(_from.text);
    final b = parseLatLon(_to.text);

    setState(() {
      // _aErr = a == null ? '緯度,経度 で入力' : null;
      // _bErr = b == null ? '緯度,経度 で入力' : null;
    });

    if (a == null || b == null) {
      setState(() {
        candidates = [];
        _loading = false;
      });
      _cancelPolling(); // 進行中のジョブがあれば止める
      return;
    }

    // 既存ジョブはキャンセルして、新しいジョブ開始
    _cancelPolling();
    await _startRouteJob(a.$1, a.$2, b.$1, b.$2);
  }


  Future<void> _startRouteJob(
    double alat,
    double alon,
    double blat,
    double blon,
  ) async {
    setState(() {
      _loading = true;
      candidates = [];
    });

    try {
      final params = _buildRouteParams(alat, alon, blat, blon);
      final j = await ApiClient.post('/route', body: params);
      
      final jobId = j['job_id']?.toString();
      if (jobId == null || jobId.isEmpty) {
        throw Exception('job_id が返ってきませんでした');
      }

      _routeJobId = jobId;
      _polling = true;
      _pollRoute(jobId); // 非同期ポーリング開始
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        // _aErr = 'APIエラー: $e';
      });
    }
  }

  Future<void> _pollRoute(String jobId) async {
    // ジョブがキャンセルされていたり、別ジョブになっていたら終了
    if (!_polling || !mounted) return;
    if (_routeJobId != jobId) return;

    try {
      final j = await ApiClient.get('/route', params: {'job_id': jobId});
      final status = j['status']?.toString() ?? 'unknown';

      if (!mounted || !_polling || _routeJobId != jobId) return;

      if (status == 'pending' || status == 'running') {
        // まだ計算中 → 少し待ってから再度ポーリング
        Future.delayed(const Duration(seconds: 50), () {
          _pollRoute(jobId);
        });
        return;
      }

      if (status == 'done') {
        final result = j['result'];
        List<Candidate> list = const [];
        if (result is Map<String, dynamic>) {
          list = _parseCandidatesFromJson(result);
        }

        setState(() {
          candidates = list;
          _loading = false;
        });
        _polling = false;
        return;
      }

      // error / unknown
      setState(() {
        _loading = false;
        // _aErr = '経路計算に失敗しました ($status)';
      });
      _polling = false;
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        // _aErr = 'ポーリング中エラー: $e';
      });
      _polling = false;
    }
  }

  void _cancelPolling() {
    _polling = false;
    _routeJobId = null;
  }

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(widget.title),
      ),
      child: SafeArea(
        child: Column(
          children: [
            const SizedBox(height: 8),

            // 出発Aの検索バー
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: PlaceField(
                label: '出発(検索)',
                onPicked: (lat, lon, desc) {
                  _from.text = '$lat,$lon'; // ここで内部的に lat,lon を持つ
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
                  _to.text = '$lat,$lon';
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

            const SizedBox(height: 16),
            
            // --- 時刻選択 ---
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
                      const Text('出発時刻', style: TextStyle(fontSize: 14)),
                      Text(
                        '${_startTime.hour.toString().padLeft(2, '0')}:${_startTime.minute.toString().padLeft(2, '0')}',
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

            // 結果リスト
            Expanded(
              child: _loading
                  ? const Center(child: BusLoadingIndicator())
                  : (candidates.isEmpty
                      ? const Center(child: Text('出発と到着を選択'))
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                          itemCount: candidates.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(height: 12),
                          itemBuilder: (context, i) {
                            final c = candidates[i];
                            return GestureDetector(
                              onTap: () {
                                Navigator.of(context).push(
                                  CupertinoPageRoute(
                                    builder: (_) =>
                                        RouteDetailPage(candidate: c),
                                  ),
                                );
                              },
                              child: RouteCard(candidate: c, rank: i + 1),
                            );
                          },
                        )),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _from.removeListener(_recompute);
    _to.removeListener(_recompute);
    _from.dispose();
    _to.dispose();
    _polling = false;
    _routeJobId = null;
    super.dispose();
  }
}

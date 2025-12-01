  import 'dart:convert';
  import 'package:google_maps_flutter/google_maps_flutter.dart';
  import 'package:http/http.dart' as http;
  import 'package:flutter/cupertino.dart';
  import 'package:flutter/foundation.dart';

  Map<String, dynamic> _jsonUtf8(http.Response r) {
    final body = utf8.decode(r.bodyBytes);
    return json.decode(body) as Map<String, dynamic>;
  }

  // シミュレータは 127.0.0.1。実機ならMacのLAN IPに置き換え
  const String kApiBase = 'http://127.0.0.1:8000';

  // 簡易的なグローバル保存領域 (メモリのみ)
  final List<Candidate> kSavedRoutes = [];

  // -------------------- API Client (共通化) --------------------
  class ApiClient {
    static void _log(String message) {
      if (kDebugMode) {
        print('[API] $message');
      }
    }

    static Future<Map<String, dynamic>> get(String path, {Map<String, String>? params}) async {
      final uri = Uri.parse('$kApiBase$path').replace(queryParameters: params);
      _log('GET $uri');
      
      try {
        final r = await http.get(uri);
        _log('GET $uri -> ${r.statusCode}');
        
        if (r.statusCode != 200) {
          throw Exception('HTTP ${r.statusCode}');
        }
        
        final json = _jsonUtf8(r);
        _log('Response: ${json.toString().substring(0, json.toString().length > 200 ? 200 : json.toString().length)}...');
        return json;
      } catch (e) {
        _log('GET $uri -> ERROR: $e');
        rethrow;
      }
    }

    static Future<Map<String, dynamic>> post(String path, {Map<String, String>? body}) async {
      final uri = Uri.parse('$kApiBase$path');
      _log('POST $uri body=$body');
      
      try {
        final r = await http.post(uri, body: body);
        _log('POST $uri -> ${r.statusCode}');
        
        if (r.statusCode != 200) {
          throw Exception('HTTP ${r.statusCode}');
        }
        
        final json = _jsonUtf8(r);
        _log('Response: ${json.toString().substring(0, json.toString().length > 200 ? 200 : json.toString().length)}...');
        return json;
      } catch (e) {
        _log('POST $uri -> ERROR: $e');
        rethrow;
      }
    }
  }

  void main() => runApp(const App());

  class App extends StatelessWidget {
    const App({super.key});
    @override
    Widget build(BuildContext context) {
      return const CupertinoApp(
        debugShowCheckedModeBanner: false,
        title: 'Toei Route Demo',
        home: RootTabs(),
      );
    }
  }

  class RootTabs extends StatelessWidget {
    const RootTabs({super.key});

    @override
    Widget build(BuildContext context) {
      return CupertinoTabScaffold(
        tabBar: CupertinoTabBar(
          items: const [
            BottomNavigationBarItem(
              icon: Icon(CupertinoIcons.search),
              label: '検索',
            ),
            BottomNavigationBarItem(
              icon: Icon(CupertinoIcons.time),
              label: 'ライブ',
            ),
            BottomNavigationBarItem(
              icon: Icon(CupertinoIcons.bookmark),
              label: 'My Route',
            ),
          ],
        ),
        tabBuilder: (context, index) {
          switch (index) {
            case 0:
              return CupertinoTabView(builder: (context) => const HomePage());
            case 1:
              return CupertinoTabView(builder: (context) => const LivePage());
            case 2:
              return CupertinoTabView(builder: (context) => const MyRoutePage());
            default:
              return CupertinoTabView(builder: (context) => const HomePage());
          }
        },
      );
    }
  }

  enum Preference { fewTransfers, shortTime }

  class HomePage extends StatefulWidget {
    final String title;
    const HomePage({super.key, this.title = 'Home'});

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
    String? _aErr;
    String? _bErr;
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
                child: const Text('完了'),
                onPressed: () => Navigator.pop(context),
              )
            ],
          ),
        ),
      );
    }

    List<Candidate> _parseCandidatesFromJson(Map<String, dynamic> j) {
      final raw = j['candidates'] as List?;
      if (raw == null) return const [];

      return raw
          .map((e) => Candidate.fromJson(e as Map<String, dynamic>))
          .toList();
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
      final a = _parseLatLon(_from.text);
      final b = _parseLatLon(_to.text);

      setState(() {
        _aErr = a == null ? '緯度,経度 で入力' : null;
        _bErr = b == null ? '緯度,経度 で入力' : null;
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
          _aErr = 'APIエラー: $e';
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
          _aErr = '経路計算に失敗しました ($status)';
        });
        _polling = false;
      } catch (e) {
        if (!mounted) return;
        setState(() {
          _loading = false;
          _aErr = 'ポーリング中エラー: $e';
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
          middle: Text(widget.title ?? '地図から選ぶ'),
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


  (String, String)? _splitComma(String s) {
    final i = s.indexOf(',');
    if (i <= 0) return null;
    final a = s.substring(0, i).trim();
    final b = s.substring(i + 1).trim();
    if (a.isEmpty || b.isEmpty) return null;
    return (a, b);
  }

  (double, double)? _parseLatLon(String s) {
    var t = s.trim();
    // 全角→半角、全角カンマ対応
    const full2half = {
      '０': '0',
      '１': '1',
      '２': '2',
      '３': '3',
      '４': '4',
      '５': '5',
      '６': '6',
      '７': '7',
      '８': '8',
      '９': '9',
      '－': '-',
      '，': ',',
      '．': '.',
    };
    t = t.split('').map((ch) => full2half[ch] ?? ch).join();
    // 数字・符号・小数点・カンマ以外を除去（カッコなどを消す）
    t = t.replaceAll(RegExp(r'[^\d\.\-\,]'), '');
    final sp = _splitComma(t);
    if (sp == null) return null;
    final lat = double.tryParse(sp.$1);
    final lon = double.tryParse(sp.$2);
    if (lat == null || lon == null) return null;
    if (lat.abs() > 90 || lon.abs() > 180) return null;
    return (lat, lon);
  }

  class _CupertinoCoordInput extends StatelessWidget {
    final String label;
    final TextEditingController controller;
    final String? error;
    const _CupertinoCoordInput({
      required this.label,
      required this.controller,
      this.error,
    });
    @override
    Widget build(BuildContext context) {
      final borderColor = error == null
          ? CupertinoColors.separator
          : CupertinoColors.systemRed;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 6),
            child: Text(
              label,
              style: const TextStyle(
                color: CupertinoColors.inactiveGray,
                fontSize: 12,
              ),
            ),
          ),
          Container(
            decoration: BoxDecoration(
              color: CupertinoColors.white,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: borderColor, width: 1),
            ),
            child: CupertinoTextField(
              controller: controller,
              placeholder: '例) 35.68,139.76',
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              keyboardType: const TextInputType.numberWithOptions(
                signed: true,
                decimal: true,
              ),
            ),
          ),
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(top: 4, left: 4),
              child: Text(
                error!,
                style: const TextStyle(
                  color: CupertinoColors.systemRed,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      );
    }
  }

  class Candidate {
    final String id;
    final List<String> lines;
    final int rides;
    final int walks;
    final int boards;
    final int transfers;
    final int total;
    final List<StepSeg> steps;
    final List<LatLng> points;

    Candidate({
      required this.id,
      required this.lines,
      required this.rides,
      required this.walks,
      required this.boards,
      required this.transfers,
      required this.total,
      required this.steps,
      required this.points,
    });


    static List<StepSeg> _readSteps(Map<String, dynamic> j) {
      final out = <StepSeg>[];
      final raw = j['steps'];
      if (raw is List) {
        for (final item in raw) {
          if (item is Map) {
            out.add(StepSeg.fromJson(Map<String, dynamic>.from(item)));
          }
        }
      }
      return out;
    }

    factory Candidate.fromJson(Map<String, dynamic> j) {
      return Candidate(
        id: j['id']?.toString() ?? '',
        lines: (j['lines'] is List) ? List<String>.from(j['lines']) : const [],
        rides: (j['rides'] as num? ?? 0).toInt(),
        walks: (j['walks'] as num? ?? 0).toInt(),
        boards: (j['boards'] as num? ?? 0).toInt(),
        transfers: (j['transfers'] as num? ?? 0).toInt(),
        total: (j['total'] as num? ?? 0).toInt(),
        steps: _readSteps(j),
        points: (j['points'] as List?)
                ?.map((e) => (e is List && e.length >= 2)
                    ? LatLng((e[0] as num).toDouble(), (e[1] as num).toDouble())
                    : const LatLng(0, 0))
                .toList() ??
            const [],
      );
    }

  }

  class StepSeg {
    final String kind;    // 'walk' | 'bus' | 'rail'
    final String title;
    final int edges;
    final int? minutes;
    final int? meters;
    final int? fareYen;
    final String? from;
    final String? to;
    final String? departureTime;
    final String? arrivalTime;

    // ★ 追加
    final List<StopPoint> stops;

    StepSeg({
      required this.kind,
      required this.title,
      required this.edges,
      this.minutes,
      this.meters,
      this.fareYen,
      this.from,
      this.to,
      this.departureTime,
      this.arrivalTime,
      List<StopPoint>? stops,
    }) : stops = stops ?? const [];

    factory StepSeg.fromJson(Map<String, dynamic> j) {
      final rawStops = j['stops'] as List? ?? const [];
      final stops = <StopPoint>[];
      for (final v in rawStops) {
        if (v is Map) {
          stops.add(StopPoint.fromJson(Map<String, dynamic>.from(v)));
        }
      }

      return StepSeg(
        kind: j['kind']?.toString() ?? 'bus',
        title: j['title']?.toString() ?? '',
        edges: (j['edges'] as num? ?? 0).toInt(),
        minutes: (j['minutes'] as num?)?.toInt(),
        meters: (j['meters'] as num?)?.toInt(),
        fareYen: (j['fareYen'] as num?)?.toInt(),
        from: j['from_']?.toString() ?? j['from']?.toString(),
        to: j['to']?.toString(),
        departureTime: j['departure_time']?.toString(),
        arrivalTime: j['arrival_time']?.toString(),
        stops: stops,
      );
    }

    String get mainTitle => kind == 'walk' ? '徒歩' : title;
    String? get subTitle {
      // from/to が両方あるなら優先して出す
      if (from != null && to != null) {
        // 徒歩なら距離 or 時間をオマケ表示
        if (kind == 'walk') {
          String extra = '';
          if (minutes != null) {
            extra = '（約${minutes}分）';
          } else if (meters != null) {
            extra = '（約${meters}m）';
          }
          return '$from → $to$extra';
        }
        // バス・電車はそのまま
        return '$from → $to';
      }

      // from/to が無いときだけ、従来の歩きフォールバック
      if (kind == 'walk') {
        if (meters != null)   return '徒歩 約${meters}m';
        if (minutes != null)  return '徒歩 約${minutes}分';
        return '徒歩';
      }

      return null;
    }

  }



  class RouteEngine {
    // 仮の重み（Pythonと揃える）
    static const int ride = 1;
    static const int board = 30;
    static const int walk = 60;

    static List<Candidate> computeByCoords({
      required double alat,
      required double alon,
      required double blat,
      required double blon,
      required Preference pref,
    }) {
      // 実際はバックエンド（Python）に投げて候補3件を受け取る。
      // ここはデモ：上23→上60 / 上23→草64 / 上23→都08→草64 を返す。
      final c1 = _build(
        id: 'A',
        lines: ['上23', '上60'],
        rides: 47,
        walks: 2,
        boards: 2,
        transfers: 1,
        steps: [
          StepSeg(kind: 'bus', title: '上23 A最寄り→上野松坂屋前', edges: 26),
          StepSeg(kind: 'walk', title: '徒歩 上野松坂屋前→上野広小路', edges: 1),
          StepSeg(kind: 'bus', title: '上60 上野広小路→B最寄り', edges: 21),
        ],
      );
      final c2 = _build(
        id: 'B',
        lines: ['上23', '草64'],
        rides: 48,
        walks: 2,
        boards: 2,
        transfers: 1,
        steps: [
          StepSeg(kind: 'bus', title: '上23 A最寄り→浅草雷門', edges: 18),
          StepSeg(kind: 'walk', title: '徒歩 雷門乗換', edges: 1),
          StepSeg(kind: 'bus', title: '草64 雷門→B最寄り', edges: 30),
        ],
      );
      final c3 = _build(
        id: 'C',
        lines: ['上23', '都08', '草64'],
        rides: 49,
        walks: 2,
        boards: 3,
        transfers: 2,
        steps: [
          StepSeg(kind: 'bus', title: '上23 A最寄り→スカイツリー入口', edges: 14),
          StepSeg(kind: 'bus', title: '都08 入口→二天門', edges: 4),
          StepSeg(kind: 'walk', title: '徒歩 二天門乗換', edges: 1),
          StepSeg(kind: 'bus', title: '草64 二天門→B最寄り', edges: 31),
        ],
      );
      final list = [c1, c2, c3];
      if (pref == Preference.fewTransfers) {
        list.sort((a, b) {
          final t = a.transfers.compareTo(b.transfers);
          if (t != 0) return t;
          final b0 = a.boards.compareTo(b.boards);
          if (b0 != 0) return b0;
          return a.total.compareTo(b.total);
        });
      } else {
        list.sort((a, b) => a.total.compareTo(b.total));
      }
      return list;
    }

    static Candidate _build({
      required String id,
      required List<String> lines,
      required int rides,
      required int walks,
      required int boards,
      required int transfers,
      required List<StepSeg> steps,
    }) {
      final total = rides * ride + walks * walk + boards * board;
      return Candidate(
        id: id,
        lines: lines,
        rides: rides,
        walks: walks,
        boards: boards,
        transfers: transfers,
        total: total,
        steps: steps,
        points: const [], // Mock data has no points
      );
    }
  }

  class RouteCard extends StatelessWidget {
    final Candidate candidate;
    final int rank;
    const RouteCard({super.key, required this.candidate, required this.rank});

    @override
    Widget build(BuildContext context) {
      return Container(
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6,
          borderRadius: BorderRadius.circular(16),
        ),
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: CupertinoColors.activeBlue,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    'C$rank',
                    style: const TextStyle(color: CupertinoColors.white),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    candidate.lines.join(' → '),
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w600,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: -6,
              children: [
                _chip('総スコア ${candidate.total}'),
                _chip('乗換 ${candidate.transfers}'),
                _chip('乗車区間 ${candidate.rides}'),
                _chip('徒歩 ${candidate.walks}'),
              ],
            ),
            const SizedBox(height: 8),
            // ダイジェスト（最初の2区間だけ）
            Text(
              candidate.steps
                  .map((seg) {
                    if (seg.kind == 'walk') {
                      final m = seg.meters ?? 0;
                      final dist = m >= 1000
                          ? '${(m / 1000).toStringAsFixed(1)}km'
                          : '${m}m';
                      final mm = seg.minutes != null ? '（約${seg.minutes}分）' : '';
                      return '徒歩 $dist$mm';
                    } else {
                      final stops = seg.edges > 0 ? ' ${seg.edges}停' : '';
                      final mm = seg.minutes != null ? '（約${seg.minutes}分）' : '';
                      return '${seg.title}$stops$mm';
                    }
                  })
                  .take(2)
                  .join(' / '),
              style: const TextStyle(color: CupertinoColors.inactiveGray),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      );
    }

    Widget _chip(String text) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: CupertinoColors.white,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(text, style: const TextStyle(fontSize: 12)),
      );
    }
  }

  class RouteDetailPage extends StatelessWidget {
    final Candidate candidate;
    const RouteDetailPage({super.key, required this.candidate});

    @override
    Widget build(BuildContext context) {
      return CupertinoPageScaffold(
        navigationBar: CupertinoNavigationBar(
          middle: Text(candidate.lines.join(' → ')),
          trailing: CupertinoButton(
            padding: EdgeInsets.zero,
            child: const Icon(CupertinoIcons.bookmark),
            onPressed: () {
              if (kSavedRoutes.any((e) => e.id == candidate.id)) {
                // 既に保存済みなら何もしないか、削除する？今回は追加のみ
                showCupertinoDialog(
                  context: context,
                  builder: (ctx) => CupertinoAlertDialog(
                    title: const Text('保存済み'),
                    content: const Text('この経路は既にMy Routeに保存されています。'),
                    actions: [
                      CupertinoDialogAction(
                        child: const Text('OK'),
                        onPressed: () => Navigator.pop(ctx),
                      ),
                    ],
                  ),
                );
              } else {
                kSavedRoutes.add(candidate);
                showCupertinoDialog(
                  context: context,
                  builder: (ctx) => CupertinoAlertDialog(
                    title: const Text('保存しました'),
                    content: const Text('My Routeに追加しました。'),
                    actions: [
                      CupertinoDialogAction(
                        child: const Text('OK'),
                        onPressed: () => Navigator.pop(ctx),
                      ),
                    ],
                  ),
                );
              }
            },
          ),
        ),
        child: SafeArea(
          child: Column(
            children: [
              const SizedBox(height: 8),
              // サマリー
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16.0),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    _stat('総スコア', candidate.total.toString()),
                    _stat('乗換', candidate.transfers.toString()),
                    _stat('乗車区間', candidate.rides.toString()),
                    _stat('徒歩', '${candidate.walks}m'),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              // 地図プレースホルダ
              Container(
                height: 200,
                margin: const EdgeInsets.symmetric(horizontal: 16),
                decoration: BoxDecoration(
                  color: CupertinoColors.systemGrey6,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: GoogleMap(
                    initialCameraPosition: CameraPosition(
                      target: candidate.points.isNotEmpty
                          ? candidate.points.first
                          : const LatLng(35.681236, 139.767125), // Default: Tokyo Station
                      zoom: 13,
                    ),
                    polylines: {
                      Polyline(
                        polylineId: const PolylineId('route'),
                        points: candidate.points,
                        color: CupertinoColors.activeBlue,
                        width: 5,
                      ),
                    },
                    markers: {
                      if (candidate.points.isNotEmpty) ...[
                        Marker(
                          markerId: const MarkerId('start'),
                          position: candidate.points.first,
                          infoWindow: const InfoWindow(title: 'Start'),
                        ),
                        Marker(
                          markerId: const MarkerId('end'),
                          position: candidate.points.last,
                          infoWindow: const InfoWindow(title: 'End'),
                        ),
                      ],
                    },
                  ),
                ),
              ),
              const SizedBox(height: 12),
              // 区間一覧
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                  itemCount: candidate.steps.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (context, i) {
                    final seg = candidate.steps[i];
                    return _stepTile(context, seg);  // ← context 渡す
                  },
                ),
              ),
            ],
          ),
        ),
      );
    }

    // ---- ここから下はこのクラス内のヘルパ ----

    Widget _stat(String k, String v) {
      return Column(
        children: [
          Text(
            v,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 2),
          Text(
            k,
            style: const TextStyle(
              color: CupertinoColors.inactiveGray,
              fontSize: 12,
            ),
          ),
        ],
      );
    }
    // RouteDetailPage 内
    Widget _stepTile(BuildContext context, StepSeg s) {
      final isWalk = s.kind == 'walk';
      final right = s.minutes != null
          ? '約${s.minutes}分'
          : (!isWalk && s.edges > 0
              ? '${s.edges}停'
              : (isWalk && s.meters != null ? '${s.meters}m' : ''));

      final canShowStops = !isWalk && s.stops.isNotEmpty;

      final content = Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: CupertinoColors.white,
          borderRadius: BorderRadius.circular(12),
          boxShadow: [
            BoxShadow(
              color: CupertinoColors.systemGrey.withOpacity(0.1),
              blurRadius: 4,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ヘッダ行 (アイコン + タイトル + 時間)
            Row(
              children: [
                _roundIcon(s.kind),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        s.mainTitle,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      if (s.departureTime != null && s.arrivalTime != null)
                        Text(
                          '${s.departureTime} → ${s.arrivalTime}',
                          style: const TextStyle(
                            fontSize: 13,
                            color: CupertinoColors.activeBlue,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      if (s.subTitle != null) ...[
                        const SizedBox(height: 4),
                        Text(
                          s.subTitle!,
                          style: const TextStyle(
                            color: CupertinoColors.inactiveGray,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                Text(
                  right,
                  style: const TextStyle(
                    fontSize: 13,
                    color: CupertinoColors.systemGrey,
                  ),
                ),
              ],
            ),
          ],
        ),
      );

      if (!canShowStops) return content;

      return GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          Navigator.of(context).push(
            CupertinoPageRoute(
              builder: (_) => SegmentStopsPage(segment: s),
            ),
          );
        },
        child: content,
      );
    }



    Widget _miniChip(String text) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: CupertinoColors.white, borderRadius: BorderRadius.circular(8)),
      child: Text(text, style: const TextStyle(fontSize: 12)),
    );

    String _fmtMeters(int m) => m >= 1000 ? '${(m/1000).toStringAsFixed(1)}km' : '${m}m';


    // title から「上23 〜」の先頭トークンを線名として拾う（無ければ title そのまま）
    String _lineNameFromTitle(String title) {
      final t = title.trim();
      if (t.isEmpty) return 'バス';
      final sp = t.split(RegExp(r'\s+'));
      return sp.isNotEmpty ? sp.first : t;
    }

    // 左の丸アイコン
    Widget _roundIcon(String kind) {
      IconData icon;
      Color color;
      switch (kind) {
        case 'walk':
          icon = CupertinoIcons.paw_solid;
          color = CupertinoColors.activeOrange;
          break;
        case 'rail':
          icon = CupertinoIcons.tram_fill;
          color = CupertinoColors.systemPurple;
          break;
        default:
          icon = CupertinoIcons.bus;
          color = CupertinoColors.activeBlue;
      }
      return Container(
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          color: color.withOpacity(0.15),
          shape: BoxShape.circle,
        ),
        alignment: Alignment.center,
        child: Icon(icon, color: color),
      );
    }

    // 右肩の小チップ
    Widget _chip(String text) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: CupertinoColors.white,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(text, style: const TextStyle(fontSize: 12)),
      );
    }
  }

  class MapPickerPage extends StatefulWidget {
    final String? title;
    const MapPickerPage({super.key, this.title});
    @override
    State<MapPickerPage> createState() => _MapPickerPageState();
  }

  class _MapPickerPageState extends State<MapPickerPage> {
    LatLng _center = const LatLng(35.681236, 139.767125); // 東京駅あたり
    LatLng? _picked;
    @override
    Widget build(BuildContext context) {
      return CupertinoPageScaffold(
        navigationBar: CupertinoNavigationBar(
          middle: Text(widget.title ?? '地図から選ぶ'),
        ),
        child: SafeArea(
          child: Stack(
            children: [
              GoogleMap(
                initialCameraPosition: CameraPosition(target: _center, zoom: 13),
                myLocationEnabled: true,
                onLongPress: (latLng) => setState(() => _picked = latLng),
                markers: {
                  if (_picked != null)
                    Marker(
                      markerId: const MarkerId('picked'),
                      position: _picked!,
                    ),
                },
              ),
              Positioned(
                left: 16,
                right: 16,
                bottom: 24,
                child: CupertinoButton.filled(
                  onPressed: _picked == null
                      ? null
                      : () => Navigator.pop(context, _picked),
                  child: Text(_picked == null ? '長押しで地点を選択' : 'この地点を決定'),
                ),
              ),
            ],
          ),
        ),
      );
    }
  }

  class LivePage extends StatelessWidget {
    const LivePage({super.key});
    @override
    Widget build(BuildContext context) {
      return const CupertinoPageScaffold(
        navigationBar: CupertinoNavigationBar(middle: Text('ライブ')),
        child: SafeArea(child: _LiveContent()),
      );
    }
  }

  class _LiveContent extends StatefulWidget {
    const _LiveContent();
    @override
    State<_LiveContent> createState() => _LiveContentState();
  }

  class _LiveContentState extends State<_LiveContent> {
    int tab = 0; // 0: バス停, 1: 駅
    @override
    Widget build(BuildContext context) {
      return Column(
        children: [
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16.0),
            child: CupertinoSlidingSegmentedControl<int>(
              groupValue: tab,
              children: const {0: Text('バス停'), 1: Text('駅')},
              onValueChanged: (v) => setState(() => tab = v ?? 0),
            ),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              itemBuilder: (_, i) => _liveRow(i),
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemCount: 12,
            ),
          ),
        ],
      );
    }

    Widget _liveRow(int i) {
      return Container(
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6,
          borderRadius: BorderRadius.circular(12),
        ),
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: CupertinoColors.activeBlue,
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text(
                '上23',
                style: TextStyle(color: CupertinoColors.white),
              ),
            ),
            const SizedBox(width: 8),
            const Expanded(child: Text('平井七丁目北公園前 → 上野松坂屋前')),
            const Text(
              'あと 5 分',
              style: TextStyle(color: CupertinoColors.activeGreen),
            ),
          ],
        ),
      );
    }
  }

  class PlaceField extends StatefulWidget {
    final String label;
    final void Function(double lat, double lon, String desc) onPicked;
    final String? initialText;

    const PlaceField({
      super.key,
      required this.label,
      required this.onPicked,
      this.initialText,
    });

    @override
    State<PlaceField> createState() => _PlaceFieldState();
  }

  class _PlaceFieldState extends State<PlaceField> {
    final _ctrl = TextEditingController();
    List<Map<String, dynamic>> _preds = [];
    bool _loading = false;
    bool _suppressChange = false; // ← これ追加

    @override
    void initState() {
      super.initState();
      if (widget.initialText != null) {
        _ctrl.text = widget.initialText!;
      }
      _ctrl.addListener(_onChanged);
    }

    @override
    void dispose() {
      _ctrl.removeListener(_onChanged);
      _ctrl.dispose();
      super.dispose();
    }

    Future<void> _onChanged() async {
      if (_suppressChange) return; 

      final q = _ctrl.text.trim();
      if (q.isEmpty) {
        setState(() => _preds = []);
        return;
      }

      setState(() => _loading = true);
      try {
        final j = await ApiClient.get('/autocomplete', params: {'q': q});
        final raw = j['predictions'] as List? ?? const [];
        setState(() {
          _loading = false;
          _preds = raw.cast<Map<String, dynamic>>();
        });
      } catch (_) {
        setState(() {
          _loading = false;
          _preds = [];
        });
      }
    }

    Future<void> _pick(Map<String, dynamic> p) async {
      final placeId = p['place_id'] as String?;
      if (placeId == null) return;

      final j = await ApiClient.get('/details', params: {'place_id': placeId});
      final res = j['result'] as Map<String, dynamic>?;
      final loc = (res?['geometry']?['location'] as Map?) ?? {};
      final lat = (loc['lat'] as num?)?.toDouble() ?? 0;
      final lon = (loc['lng'] as num?)?.toDouble() ?? 0;
      final desc =
          p['description']?.toString() ??
          res?['name']?.toString() ??
          widget.label;

      // ここで onChanged が走らないようにする
      _suppressChange = true;
      _ctrl.text = desc;
      _suppressChange = false;

      setState(() => _preds = []); // 候補を閉じる
      widget.onPicked(lat, lon, desc); // HomePage 側で _to.text をセット
    }

    @override
    Widget build(BuildContext context) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 6),
            child: Text(
              widget.label,
              style: const TextStyle(
                color: CupertinoColors.inactiveGray,
                fontSize: 12,
              ),
            ),
          ),
          CupertinoTextField(
            controller: _ctrl,
            placeholder: '場所名・住所で検索',
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          ),
          if (_loading)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: CupertinoActivityIndicator(),
            ),
          if (_preds.isNotEmpty)
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 220), // ← 高さ制限
              child: Container(
                margin: const EdgeInsets.only(top: 6),
                decoration: BoxDecoration(
                  color: CupertinoColors.systemGrey6,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: ListView.builder(
                  padding: EdgeInsets.zero,
                  itemCount: _preds.length > 6 ? 6 : _preds.length,
                  itemBuilder: (context, index) {
                    final p = _preds[index];
                    final txt = p['description']?.toString() ?? '地点';
                    return CupertinoButton(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
                      ),
                      alignment: Alignment.centerLeft,
                      onPressed: () => _pick(p),
                      child: Text(
                        txt,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    );
                  },
                ),
              ),
            ),
        ],
      );
    }
  }

  class StopPoint {
    final String name;
    final bool isOrigin;      // 始発 or 乗車
    final bool isDestination; // 終点 or 降車

    StopPoint({
      required this.name,
      this.isOrigin = false,
      this.isDestination = false,
    });

    factory StopPoint.fromJson(Map<String, dynamic> j) {
      return StopPoint(
        name: j['name']?.toString() ?? '',
        isOrigin: j['is_origin'] == true,
        isDestination: j['is_destination'] == true,
      );
    }
  }

  class SegmentStopsPage extends StatelessWidget {
    final StepSeg segment;
    const SegmentStopsPage({super.key, required this.segment});

    @override
    Widget build(BuildContext context) {
      return CupertinoPageScaffold(
        navigationBar: CupertinoNavigationBar(
          middle: Text(segment.title.isEmpty ? segment.mainTitle : segment.title),
        ),
        child: SafeArea(
          child: ListView.builder(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            itemCount: segment.stops.length,
            itemBuilder: (context, index) {
              final stop = segment.stops[index];
              final isFirst = index == 0;
              final isLast = index == segment.stops.length - 1;
              return _StopRow(
                stop: stop,
                isFirst: isFirst,
                isLast: isLast,
              );
            },
          ),
        ),
      );
    }
  }

  class _StopRow extends StatelessWidget {
    final StopPoint stop;
    final bool isFirst;
    final bool isLast;

    const _StopRow({
      required this.stop,
      required this.isFirst,
      required this.isLast,
    });

    @override
    Widget build(BuildContext context) {
      final nameStyle = TextStyle(
        fontSize: 16,
        fontWeight:
            (stop.isOrigin || stop.isDestination) ? FontWeight.w600 : FontWeight.w400,
      );

      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 左側の縦線＋丸
          SizedBox(
            width: 40,
            child: Column(
              children: [
                if (!isFirst)
                  Container(
                    width: 2,
                    height: 12,
                    color: CupertinoColors.systemGrey4,
                  ),
                Container(
                  width: 18,
                  height: 18,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: CupertinoColors.activeGreen,
                      width: 2,
                    ),
                    color: stop.isOrigin || stop.isDestination
                        ? CupertinoColors.activeGreen
                        : CupertinoColors.white,
                  ),
                ),
                if (!isLast)
                  Container(
                    width: 2,
                    height: 24,
                    color: CupertinoColors.systemGrey4,
                  ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          // 右側テキスト
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(stop.name, style: nameStyle),
                  if (stop.isOrigin || stop.isDestination) ...[
                    const SizedBox(height: 2),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: CupertinoColors.systemGrey5,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        stop.isOrigin
                            ? '乗車'
                            : (stop.isDestination ? '降車' : ''),
                        style: const TextStyle(
                          fontSize: 10,
                          color: CupertinoColors.inactiveGray,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      );
    }
  }

  class MyRoutePage extends StatefulWidget {
    const MyRoutePage({super.key});

    @override
    State<MyRoutePage> createState() => _MyRoutePageState();
  }

  class _MyRoutePageState extends State<MyRoutePage> {
    @override
    Widget build(BuildContext context) {
      return CupertinoPageScaffold(
        navigationBar: const CupertinoNavigationBar(
          middle: Text('My Route'),
        ),
        child: SafeArea(
          child: kSavedRoutes.isEmpty
              ? const Center(child: Text('保存された経路はありません'))
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                  itemCount: kSavedRoutes.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (context, i) {
                    final c = kSavedRoutes[i];
                    return GestureDetector(
                      onTap: () {
                        Navigator.of(context).push(
                          CupertinoPageRoute(
                            builder: (_) => RouteDetailPage(candidate: c),
                          ),
                        );
                      },
                      child: RouteCard(candidate: c, rank: i + 1),
                    );
                  },
                ),
        ),
      );
    }
  }

class BusLoadingIndicator extends StatefulWidget {
  const BusLoadingIndicator({super.key});

  @override
  State<BusLoadingIndicator> createState() => _BusLoadingIndicatorState();
}

class _BusLoadingIndicatorState extends State<BusLoadingIndicator>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late final Animation<Offset> _offsetAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    )..repeat();

    _offsetAnimation = Tween<Offset>(
      begin: const Offset(-0.5, 0.0),
      end: const Offset(1.5, 0.0),
    ).animate(CurvedAnimation(
      parent: _controller,
      curve: Curves.linear,
    ));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        SlideTransition(
          position: _offsetAnimation,
          child: AnimatedBuilder(
            animation: _controller,
            builder: (context, child) {
               final int frame = (_controller.value * 40).floor() % 4; 
               String image;
               switch (frame) {
                 case 0: image = 'assets/images/bus_loading_01.png'; break;
                 case 1: image = 'assets/images/bus_loading_02.png'; break;
                 case 2: image = 'assets/images/bus_loading_03.png'; break;
                 case 3: image = 'assets/images/bus_loading_04.png'; break;
                 default: image = 'assets/images/bus_loading_01.png';
               }
               return SizedBox(
                 width: 80,
                 child: Image.asset(
                   image,
                   gaplessPlayback: true,
                 ),
               );
            },
          ),
        ),
        const Text('検索中...', style: TextStyle(color: CupertinoColors.inactiveGray)),
      ],
    );
  }
}

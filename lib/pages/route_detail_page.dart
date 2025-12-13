import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/route_models.dart';
import '../data/global_state.dart';
import '../services/storage_service.dart';
import '../widgets/timetable_view.dart';
import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../services/trip_draft_service.dart';
import 'leader_mode_page.dart';
import '../core/api_client.dart';
import '../widgets/bus_loading_indicator.dart';

// --- メインの画面 ---
class RouteDetailPage extends StatefulWidget {
  final Candidate candidate;
  final bool isReturnSelection;

  const RouteDetailPage({super.key, required this.candidate, this.isReturnSelection = false});

  @override
  State<RouteDetailPage> createState() => _RouteDetailPageState();
}

class _RouteDetailPageState extends State<RouteDetailPage> {
  // 再検索用の日時
  DateTime _searchTime = DateTime.now();
  final TripDraftService _draftService = TripDraftService();

  bool get _isReturnSelection => widget.isReturnSelection;

  // 保存状態の判定ロジック
  bool get _isSaved {
    return kSavedRoutes.any((e) => _isSameRoute(e, widget.candidate));
  }

  // 経路が同じか判定するヘルパー
  bool _isSameRoute(Candidate a, Candidate b) {
    if (a.id != b.id) return false;
    if (a.points.isEmpty || b.points.isEmpty) return false;
    final sameStart = a.points.first.latitude == b.points.first.latitude &&
                      a.points.first.longitude == b.points.first.longitude;
    final sameEnd = a.points.last.latitude == b.points.last.latitude &&
                    a.points.last.longitude == b.points.last.longitude;
    return sameStart && sameEnd;
  }

  void _toggleBookmark() {
    setState(() {
      if (_isSaved) {
        _showDeleteDialog();
      } else {
        kSavedRoutes.add(widget.candidate);
        StorageService().saveRoutes(kSavedRoutes);
        _showSavedDialog();
      }
    });
  }

  void _showDeleteDialog() {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('ブックマークを削除'),
        content: const Text('この経路をMy Routeから削除しますか?'),
        actions: [
          CupertinoDialogAction(child: const Text('キャンセル'), onPressed: () => Navigator.pop(ctx)),
          CupertinoDialogAction(
            isDestructiveAction: true,
            child: const Text('削除'),
            onPressed: () {
              Navigator.pop(ctx);
              setState(() {
                kSavedRoutes.removeWhere((e) => _isSameRoute(e, widget.candidate));
                StorageService().saveRoutes(kSavedRoutes);
              });
            },
          ),
        ],
      ),
    );
  }

  void _showSavedDialog() {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('保存しました'),
        content: const Text('My Routeに追加しました。'),
        actions: [
          CupertinoDialogAction(child: const Text('OK'), onPressed: () => Navigator.pop(ctx)),
        ],
      ),
    );
  }

  void _setDirection(LegDirection direction) {
    try {
      setState(() {
        _draftService.setRoute(direction, widget.candidate);
      });
    } on StateError catch (e) {
      _showDuplicateRouteAlert(e.message ?? '行きと同じ経路は帰りに設定できません');
    }
  }

  String _routeLabel(Candidate? candidate) {
    if (candidate == null) return '未選択';
    return candidate.lines.join(' → ');
  }

  void _showDuplicateRouteAlert(String message) {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('別の経路を選択してください'),
        content: Text(message),
        actions: [
          CupertinoDialogAction(
            child: const Text('OK'),
            onPressed: () => Navigator.pop(ctx),
          ),
        ],
      ),
    );
  }

  Widget _roundTripComposer() {
    final outbound = _draftService.outbound;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGroupedBackground,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  _isReturnSelection ? '帰りの経路を決める' : '往復の経路を決める',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (_isReturnSelection && outbound != null) ...[
              _selectedOutboundSummary(outbound),
              const SizedBox(height: 12),
            ],
            if (_isReturnSelection) ...[
              CupertinoButton.filled(
                onPressed: () => _setDirection(LegDirection.inbound),
                child: const Text('この経路を帰りに設定'),
              ),
              const SizedBox(height: 12),
              CupertinoButton.filled(
                onPressed: _draftService.isComplete ? _showCreateTripDialog : null,
                child: const Text('グループ作成'),
              ),
              const SizedBox(height: 6),
              Text(
                _draftService.isComplete
                    ? '往復が揃いました。グループを作成できます。'
                    : '帰りの経路を選ぶと作成できます',
                style: const TextStyle(color: CupertinoColors.systemGrey),
              ),
            ] else ...[
              CupertinoButton(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                onPressed: _startReturnSearch,
                child: const Text('帰りを探す（出発地/到着地を入れ替え）'),
              ),
              const SizedBox(height: 6),
              const Text(
                '帰りの経路を選ぶと作成できます',
                style: TextStyle(color: CupertinoColors.systemGrey),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _selectedOutboundSummary(Candidate candidate) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.systemGrey6,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '行きに設定中',
            style: TextStyle(fontSize: 12, color: CupertinoColors.systemGrey),
          ),
          const SizedBox(height: 4),
          Text(
            candidate.lines.join(' → '),
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          Text(
            '所要時間 ${candidate.totalTime}分・乗換 ${candidate.transfers}回',
            style: const TextStyle(fontSize: 12, color: CupertinoColors.systemGrey),
          ),
        ],
      ),
    );
  }

  // --- 再検索機能 (既存維持) ---
  void _showReSearchPicker() {
    _searchTime = DateTime.now();
    showCupertinoModalPopup(
      context: context,
      builder: (ctx) => Container(
        height: 280,
        color: CupertinoColors.systemBackground,
        child: Column(
          children: [
            Container(
              alignment: Alignment.centerRight,
              child: CupertinoButton(
                child: const Text('検索実行'),
                onPressed: () {
                  Navigator.pop(ctx);
                  _executeReSearch(startReturnFlow: _isReturnSelection);
                },
              ),
            ),
            SizedBox(
              height: 200,
              child: CupertinoDatePicker(
                mode: CupertinoDatePickerMode.dateAndTime,
                initialDateTime: _searchTime,
                use24hFormat: true,
                onDateTimeChanged: (val) {
                  _searchTime = val;
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _startReturnSearch() async {
    if (widget.candidate.points.length < 2) return;
    setState(() {
      _draftService.reset();
      _draftService.setRoute(LegDirection.outbound, widget.candidate);
    });
    await _executeReSearch(reverse: true, startReturnFlow: true);
  }

  Future<void> _executeReSearch({bool reverse = false, bool startReturnFlow = false}) async {
    final original = widget.candidate;
    if (original.points.isEmpty) return;

    showCupertinoDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => Center(
        child: Container(
          width: 160,
          height: 160,
          decoration: BoxDecoration(
            color: CupertinoColors.systemBackground,
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              BusLoadingIndicator(),
              SizedBox(height: 16),
              Text('再検索中...', style: TextStyle(fontSize: 14)),
            ],
          ),
        ),
      ),
    );

    try {
      final start = reverse ? original.points.last : original.points.first;
      final end = reverse ? original.points.first : original.points.last;

      final params = {
        'alat': '${start.latitude}',
        'alon': '${start.longitude}',
        'blat': '${end.latitude}',
        'blon': '${end.longitude}',
        'pref': original.preference ?? 'fewTransfers',
        'time': '${_searchTime.hour.toString().padLeft(2, '0')}:${_searchTime.minute.toString().padLeft(2, '0')}',
        'date': '${_searchTime.year}-${_searchTime.month.toString().padLeft(2, '0')}-${_searchTime.day.toString().padLeft(2, '0')}',
      };

      final j = await ApiClient.post('/route', body: params);
      final jobId = j['job_id']?.toString();
      
      if (jobId == null) throw Exception('Job ID missing');

      await _poll(jobId, startReturnFlow: startReturnFlow);

    } catch (e) {
      if (!mounted) return;
      Navigator.of(context, rootNavigator: true).pop(); // ローディング閉じる
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('再検索に失敗しました: $e'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            )
          ],
        ),
      );
    }
  }

  Future<void> _poll(String jobId, {bool startReturnFlow = false}) async {
    while (true) {
      await Future.delayed(const Duration(seconds: 1));
      try {
        final j = await ApiClient.get('/route', params: {'job_id': jobId});
        final status = j['status']?.toString();
        
        if (status == 'done') {
          final result = j['result'];
          final list = (result['candidates'] as List?)
              ?.map((e) => Candidate.fromJson(e as Map<String, dynamic>))
              .toList();
          
          if (!mounted) return;
          Navigator.of(context, rootNavigator: true).pop(); // ローディング閉じる

          if (list != null && list.isNotEmpty) {
            // 新しい結果画面へ遷移（push）することで「戻る」が可能
            Navigator.of(context).push(
              CupertinoPageRoute(
                builder: (_) => RouteDetailPage(
                  candidate: list.first,
                  isReturnSelection: startReturnFlow,
                ),
              ),
            );
          } else {
             showCupertinoDialog(
              context: context,
              builder: (ctx) => CupertinoAlertDialog(
                content: const Text('指定された日時の経路が見つかりませんでした。'),
                actions: [
                  CupertinoDialogAction(
                    child: const Text('OK'),
                    onPressed: () => Navigator.pop(ctx),
                  )
                ],
              ),
            );
          }
          return;
        } else if (status == 'error') {
          throw Exception(j['error']);
        }
      } catch (e) {
        rethrow;
      }
    }
  }

  // --- グループ作成機能 (行き・帰りが揃った時だけ表示) ---
  void _showCreateTripDialog() {
    if (!_draftService.isComplete) {
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('帰りの経路を選択してください'),
          content: const Text('行きと帰りが揃ってからグループ作成ができます。'),
          actions: [
            CupertinoDialogAction(
              child: const Text('OK'),
              onPressed: () => Navigator.pop(ctx),
            ),
          ],
        ),
      );
      return;
    }

    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('この往復でグループを作成'),
        content: Text('行き: ${_routeLabel(_draftService.outbound)}\n帰り: ${_routeLabel(_draftService.inbound)}'),
        actions: [
          CupertinoDialogAction(
            child: const Text('キャンセル'),
            onPressed: () => Navigator.pop(ctx),
          ),
          CupertinoDialogAction(
            child: const Text('作成する'),
            onPressed: () {
              Navigator.pop(ctx);
              _createTrip();
            },
          ),
        ],
      ),
    );
  }

  Future<void> _createTrip() async {
    print('[DEBUG] _createTrip called. Widget mounted: $mounted');
    try {
      final tripId = await _draftService.createTrip();
      print('[DEBUG] Trip created. ID: $tripId');

      if (!mounted) {
        print('[DEBUG] Widget not mounted after createTrip. Aborting navigation.');
        return;
      }

      // 3. リーダー画面へ遷移
      print('[DEBUG] Navigating to LeaderModePage...');
      Navigator.push(
        context,
        CupertinoPageRoute(builder: (_) {
          print('[DEBUG] Building LeaderModePage route...');
          return LeaderModePage(tripId: tripId);
        }),
      );
      print('[DEBUG] Navigation pushed.');
    } catch (e, stack) {
      print('[DEBUG] Error in _createTrip: $e\n$stack');
      if (!mounted) return;
      showCupertinoDialog(
        context: context,
        builder: (ctx) => CupertinoAlertDialog(
          title: const Text('エラー'),
          content: Text('作成に失敗しました: $e'),
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
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(widget.candidate.lines.join(' → ')),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 再検索ボタン
            CupertinoButton(
              padding: EdgeInsets.zero,
              onPressed: _showReSearchPicker,
              child: const Icon(CupertinoIcons.clock),
            ),
            // ブックマークボタン
            CupertinoButton(
              padding: EdgeInsets.zero,
              child: Icon(_isSaved ? CupertinoIcons.bookmark_fill : CupertinoIcons.bookmark),
              onPressed: _toggleBookmark,
            ),
          ],
        ),
      ),
      child: SafeArea(
        child: CustomScrollView(
          slivers: [
            const SliverToBoxAdapter(child: SizedBox(height: 8)),

            if (widget.candidate.isFutureSuggestion)
              SliverToBoxAdapter(
                child: _FutureSuggestionAlert(date: widget.candidate.departureDate),
              ),

            SliverToBoxAdapter(child: RouteSummary(candidate: widget.candidate)),

            SliverToBoxAdapter(child: _roundTripComposer()),

            const SliverToBoxAdapter(child: SizedBox(height: 12)),

            SliverToBoxAdapter(child: RouteMapPreview(points: widget.candidate.points)),

            const SliverToBoxAdapter(child: SizedBox(height: 12)),

            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              sliver: SliverList(
                delegate: SliverChildBuilderDelegate(
                  (context, index) {
                    final itemIndex = index ~/ 2;
                    if (index.isEven) {
                      return RouteStepTile(segment: widget.candidate.steps[itemIndex]);
                    }
                    return const SizedBox(height: 8);
                  },
                  childCount: widget.candidate.steps.isEmpty
                      ? 0
                      : (widget.candidate.steps.length * 2) - 1,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// --- 以下、切り出したWidget群 (別ファイルにしてもOK) ---

class _FutureSuggestionAlert extends StatelessWidget {
  final DateTime? date;
  const _FutureSuggestionAlert({required this.date});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.activeOrange.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: CupertinoColors.activeOrange),
      ),
      child: Row(
        children: [
          const Icon(CupertinoIcons.exclamationmark_triangle_fill, color: CupertinoColors.activeOrange),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              "ご指定の日時は運行終了または運休日のため、\n${date?.toString().split(' ')[0]} の経路を表示しています。",
              style: const TextStyle(
                  color: CupertinoColors.activeOrange, fontWeight: FontWeight.bold, fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }
}

class RouteSummary extends StatelessWidget {
  final Candidate candidate;
  const RouteSummary({super.key, required this.candidate});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16.0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _stat('所要時間', '${candidate.totalTime}分'),
          _stat('乗換', candidate.transfers.toString()),
          _stat('乗車区間', candidate.rides.toString()),
          _stat('徒歩', '${candidate.walks}m'),
        ],
      ),
    );
  }

  Widget _stat(String k, String v) {
    return Column(
      children: [
        Text(v, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        Text(k, style: const TextStyle(color: CupertinoColors.inactiveGray, fontSize: 12)),
      ],
    );
  }
}

class RouteMapPreview extends StatelessWidget {
  final List<LatLng> points;
  const RouteMapPreview({super.key, required this.points});

  @override
  Widget build(BuildContext context) {
    return Container(
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
            target: points.isNotEmpty ? points.first : const LatLng(35.681236, 139.767125),
            zoom: 13,
          ),
          polylines: {
            Polyline(
              polylineId: const PolylineId('route'),
              points: points,
              color: CupertinoColors.activeBlue,
              width: 5,
            ),
          },
          markers: {
            if (points.isNotEmpty) ...[
              Marker(markerId: const MarkerId('start'), position: points.first, infoWindow: const InfoWindow(title: 'Start')),
              Marker(markerId: const MarkerId('end'), position: points.last, infoWindow: const InfoWindow(title: 'End')),
            ],
          },
        ),
      ),
    );
  }
}

class RouteStepTile extends StatelessWidget {
  final StepSeg segment;
  const RouteStepTile({super.key, required this.segment});

  @override
  Widget build(BuildContext context) {
    final isWalk = segment.kind == 'walk';
    final rightText = _getRightText(isWalk);
    final canShowStops = !isWalk && segment.stops.isNotEmpty;

    final content = Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: CupertinoColors.systemGrey.withValues(alpha: 0.1),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _RoundIcon(kind: segment.kind),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(segment.mainTitle, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                    if (segment.departureTime != null && segment.arrivalTime != null)
                      Text('${segment.departureTime} → ${segment.arrivalTime}',
                          style: const TextStyle(fontSize: 13, color: CupertinoColors.activeBlue, fontWeight: FontWeight.w600)),
                    if (segment.subTitle != null) ...[
                      const SizedBox(height: 4),
                      Text(segment.subTitle!, style: const TextStyle(color: CupertinoColors.inactiveGray)),
                    ],
                  ],
                ),
              ),
              if (rightText.isNotEmpty)
                Text(rightText, style: const TextStyle(fontSize: 13, color: CupertinoColors.systemGrey)),
            ],
          ),
          if (segment.kind == 'bus' && segment.routeId.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8.0),
              child: Container(height: 1, color: CupertinoColors.systemGrey5),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4.0),
              child: TimetableView(routeId: segment.routeId, stopId: segment.departureStopId),
            ),
          ],
        ],
      ),
    );

    if (!canShowStops) return content;

    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => Navigator.of(context).push(CupertinoPageRoute(builder: (_) => SegmentStopsPage(segment: segment))),
      child: content,
    );
  }

  String _getRightText(bool isWalk) {
    if (segment.minutes != null) return '約${segment.minutes}分';
    if (!isWalk && segment.edges > 0) return '${segment.edges}停';
    if (isWalk && segment.meters != null) return '${segment.meters}m';
    return '';
  }
}

class _RoundIcon extends StatelessWidget {
  final String kind;
  const _RoundIcon({required this.kind});

  @override
  Widget build(BuildContext context) {
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
      width: 36, height: 36,
      decoration: BoxDecoration(color: color.withValues(alpha: 0.15), shape: BoxShape.circle),
      alignment: Alignment.center,
      child: Icon(icon, color: color),
    );
  }
}

// --- 以下のクラスは別ファイルへ移動推奨だが、今回はここに維持 ---

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

    return GestureDetector(
      onTap: () {
        if (stop.lat != null && stop.lon != null) {
          Navigator.of(context).push(
            CupertinoPageRoute(
              builder: (_) => BusStopMapPage(stop: stop),
            ),
          );
        } else {
          print('[DEBUG] lat or lon is null');
        }
      },
      behavior: HitTestBehavior.opaque,
      child: Row(
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
      ),
    );
  }
}

class BusStopMapPage extends StatelessWidget {
  final StopPoint stop;

  const BusStopMapPage({super.key, required this.stop});

  @override
  Widget build(BuildContext context) {
    print('[DEBUG] Viewing map for: ${stop.name}, lat=${stop.lat}, lon=${stop.lon}');
    final target = LatLng(stop.lat ?? 35.681236, stop.lon ?? 139.767125);

    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(stop.name),
      ),
      child: Stack(
        children: [
          GoogleMap(
            initialCameraPosition: CameraPosition(
              target: target,
              zoom: 16,
            ),
            markers: {
              Marker(
                markerId: MarkerId(stop.name),
                position: target,
                infoWindow: InfoWindow(title: stop.name),
              ),
            },
            myLocationEnabled: true,
            myLocationButtonEnabled: true,
            zoomGesturesEnabled: true,
            scrollGesturesEnabled: true,
            rotateGesturesEnabled: true,
            tiltGesturesEnabled: true,
          ),
          // 下部に住所や情報を出すパネルがあればここに配置
        ],
      ),
    );
  }
}

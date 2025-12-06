import 'package:flutter/cupertino.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/route_models.dart';
import '../data/global_state.dart';
import '../services/storage_service.dart';
import '../widgets/timetable_view.dart';

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
            // 出発地と行き先も含めて重複チェック
            final isDuplicate = kSavedRoutes.any((e) {
              if (e.id != candidate.id) return false;
              // IDが同じ場合、出発地と行き先も比較
              if (e.points.isEmpty || candidate.points.isEmpty) return false;
              final sameStart = e.points.first.latitude == candidate.points.first.latitude &&
                                e.points.first.longitude == candidate.points.first.longitude;
              final sameEnd = e.points.last.latitude == candidate.points.last.latitude &&
                              e.points.last.longitude == candidate.points.last.longitude;
              return sameStart && sameEnd;
            });

            if (isDuplicate) {
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
              StorageService().saveRoutes(kSavedRoutes); // 保存
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
            const SizedBox(height: 8),
            if (candidate.isFutureSuggestion)
              Container(
                margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: CupertinoColors.activeOrange.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: CupertinoColors.activeOrange),
                ),
                child: Row(
                  children: [
                    const Icon(CupertinoIcons.exclamationmark_triangle_fill,
                        color: CupertinoColors.activeOrange),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        "ご指定の日時は運行終了または運休日のため、\n${candidate.departureDate?.toString().split(' ')[0]} の経路を表示しています。",
                        style: const TextStyle(
                            color: CupertinoColors.activeOrange,
                            fontWeight: FontWeight.bold,
                            fontSize: 13),
                      ),
                    ),
                  ],
                ),
              ),
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
                  return _stepTile(context, seg);
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
            color: CupertinoColors.systemGrey.withValues(alpha: 0.1),
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
              if (right.isNotEmpty)
                Text(
                  right,
                  style: const TextStyle(
                    fontSize: 13,
                    color: CupertinoColors.systemGrey,
                  ),
                ),
            ],
          ),
          // Bus Timetable Embedding
          if (s.kind == 'bus' && s.routeId.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8.0),
              child: Container(height: 1, color: CupertinoColors.systemGrey5),
            ),
            Builder(
              builder: (context) {
                // デバッグログ: TimetableViewに渡す値を確認
                print('[RouteDetailPage] TimetableView呼び出し:');
                print('  - StepSeg.title: ${s.title}');
                print('  - StepSeg.from: ${s.from}');
                print('  - StepSeg.to: ${s.to}');
                print('  - StepSeg.routeId: ${s.routeId}');
                print('  - StepSeg.departureStopId: ${s.departureStopId}');
                
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4.0),
                  child: TimetableView(
                    routeId: s.routeId,
                    stopId: s.departureStopId,
                  ),
                );
              },
            ),
          ],
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
        color: color.withValues(alpha: 0.15),
        shape: BoxShape.circle,
      ),
      alignment: Alignment.center,
      child: Icon(icon, color: color),
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

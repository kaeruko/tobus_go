import 'package:flutter/cupertino.dart';
import '../models/route_models.dart';

class RouteCard extends StatelessWidget {
  final Candidate candidate;
  final int rank;
  const RouteCard({super.key, required this.candidate, required this.rank});

  String get _origin {
    // 最初のstepのfromを取得
    if (candidate.steps.isNotEmpty) {
      final firstStep = candidate.steps.first;
      return firstStep.from ?? '出発地';
    }
    return '出発地';
  }

  String get _destination {
    // 最後のstepのtoを取得
    if (candidate.steps.isNotEmpty) {
      final lastStep = candidate.steps.last;
      return lastStep.to ?? '目的地';
    }
    return '目的地';
  }

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
          // 出発地 → 行き先
          Row(
            children: [
              const Icon(
                CupertinoIcons.location_fill,
                size: 14,
                color: CupertinoColors.systemGreen,
              ),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  '$_origin → $_destination',
                  style: const TextStyle(
                    fontSize: 14,
                    color: CupertinoColors.systemGrey,
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

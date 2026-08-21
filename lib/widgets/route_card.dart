import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/fare_models.dart';
import '../models/route_models.dart';
import '../providers/route_search_provider.dart';

class RouteCard extends ConsumerWidget {
  final Candidate candidate;
  final int rank;
  final RouteMeta? meta;
  final FareQuote? fare;

  const RouteCard({
    super.key,
    required this.candidate,
    required this.rank,
    this.meta,
    this.fare,
  });

  String get _origin {
    if (candidate.originName != null && candidate.originName!.isNotEmpty) {
      return candidate.originName!;
    }
    if (candidate.steps.isNotEmpty) {
      final firstStep = candidate.steps.first;
      return firstStep.from ?? '出発地';
    }
    return '出発地';
  }

  String get _destination {
    if (meta?.destinationReachable == false) {
      final stopName = meta?.fallbackNodeName ?? '最寄り停留所';
      final walk = meta?.fallbackWalkMinutes;
      final suffix = walk != null ? '（目的地まで徒歩約${walk}分）' : '';
      return stopName + suffix;
    }
    if (candidate.destinationName != null && candidate.destinationName!.isNotEmpty) {
      return candidate.destinationName!;
    }
    if (candidate.steps.isNotEmpty) {
      final lastStep = candidate.steps.last;
      return lastStep.to ?? '目的地';
    }
    return '目的地';
  }

  String? _fareChip(FareQuote? quote) {
    if (quote == null) return null;
    if (!quote.isAvailable) return '運賃計算対象外';
    final payNow = quote.payNowYen;
    if (payNow == null) return '支払額不明';
    if (quote.settlementType == 'reimbursement') {
      return 'いったん $payNow円';
    }
    if (quote.settlementType == 'free_pass') {
      return '支払 0円（乗車証）';
    }
    return '支払 $payNow円';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final effectiveFare = fare ?? ref.watch(
      routeSearchProvider.select(
        (state) => state.fareByCandidateId[candidate.id],
      ),
    );
    final fareChip = _fareChip(effectiveFare);

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
            runSpacing: 4,
            children: [
              _chip('所要 ${candidate.totalTime}分'),
              _chip('乗換 ${candidate.transfers}'),
              _chip('乗車区間 ${candidate.rides}'),
              _chip('徒歩 ${candidate.walks}'),
              if (fareChip != null) _chip(fareChip),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            candidate.steps
                .map((seg) {
                  if (seg.kind == 'walk') {
                    final m = seg.meters;
                    final dist = m >= 1000
                        ? '${(m / 1000).toStringAsFixed(1)}km'
                        : '${m.toInt()}m';
                    final mm = seg.minutes > 0 ? '（約${seg.minutes}分）' : '';
                    return '徒歩 $dist$mm';
                  }
                  final stops = seg.edges > 0 ? ' ${seg.edges}停' : '';
                  final mm = seg.minutes > 0 ? '（約${seg.minutes}分）' : '';
                  return '${seg.title}$stops$mm';
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

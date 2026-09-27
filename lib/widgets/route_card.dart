import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
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

  String _origin(AppLocalizations l10n) {
    if (candidate.originName != null && candidate.originName!.isNotEmpty) {
      return candidate.originName!;
    }
    if (candidate.steps.isNotEmpty) {
      final firstStep = candidate.steps.first;
      return firstStep.from ?? l10n.originFallback;
    }
    return l10n.originFallback;
  }

  String _destination(AppLocalizations l10n) {
    if (meta?.destinationReachable == false) {
      final stopName = meta?.fallbackNodeName ?? l10n.nearestStop;
      final walk = meta?.fallbackWalkMinutes;
      final suffix = walk != null ? l10n.destinationWalkSuffix(walk) : '';
      return stopName + suffix;
    }
    if (candidate.destinationName != null &&
        candidate.destinationName!.isNotEmpty) {
      return candidate.destinationName!;
    }
    if (candidate.steps.isNotEmpty) {
      final lastStep = candidate.steps.last;
      return lastStep.to ?? l10n.destinationFallback;
    }
    return l10n.destinationFallback;
  }

  String? _fareChip(FareQuote? quote, AppLocalizations l10n) {
    if (quote == null) return null;
    if (!quote.isAvailable) return l10n.fareUnavailable;
    final payNow = quote.payNowYen;
    if (payNow == null) return l10n.fareUnknown;
    if (quote.settlementType == 'reimbursement') {
      return l10n.fareReimbursement(payNow);
    }
    if (quote.settlementType == 'free_pass') {
      return l10n.fareFreePass;
    }
    return l10n.farePay(payNow);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final effectiveFare =
        fare ??
        ref.watch(
          routeSearchProvider.select(
            (state) => state.fareByCandidateId[candidate.id],
          ),
        );
    final fareChip = _fareChip(effectiveFare, l10n);

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
                  '${_origin(l10n)} → ${_destination(l10n)}',
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
              _chip(l10n.totalTimeChip(candidate.totalTime)),
              _chip(l10n.transfersChip(candidate.transfers)),
              _chip(l10n.ridesChip(candidate.rides)),
              _chip(l10n.walkChip(candidate.walkingDistanceMeters)),
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
                    final mm = seg.minutes > 0
                        ? l10n.approxMinutes(seg.minutes)
                        : '';
                    return l10n.walkSegment(dist, mm);
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

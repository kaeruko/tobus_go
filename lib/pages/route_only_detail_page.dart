import 'package:flutter/cupertino.dart';

import '../models/fare_models.dart';
import '../models/route_models.dart';
import '../widgets/route_map_preview.dart';

class RouteOnlyDetailPage extends StatelessWidget {
  final Candidate candidate;
  final FareQuote? fare;

  const RouteOnlyDetailPage({
    super.key,
    required this.candidate,
    this.fare,
  });

  IconData _iconFor(StepSeg step) {
    switch (step.kind) {
      case 'bus':
        return CupertinoIcons.bus;
      case 'rail':
        return CupertinoIcons.arrow_right_circle;
      case 'wait':
        return CupertinoIcons.clock;
      case 'walk':
        return CupertinoIcons.person;
      default:
        throw StateError('Unsupported route step kind: ${step.kind}');
    }
  }

  Widget _fareSummary(BuildContext context) {
    final quote = fare;
    if (quote == null) return const SizedBox.shrink();

    final lines = <String>[];
    if (quote.normalFareYen != null) {
      lines.add('通常運賃 ${quote.normalFareYen}円');
    }
    if (quote.isAvailable && quote.payNowYen != null) {
      lines.add('今回の支払 ${quote.payNowYen}円');
    }
    if (quote.settlementType == 'reimbursement' &&
        quote.effectiveFareYen != null) {
      lines.add('支給後の実質 ${quote.effectiveFareYen}円');
    }
    if (!quote.isAvailable) {
      lines.add('この経路では通常運賃を厳密計算できません');
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6.resolveFrom(context),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              quote.settlementLabel,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 4),
            for (final line in lines) Text(line),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(middle: Text('経路詳細')),
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.only(top: 16, bottom: 32),
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '所要 ${candidate.totalTime}分',
                    style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  if (candidate.arrivalTime != null)
                    Text(
                      '${candidate.arrivalTime} 着',
                      style: const TextStyle(
                        fontSize: 18,
                        color: CupertinoColors.activeBlue,
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                '乗車 ${candidate.rides}回・乗換 ${candidate.transfers}回',
                style: const TextStyle(color: CupertinoColors.systemGrey),
              ),
            ),
            _fareSummary(context),
            const SizedBox(height: 12),
            if (candidate.points.isNotEmpty) ...[
              RouteMapPreview(points: candidate.points),
              const SizedBox(height: 16),
            ],
            for (final step in candidate.steps)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: CupertinoColors.secondarySystemGroupedBackground
                        .resolveFrom(context),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(_iconFor(step), size: 24),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              step.mainTitle,
                              style: const TextStyle(
                                fontSize: 17,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            if (step.subTitle != null) ...[
                              const SizedBox(height: 3),
                              Text(step.subTitle!),
                            ],
                            if (step.departureTime != null ||
                                step.arrivalTime != null) ...[
                              const SizedBox(height: 5),
                              Text(
                                '${step.departureTime ?? '--:--'} → '
                                '${step.arrivalTime ?? '--:--'}',
                                style: const TextStyle(
                                  color: CupertinoColors.systemGrey,
                                ),
                              ),
                            ],
                            if (step.stops.length > 2) ...[
                              const SizedBox(height: 5),
                              Text(
                                '${step.stops.length}停留所・${step.minutes}分',
                                style: const TextStyle(
                                  color: CupertinoColors.systemGrey,
                                  fontSize: 13,
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

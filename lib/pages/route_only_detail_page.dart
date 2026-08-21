import 'package:flutter/cupertino.dart';

import '../models/route_models.dart';
import '../widgets/route_map_preview.dart';

class RouteOnlyDetailPage extends StatelessWidget {
  final Candidate candidate;

  const RouteOnlyDetailPage({super.key, required this.candidate});

  IconData _iconFor(StepSeg step) {
    switch (step.kind) {
      case 'bus':
        return CupertinoIcons.bus;
      case 'rail':
        return CupertinoIcons.tram_fill;
      case 'wait':
        return CupertinoIcons.clock;
      case 'walk':
        return CupertinoIcons.person_walk;
      default:
        throw StateError('Unsupported route step kind: ${step.kind}');
    }
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
            const SizedBox(height: 16),
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

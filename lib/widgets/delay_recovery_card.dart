import 'package:flutter/material.dart';

import '../logic/delay_impact_analyzer.dart';
import '../logic/next_ride_realtime.dart';

class DelayRecoveryCard extends StatelessWidget {
  final DelayImpact impact;
  final Widget? action;
  final NextRideRealtimeDeparture? nextRideRealtime;

  const DelayRecoveryCard({
    super.key,
    required this.impact,
    this.action,
    this.nextRideRealtime,
  });

  @override
  Widget build(BuildContext context) {
    if (!impact.requiresReplan) return const SizedBox.shrink();

    return Card(
      margin: EdgeInsets.zero,
      elevation: 2,
      color: Colors.orange.shade50,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Colors.orange.shade300),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.warning_amber_rounded, color: Colors.orange.shade800),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '次の乗換えに間に合わない可能性があります',
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              '${_clock(impact.predictedArrivalAt)} '
              '${impact.currentAlightingPlaceName}',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            if (impact.transferWalkMinutes > 0) ...[
              const SizedBox(height: 4),
              Text('徒歩${impact.transferWalkMinutes}分'),
            ],
            if (impact.transferBoardingMinutes > 0) ...[
              const SizedBox(height: 4),
              Text('乗車準備${impact.transferBoardingMinutes}分'),
            ],
            const SizedBox(height: 4),
            Text(
              _nextRideText(),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            if (action != null) ...[
              const SizedBox(height: 12),
              action!,
            ],
          ],
        ),
      ),
    );
  }

  String _nextRideText() {
    final realtime = nextRideRealtime;
    if (realtime == null) {
      return '${_clock(impact.nextDepartureAt)} ${impact.nextRideTitle}';
    }

    switch (realtime.status) {
      case NextRideRealtimeDepartureStatus.predicted:
        return '${_clock(impact.nextDepartureAt)} '
            '次便は${realtime.boardingPlaceName}発見込み';
      case NextRideRealtimeDepartureStatus.atBoardingPlace:
        return '${_clock(realtime.observedAt)} '
            '次便は${realtime.boardingPlaceName}に到着';
      case NextRideRealtimeDepartureStatus.passedBoardingPlace:
        return '${_clock(realtime.observedAt)} '
            '次便は${realtime.boardingPlaceName}を通過';
    }
  }

  static String _clock(DateTime value) {
    final local = value.toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }
}

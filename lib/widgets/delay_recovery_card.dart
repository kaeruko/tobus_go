import 'package:flutter/material.dart';

import '../logic/delay_impact_analyzer.dart';

class DelayRecoveryCard extends StatelessWidget {
  final DelayImpact impact;
  final Widget? action;
  final String? helperText;

  const DelayRecoveryCard({
    super.key,
    required this.impact,
    this.action,
    this.helperText,
  });

  @override
  Widget build(BuildContext context) {
    if (!impact.requiresReplan) return const SizedBox.shrink();

    final missedMinutes = _ceilMinutes(impact.missedBy);
    final walkText = impact.transferWalkMinutes > 0
        ? '徒歩${impact.transferWalkMinutes}分を含めると、'
        : '';

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
            const SizedBox(height: 10),
            Text(
              '${_clock(impact.predictedArrivalAt)} '
              '${impact.currentAlightingPlaceName}到着見込みです。',
            ),
            const SizedBox(height: 4),
            Text(
              '$walkText${_clock(impact.nextDepartureAt)}発 '
              '${impact.nextRideTitle}には約$missedMinutes分間に合わない見込みです。',
            ),
            if (helperText != null && helperText!.trim().isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                helperText!,
                style: const TextStyle(color: Colors.black54, fontSize: 13),
              ),
            ],
            if (action != null) ...[
              const SizedBox(height: 10),
              action!,
            ],
          ],
        ),
      ),
    );
  }

  static String _clock(DateTime value) {
    final local = value.toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }

  static int _ceilMinutes(Duration duration) {
    final seconds = duration.inSeconds;
    if (seconds <= 0) return 0;
    return (seconds + 59) ~/ 60;
  }
}

import 'package:flutter/material.dart';

import '../logic/group_schedule_impact.dart';

class GroupScheduleImpactCard extends StatelessWidget {
  final GroupScheduleImpact impact;
  final String? helperText;

  const GroupScheduleImpactCard({
    super.key,
    required this.impact,
    this.helperText,
  });

  @override
  Widget build(BuildContext context) {
    final overrunMinutes = _ceilMinutes(impact.overrun);
    final basisText = switch (impact.arrival.basis) {
      GroupArrivalEstimateBasis.routeSchedule =>
        '現在の経路予定では ${_clock(impact.arrival.expectedArrivalAt)} 到着予定です。',
      GroupArrivalEstimateBasis.finalRideRealtime =>
        '現在乗車中の便から ${_clock(impact.arrival.expectedArrivalAt)} 到着見込みです。',
    };

    return Card(
      margin: EdgeInsets.zero,
      elevation: 2,
      color: Colors.amber.shade50,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Colors.amber.shade400),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.schedule, color: Colors.amber.shade900),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '到着見込みが次の予定を過ぎます',
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(basisText),
            const SizedBox(height: 4),
            Text(
              '「${impact.affectedEntry.label}」は '
              '${_clock(impact.affectedEntry.plannedAt)} 予定のため、'
              '約$overrunMinutes分過ぎる見込みです。',
            ),
            const SizedBox(height: 8),
            const Text(
              '交通経路の変更だけでは、この予定時刻は自動で動かしません。',
              style: TextStyle(color: Colors.black54, fontSize: 13),
            ),
            if (helperText != null && helperText!.trim().isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                helperText!,
                style: const TextStyle(color: Colors.black54, fontSize: 13),
              ),
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

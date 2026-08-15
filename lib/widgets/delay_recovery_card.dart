import 'package:flutter/material.dart';

import '../logic/delay_impact_analyzer.dart';
import '../logic/next_ride_realtime.dart';

class DelayRecoveryCard extends StatelessWidget {
  final DelayImpact impact;
  final Widget? action;
  final String? helperText;
  final NextRideRealtimeDeparture? nextRideRealtime;
  final DateTime? scheduledNextDepartureAt;
  final String? realtimeDiagnostic;

  const DelayRecoveryCard({
    super.key,
    required this.impact,
    this.action,
    this.helperText,
    this.nextRideRealtime,
    this.scheduledNextDepartureAt,
    this.realtimeDiagnostic,
  });

  @override
  Widget build(BuildContext context) {
    if (!impact.requiresReplan) return const SizedBox.shrink();

    final missedMinutes = _ceilMinutes(impact.missedBy);
    final isConfirmedTransfer =
        impact.basis == DelayImpactBasis.confirmedTransferPlace;
    final basisText = isConfirmedTransfer
        ? '${_clock(impact.predictedArrivalAt)}現在、'
            '${impact.currentAlightingPlaceName}を最後に確認できた地点として見積もっています。'
        : '${_clock(impact.predictedArrivalAt)} '
            '${impact.currentAlightingPlaceName}到着見込みです。';
    final walkText = impact.transferWalkMinutes <= 0
        ? ''
        : isConfirmedTransfer
        ? '現在地を推測せず、予定の徒歩${impact.transferWalkMinutes}分をすべて見込むと、'
        : '徒歩${impact.transferWalkMinutes}分を含めると、';

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
            Text(basisText),
            const SizedBox(height: 4),
            Text(_transferRiskText(walkText, missedMinutes)),
            if (nextRideRealtime != null) ...[
              const SizedBox(height: 6),
              Text(
                _nextRideRealtimeText(),
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ],
            if (realtimeDiagnostic != null &&
                realtimeDiagnostic!.trim().isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                realtimeDiagnostic!,
                style: TextStyle(color: Colors.red.shade700, fontSize: 12),
              ),
            ],
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

  String _transferRiskText(String walkText, int missedMinutes) {
    final realtime = nextRideRealtime;
    if (realtime?.status ==
        NextRideRealtimeDepartureStatus.passedBoardingPlace) {
      return '$walkText${impact.nextRideTitle}は乗車地点を通過済みです。';
    }
    return '$walkText${_clock(impact.nextDepartureAt)}発 '
        '${impact.nextRideTitle}には約$missedMinutes分間に合わない見込みです。';
  }

  String _nextRideRealtimeText() {
    final realtime = nextRideRealtime!;
    switch (realtime.status) {
      case NextRideRealtimeDepartureStatus.predicted:
        final scheduled = scheduledNextDepartureAt;
        if (scheduled == null) {
          throw StateError('次便Realtime適用時に予定出発時刻がありません');
        }
        return '次便Realtime: ${_clock(impact.nextDepartureAt)}発見込み '
            '（予定 ${_clock(scheduled)}）';
      case NextRideRealtimeDepartureStatus.atBoardingPlace:
        return '次便Realtime: ${_clock(realtime.observedAt)}時点で'
            '${realtime.boardingPlaceName}に到着済みです。';
      case NextRideRealtimeDepartureStatus.passedBoardingPlace:
        return '次便Realtime: ${_clock(realtime.observedAt)}時点で'
            '${realtime.boardingPlaceName}を通過済みです。';
    }
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

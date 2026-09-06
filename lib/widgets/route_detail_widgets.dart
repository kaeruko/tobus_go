import 'package:flutter/cupertino.dart';

import '../models/fare_models.dart';
import '../models/route_models.dart';
import '../pages/segment_stops_page.dart';
import '../utils/string_utils.dart';
import 'timetable_view.dart';

class RouteFutureSuggestionAlert extends StatelessWidget {
  final DateTime? date;

  const RouteFutureSuggestionAlert({super.key, required this.date});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.activeOrange.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: CupertinoColors.activeOrange),
      ),
      child: Row(
        children: [
          const Icon(
            CupertinoIcons.exclamationmark_triangle_fill,
            color: CupertinoColors.activeOrange,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'ご指定の日時は運行終了または運休日のため、\n'
              '${date?.toString().split(' ')[0]} の経路を表示しています。',
              style: const TextStyle(
                color: CupertinoColors.activeOrange,
                fontWeight: FontWeight.bold,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class RouteEndpointSummary extends StatelessWidget {
  final Candidate candidate;
  final RouteMeta? meta;

  const RouteEndpointSummary({super.key, required this.candidate, this.meta});

  String get _origin =>
      StringUtils.extractSimpleName(routeOriginLabel(candidate));

  String get _destination {
    if (meta?.destinationReachable == false) {
      final stop = meta?.fallbackNodeName ?? '最寄り停留所';
      final minutes = meta?.fallbackWalkMinutes;
      final suffix = minutes != null ? '（目的地まで徒歩約${minutes}分）' : '';
      return stop + suffix;
    }
    return StringUtils.extractSimpleName(routeDestinationLabel(candidate));
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: CupertinoColors.systemGrey6.resolveFrom(context),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _row(CupertinoIcons.location_solid, '出発', _origin),
            const SizedBox(height: 6),
            _row(CupertinoIcons.flag, '目的地', _destination),
          ],
        ),
      ),
    );
  }

  Widget _row(IconData icon, String label, String text) {
    return Row(
      children: [
        Icon(icon, size: 18, color: CupertinoColors.activeBlue),
        const SizedBox(width: 8),
        Text(
          label,
          style: const TextStyle(
            color: CupertinoColors.systemGrey,
            fontSize: 12,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}

class RouteFallbackDestinationNotice extends StatelessWidget {
  final RouteMeta meta;

  const RouteFallbackDestinationNotice({super.key, required this.meta});

  @override
  Widget build(BuildContext context) {
    final stop = meta.fallbackNodeName ?? '最寄り停留所';
    final minutes = meta.fallbackWalkMinutes;
    final walkText = minutes != null
        ? '徒歩約${minutes}分'
        : (meta.fallbackDistanceM != null
              ? '徒歩${meta.fallbackDistanceM!.toStringAsFixed(0)}m程度'
              : '徒歩圏内');

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.systemYellow.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: CupertinoColors.systemYellow),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(
                CupertinoIcons.exclamationmark_triangle_fill,
                color: CupertinoColors.systemOrange,
              ),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  '目的地付近までの経路のみ表示しています',
                  style: TextStyle(
                    color: CupertinoColors.activeOrange,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '${meta.destinationLabel}に直接到達できません。'
            '最寄りは「$stop」で、ここから$walkTextです。',
            style: const TextStyle(fontSize: 14),
          ),
        ],
      ),
    );
  }
}

class RouteSummary extends StatelessWidget {
  final Candidate candidate;

  const RouteSummary({super.key, required this.candidate});

  String _startTime(String? arrival, int durationMinutes) {
    if (arrival == null || !arrival.contains(':')) return '--:--';
    final parts = arrival.split(':');
    if (parts.length < 2) return '--:--';
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null || minute < 0 || minute >= 60) {
      return '--:--';
    }
    final startMinutes = hour * 60 + minute - durationMinutes;
    final normalized = ((startMinutes % (24 * 60)) + (24 * 60)) % (24 * 60);
    return '${(normalized ~/ 60).toString().padLeft(2, '0')}:'
        '${(normalized % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final arrival = candidate.arrivalTime;
    final start = _startTime(arrival, candidate.totalTime);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                start,
                style: const TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: CupertinoColors.activeBlue,
                ),
              ),
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 12),
                child: Icon(
                  CupertinoIcons.arrow_right,
                  color: CupertinoColors.systemGrey,
                ),
              ),
              Text(
                arrival ?? '--:--',
                style: const TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _stat('所要時間', '${candidate.totalTime}分'),
              _stat('乗換', candidate.transfers.toString()),
              _stat('乗車区間', candidate.rides.toString()),
              _stat('徒歩', '${candidate.walkingDistanceMeters}m'),
            ],
          ),
        ),
      ],
    );
  }

  Widget _stat(String label, String value) {
    return Column(
      children: [
        Text(
          value,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: const TextStyle(
            color: CupertinoColors.inactiveGray,
            fontSize: 12,
          ),
        ),
      ],
    );
  }
}

class FareSummary extends StatelessWidget {
  final FareQuote? fare;

  const FareSummary({super.key, required this.fare});

  @override
  Widget build(BuildContext context) {
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

    final showSettlementLabel = quote.settlementType != 'normal';
    if (!showSettlementLabel && lines.isEmpty) {
      return const SizedBox.shrink();
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
            if (showSettlementLabel) ...[
              Text(
                quote.settlementLabel,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              if (lines.isNotEmpty) const SizedBox(height: 4),
            ],
            for (final line in lines) Text(line),
          ],
        ),
      ),
    );
  }
}

class RouteStepTile extends StatelessWidget {
  final StepSeg segment;
  final bool showTimetable;

  const RouteStepTile({
    super.key,
    required this.segment,
    this.showTimetable = false,
  });

  @override
  Widget build(BuildContext context) {
    final isWalk = segment.kind == 'walk';
    final canShowStops = !isWalk && segment.stops.isNotEmpty;
    final rightText = _rightText(isWalk);

    final content = Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: CupertinoColors.systemBackground.resolveFrom(context),
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
          Row(
            children: [
              _RouteStepIcon(kind: segment.kind),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      segment.mainTitle,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    if (segment.departureTime != null &&
                        segment.arrivalTime != null)
                      Text(
                        '${segment.departureTime} → ${segment.arrivalTime}',
                        style: const TextStyle(
                          fontSize: 13,
                          color: CupertinoColors.activeBlue,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    if (segment.subTitle != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        segment.subTitle!,
                        style: const TextStyle(
                          color: CupertinoColors.inactiveGray,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (rightText.isNotEmpty)
                Text(
                  rightText,
                  style: const TextStyle(
                    fontSize: 13,
                    color: CupertinoColors.systemGrey,
                  ),
                ),
            ],
          ),
          if (showTimetable &&
              segment.kind == 'bus' &&
              segment.routeId != null &&
              segment.routeId!.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Container(height: 1, color: CupertinoColors.systemGrey5),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: TimetableView(
                routeId: segment.routeId!,
                stopId: segment.departureStopId,
                targetPoleId: segment.arrivalPoleId,
              ),
            ),
          ],
        ],
      ),
    );

    if (!canShowStops) return content;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => Navigator.of(context).push(
        CupertinoPageRoute(builder: (_) => SegmentStopsPage(segment: segment)),
      ),
      child: content,
    );
  }

  String _rightText(bool isWalk) {
    if (segment.minutes > 0) return '約${segment.minutes}分';
    if (!isWalk && segment.edges > 0) return '${segment.edges}停';
    if (isWalk && segment.meters > 0) {
      return '${segment.meters.round()}m';
    }
    return '';
  }
}

class _RouteStepIcon extends StatelessWidget {
  final String kind;

  const _RouteStepIcon({required this.kind});

  @override
  Widget build(BuildContext context) {
    final (icon, color) = switch (kind) {
      'walk' => (CupertinoIcons.paw_solid, CupertinoColors.activeOrange),
      'wait' => (CupertinoIcons.clock, CupertinoColors.systemGrey),
      'rail' => (CupertinoIcons.tram_fill, CupertinoColors.systemPurple),
      'bus' => (CupertinoIcons.bus, CupertinoColors.activeBlue),
      _ => throw StateError('Unsupported route step kind: $kind'),
    };
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

String routeOriginLabel(Candidate candidate) {
  if (!_isPlaceholder(candidate.originName)) return candidate.originName!;
  if (candidate.steps.isNotEmpty &&
      !_isPlaceholder(candidate.steps.first.from)) {
    return candidate.steps.first.from!;
  }
  return '出発地';
}

String routeDestinationLabel(Candidate candidate) {
  if (!_isPlaceholder(candidate.destinationName)) {
    return candidate.destinationName!;
  }
  if (candidate.steps.isNotEmpty && !_isPlaceholder(candidate.steps.last.to)) {
    return candidate.steps.last.to!;
  }
  return '目的地';
}

bool _isPlaceholder(String? value) {
  const placeholders = {'出発地', '目的地'};
  if (value == null) return true;
  final trimmed = value.trim();
  return trimmed.isEmpty || placeholders.contains(trimmed);
}

import 'package:flutter/cupertino.dart';

import '../models/route_models.dart';

class SegmentStopsPage extends StatelessWidget {
  final StepSeg segment;

  const SegmentStopsPage({
    super.key,
    required this.segment,
  });

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: CupertinoNavigationBar(
        middle: Text(
          segment.title.isEmpty ? segment.mainTitle : segment.title,
        ),
      ),
      child: SafeArea(
        child: ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          itemCount: segment.stops.length,
          itemBuilder: (context, index) {
            final stop = segment.stops[index];
            final isFirst = index == 0;
            final isLast = index == segment.stops.length - 1;

            return _StopRow(
              stop: stop,
              isFirst: isFirst,
              isLast: isLast,
            );
          },
        ),
      ),
    );
  }
}

class _StopRow extends StatelessWidget {
  final StopPoint stop;
  final bool isFirst;
  final bool isLast;

  const _StopRow({
    required this.stop,
    required this.isFirst,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final nameStyle = TextStyle(
      fontSize: 16,
      fontWeight:
          (stop.isOrigin || stop.isDestination)
              ? FontWeight.w600
              : FontWeight.w400,
    );

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 32,
          child: Column(
            children: [
              Container(
                width: 20,
                height: 20,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: CupertinoColors.activeGreen,
                    width: 2,
                  ),
                  color:
                      stop.isOrigin || stop.isDestination
                          ? CupertinoColors.activeGreen
                          : CupertinoColors.white,
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 42,
                  color: CupertinoColors.systemGrey4,
                ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(stop.name, style: nameStyle),
                if (stop.isOrigin || stop.isDestination) ...[
                  const SizedBox(height: 2),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: CupertinoColors.systemGrey5,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      stop.isOrigin
                          ? '乗車'
                          : (stop.isDestination ? '降車' : ''),
                      style: const TextStyle(
                        fontSize: 10,
                        color: CupertinoColors.inactiveGray,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }
}
import 'package:flutter/material.dart';

import '../logic/route_replan_preview.dart';
import '../models/route_models.dart';
import 'route_replan_comparison_map.dart';

class RouteReplanComparisonSheet extends StatefulWidget {
  final RouteReplanPreview preview;
  final ValueChanged<Candidate>? onApply;

  const RouteReplanComparisonSheet({
    super.key,
    required this.preview,
    this.onApply,
  });

  @override
  State<RouteReplanComparisonSheet> createState() =>
      _RouteReplanComparisonSheetState();
}

class _RouteReplanComparisonSheetState
    extends State<RouteReplanComparisonSheet> {
  int _selectedIndex = 0;

  @override
  Widget build(BuildContext context) {
    final preview = widget.preview;
    final candidates = preview.newCandidates;
    final selected = candidates.isEmpty ? null : candidates[_selectedIndex];

    return SafeArea(
      top: false,
      child: DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.86,
        minChildSize: 0.55,
        maxChildSize: 0.96,
        builder: (context, scrollController) {
          return Material(
            color: Theme.of(context).scaffoldBackgroundColor,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
            clipBehavior: Clip.antiAlias,
            child: ListView(
              controller: scrollController,
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(
                      color: Colors.black26,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: 18),
                Text(
                  '${preview.request.anchor.placeName}から経路を見直す',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
                const SizedBox(height: 6),
                Text(
                  '${RouteReplanPreview.formatClock(preview.request.anchor.availableAt)}から利用できる経路を比較します',
                  style: const TextStyle(color: Colors.black54),
                ),
                const SizedBox(height: 18),
                RouteReplanComparisonMap(
                  key: ValueKey(selected?.id ?? 'no-new-route'),
                  originalPoints: preview.originalFuturePoints,
                  newPoints: selected == null
                      ? const []
                      : preview.pointsForNewCandidate(selected),
                  anchor: preview.request.anchor.point,
                  destination: preview.request.destination,
                ),
                const SizedBox(height: 18),
                _RouteSummaryCard(
                  title: '現在の予定',
                  arrivalLabel: '${preview.originalArrivalLabel} 到着予定',
                  lineSummary:
                      RouteReplanPreview.lineSummary(preview.originalCandidate),
                  transfers: preview.originalCandidate.transfers,
                  emphasized: false,
                ),
                const SizedBox(height: 12),
                if (candidates.isEmpty)
                  const _NoRouteFoundCard()
                else ...[
                  if (candidates.length > 1) ...[
                    Text(
                      '新しい経路の候補',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                    ),
                    const SizedBox(height: 8),
                    SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: List.generate(candidates.length, (index) {
                          final candidate = candidates[index];
                          return Padding(
                            padding: const EdgeInsets.only(right: 8),
                            child: ChoiceChip(
                              selected: _selectedIndex == index,
                              label: Text(
                                '候補${index + 1}  ${RouteReplanPreview.arrivalLabel(candidate)}着',
                              ),
                              onSelected: (selected) {
                                if (!selected) return;
                                setState(() => _selectedIndex = index);
                              },
                            ),
                          );
                        }),
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],
                  _RouteSummaryCard(
                    title: '新しい経路',
                    arrivalLabel:
                        '${RouteReplanPreview.arrivalLabel(selected!)} 到着予定',
                    lineSummary: RouteReplanPreview.lineSummary(selected!),
                    transfers: selected!.transfers,
                    emphasized: true,
                  ),
                ],
                const SizedBox(height: 18),
                if (widget.onApply == null)
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.amber.shade50,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.amber.shade200),
                    ),
                    child: const Text(
                      'いまは比較だけです。この画面を閉じても予定は変更されません。',
                      style: TextStyle(fontSize: 13),
                    ),
                  ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () => Navigator.of(context).pop(),
                        child: const Text('元の経路を続ける'),
                      ),
                    ),
                    if (widget.onApply != null && selected != null) ...[
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton(
                          onPressed: () => widget.onApply!(selected),
                          child: const Text('この経路に変更'),
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _RouteSummaryCard extends StatelessWidget {
  final String title;
  final String arrivalLabel;
  final String lineSummary;
  final int transfers;
  final bool emphasized;

  const _RouteSummaryCard({
    required this.title,
    required this.arrivalLabel,
    required this.lineSummary,
    required this.transfers,
    required this.emphasized,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: emphasized ? Colors.blue.shade50 : Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: emphasized ? Colors.blue.shade200 : Colors.black12,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
          ),
          const SizedBox(height: 8),
          Text(arrivalLabel, style: const TextStyle(fontSize: 18)),
          const SizedBox(height: 6),
          Text(lineSummary),
          const SizedBox(height: 4),
          Text(
            '乗換え $transfers回',
            style: const TextStyle(color: Colors.black54),
          ),
        ],
      ),
    );
  }
}

class _NoRouteFoundCard extends StatelessWidget {
  const _NoRouteFoundCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.orange.shade50,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.orange.shade200),
      ),
      child: const Text('この時刻から利用できる新しい経路が見つかりませんでした。'),
    );
  }
}

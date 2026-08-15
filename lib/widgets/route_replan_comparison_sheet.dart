import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/route_replan_preview.dart';
import '../models/route_models.dart';
import '../providers/route_replanner_provider.dart';
import '../providers/trip_provider.dart';
import '../services/route_replanner.dart';
import 'route_replan_comparison_map.dart';

typedef RouteReplanApplyCallback = Future<void> Function(
  RouteReplanPreview preview,
  Candidate candidate,
);

class RouteReplanComparisonSheet extends ConsumerStatefulWidget {
  final RouteReplanPreview preview;
  final RouteReplanApplyCallback? onApply;

  const RouteReplanComparisonSheet({
    super.key,
    required this.preview,
    this.onApply,
  });

  @override
  ConsumerState<RouteReplanComparisonSheet> createState() =>
      _RouteReplanComparisonSheetState();
}

class _RouteReplanComparisonSheetState
    extends ConsumerState<RouteReplanComparisonSheet> {
  late RouteReplanPreview _preview;
  int _selectedIndex = 0;
  bool _applying = false;
  bool _refreshing = false;
  Object? _refreshError;

  @override
  void initState() {
    super.initState();
    _preview = widget.preview;
  }

  @override
  Widget build(BuildContext context) {
    final currentRequest = ref.watch(currentRouteReplanRequestProvider);
    final previewMatchesCurrent = currentRequest != null &&
        sameRouteReplanRequestState(currentRequest, _preview.request);

    if (!_applying &&
        !_refreshing &&
        currentRequest != null &&
        !previewMatchesCurrent) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _refreshFor(currentRequest);
      });
    }

    final preview = _preview;
    final candidates = preview.newCandidates;
    if (candidates.isNotEmpty && _selectedIndex >= candidates.length) {
      throw StateError(
        '再探索候補の選択indexが不正です: '
        'index=$_selectedIndex, candidates=${candidates.length}',
      );
    }
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
                if (_refreshing) ...[
                  const SizedBox(height: 12),
                  const _RefreshNotice(
                    message: '移動状況が変わったため、新しい到着見込みで経路を再検索しています…',
                    loading: true,
                  ),
                ] else if (currentRequest == null) ...[
                  const SizedBox(height: 12),
                  const _RefreshNotice(
                    message: '現在の再探索起点を取得できません。状況が確認できるまで経路変更は確定できません。',
                  ),
                ] else if (!previewMatchesCurrent && _refreshError != null) ...[
                  const SizedBox(height: 12),
                  _RefreshErrorNotice(
                    error: _refreshError!,
                    onRetry: _applying ? null : () => _refreshFor(currentRequest),
                  ),
                ],
                const SizedBox(height: 18),
                RouteReplanComparisonMap(
                  key: ValueKey(
                    '${preview.request.anchor.availableAt.microsecondsSinceEpoch}:'
                    '${selected?.id ?? 'no-new-route'}',
                  ),
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
                              onSelected: _applying || _refreshing
                                  ? null
                                  : (selected) {
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
                    lineSummary: RouteReplanPreview.lineSummary(selected),
                    transfers: selected.transfers,
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
                        onPressed: _applying
                            ? null
                            : () => Navigator.of(context).pop(false),
                        child: const Text('元の経路を続ける'),
                      ),
                    ),
                    if (widget.onApply != null && selected != null) ...[
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton(
                          onPressed: _applying ||
                                  _refreshing ||
                                  !previewMatchesCurrent
                              ? null
                              : () => _apply(selected),
                          child: _applying
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : _refreshing
                                  ? const Text('再検索中…')
                                  : const Text('この経路に変更'),
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

  Future<void> _refreshFor(RouteReplanRequest requested) async {
    if (_refreshing || _applying) return;

    setState(() {
      _refreshing = true;
      _refreshError = null;
    });

    var target = requested;
    try {
      while (mounted) {
        final result = await ref.read(routeReplannerProvider).replan(target);
        if (!mounted) return;

        final latestRequest = ref.read(currentRouteReplanRequestProvider);
        if (latestRequest == null) {
          throw StateError('再検索中に現在の再探索起点を取得できなくなりました');
        }

        if (!sameRouteReplanRequestState(latestRequest, target)) {
          target = latestRequest;
          continue;
        }

        final latestTrip = ref.read(tripStreamProvider).value;
        if (latestTrip == null) {
          throw StateError('再検索中に現在のTripを取得できません');
        }

        final nextPreview = RouteReplanPreview.build(
          trip: latestTrip,
          request: latestRequest,
          result: result,
        );
        final selectedId = _selectedCandidateId();
        final nextSelectedIndex = _indexForCandidateId(
          nextPreview.newCandidates,
          selectedId,
        );

        setState(() {
          _preview = nextPreview;
          _selectedIndex = nextSelectedIndex;
          _refreshError = null;
        });
        break;
      }
    } catch (error) {
      if (!mounted) return;
      setState(() => _refreshError = error);
    } finally {
      if (mounted) {
        setState(() => _refreshing = false);
      }
    }
  }

  String? _selectedCandidateId() {
    final candidates = _preview.newCandidates;
    if (candidates.isEmpty) return null;
    if (_selectedIndex < 0 || _selectedIndex >= candidates.length) {
      throw StateError(
        '再探索候補の選択indexが不正です: '
        'index=$_selectedIndex, candidates=${candidates.length}',
      );
    }
    return candidates[_selectedIndex].id;
  }

  int _indexForCandidateId(List<Candidate> candidates, String? candidateId) {
    if (candidates.isEmpty || candidateId == null) return 0;
    for (var index = 0; index < candidates.length; index++) {
      if (candidates[index].id == candidateId) return index;
    }
    return 0;
  }

  Future<void> _apply(Candidate selected) async {
    final onApply = widget.onApply;
    if (onApply == null || _applying || _refreshing) return;

    final currentRequest = ref.read(currentRouteReplanRequestProvider);
    if (currentRequest == null ||
        !sameRouteReplanRequestState(currentRequest, _preview.request)) {
      if (currentRequest != null) {
        await _refreshFor(currentRequest);
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('移動状況が変わったため、経路を更新しました。内容を確認してください。')),
      );
      return;
    }

    setState(() => _applying = true);
    try {
      await onApply(_preview, selected);
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('経路を変更できませんでした: $error')),
      );
    } finally {
      if (mounted) {
        setState(() => _applying = false);
      }
    }
  }
}

class _RefreshNotice extends StatelessWidget {
  final String message;
  final bool loading;

  const _RefreshNotice({required this.message, this.loading = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.blue.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.blue.shade200),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (loading)
            const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          else
            const Icon(Icons.info_outline, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}

class _RefreshErrorNotice extends StatelessWidget {
  final Object error;
  final VoidCallback? onRetry;

  const _RefreshErrorNotice({required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.orange.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.orange.shade300),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('最新の移動状況で経路を更新できませんでした: $error'),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('もう一度更新'),
            ),
          ),
        ],
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

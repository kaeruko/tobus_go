import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../l10n/transit_name_localizations.dart';
import '../logic/route_replan_preview.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../services/route_replanner.dart';
import '../services/route_search_service.dart';
import 'route_replan_comparison_map.dart';

typedef RouteReplanApplyCallback = Future<void> Function(
  RouteReplanPreview preview,
  Candidate candidate,
);

typedef RouteReplanRefreshCallback = Future<RouteSearchResult> Function(
  RouteReplanRequest request,
);

class RouteReplanComparisonController extends ChangeNotifier {
  Trip _trip;
  RouteReplanRequest? _currentRequest;
  String? _blockedReason;

  RouteReplanComparisonController({
    required Trip trip,
    RouteReplanRequest? currentRequest,
    String? blockedReason,
  })  : _trip = trip,
        _currentRequest = currentRequest,
        _blockedReason = blockedReason;

  Trip get trip => _trip;
  RouteReplanRequest? get currentRequest => _currentRequest;
  String? get blockedReason => _blockedReason;

  void sync({
    required Trip trip,
    required RouteReplanRequest? currentRequest,
    required String? blockedReason,
  }) {
    final requestUnchanged =
        _sameNullableRequest(_currentRequest, currentRequest);
    final unchanged = identical(_trip, trip) &&
        requestUnchanged &&
        _blockedReason == blockedReason;
    if (unchanged) return;

    _trip = trip;
    _currentRequest = currentRequest;
    _blockedReason = blockedReason;
    notifyListeners();
  }

  static bool _sameNullableRequest(
    RouteReplanRequest? a,
    RouteReplanRequest? b,
  ) {
    if (identical(a, b)) return true;
    if (a == null || b == null) return false;
    return sameRouteReplanRequestState(a, b);
  }
}

class RouteReplanComparisonSheet extends StatefulWidget {
  final RouteReplanPreview preview;
  final RouteReplanComparisonController controller;
  final RouteReplanRefreshCallback onRefresh;
  final RouteReplanApplyCallback? onApply;

  const RouteReplanComparisonSheet({
    super.key,
    required this.preview,
    required this.controller,
    required this.onRefresh,
    this.onApply,
  });

  @override
  State<RouteReplanComparisonSheet> createState() =>
      _RouteReplanComparisonSheetState();
}

class _RouteReplanComparisonSheetState
    extends State<RouteReplanComparisonSheet> {
  late RouteReplanPreview _preview;
  int _selectedIndex = 0;
  bool _applying = false;
  bool _refreshing = false;
  bool _closingAfterApply = false;
  Object? _refreshError;
  RouteReplanRequest? _failedRequest;
  bool _controllerRebuildScheduled = false;

  @override
  void initState() {
    super.initState();
    _preview = widget.preview;
    widget.controller.addListener(_onControllerChanged);
  }

  @override
  void didUpdateWidget(covariant RouteReplanComparisonSheet oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.controller, widget.controller)) {
      oldWidget.controller.removeListener(_onControllerChanged);
      widget.controller.addListener(_onControllerChanged);
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    super.dispose();
  }

  void _onControllerChanged() {
    if (!mounted || _closingAfterApply || _controllerRebuildScheduled) {
      return;
    }
    _controllerRebuildScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _controllerRebuildScheduled = false;
      if (!mounted || _closingAfterApply) return;
      setState(() {});
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
    final currentRequest = widget.controller.currentRequest;
    final blockedReason = widget.controller.blockedReason;
    final previewMatchesCurrent = currentRequest != null &&
        sameRouteReplanRequestState(currentRequest, _preview.request);
    final failedForCurrent = currentRequest != null &&
        _failedRequest != null &&
        sameRouteReplanRequestState(currentRequest, _failedRequest!);

    if (!_closingAfterApply &&
        !_applying &&
        !_refreshing &&
        currentRequest != null &&
        !previewMatchesCurrent &&
        !failedForCurrent) {
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
      child: FractionallySizedBox(
        heightFactor: 0.92,
        alignment: Alignment.bottomCenter,
        child: Material(
          color: Theme.of(context).scaffoldBackgroundColor,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
          clipBehavior: Clip.antiAlias,
          child: ListView(
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
                  l10n.replanTitle(preview.request.anchor.placeName),
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
                const SizedBox(height: 6),
                Text(
                  l10n.replanCompareFrom(
                    RouteReplanPreview.formatClock(
                      preview.request.anchor.availableAt,
                    ),
                  ),
                  style: const TextStyle(color: Colors.black54),
                ),
                if (_refreshing) ...[
                  const SizedBox(height: 12),
                  _RefreshNotice(
                    message: l10n.replanRefreshing,
                    loading: true,
                  ),
                ] else if (currentRequest == null) ...[
                  const SizedBox(height: 12),
                  _RefreshNotice(
                    message: isEnglishTransitLocale(locale)
                        ? l10n.replanBlocked
                        : (blockedReason ?? l10n.replanBlocked),
                  ),
                ] else if (!previewMatchesCurrent &&
                    _refreshError != null &&
                    failedForCurrent) ...[
                  const SizedBox(height: 12),
                  _RefreshErrorNotice(
                    error: _refreshError!,
                    onRetry: _applying || _closingAfterApply
                        ? null
                        : () => _refreshFor(currentRequest),
                  ),
                ],
                const SizedBox(height: 18),
                RouteReplanComparisonMap(
                  originalPoints: preview.originalFuturePoints,
                  newPoints: selected == null
                      ? const []
                      : preview.pointsForNewCandidate(selected),
                  anchor: preview.request.anchor.point,
                  destination: preview.request.destination,
                ),
                const SizedBox(height: 18),
                _RouteSummaryCard(
                  title: l10n.replanCurrentPlan,
                  arrivalLabel: l10n.replanArrivalPlanned(
                    RouteReplanPreview.arrivalLabel(
                      preview.originalCandidate,
                      unknownLabel: l10n.replanUnknownTime,
                    ),
                  ),
                  lineSummary: RouteReplanPreview.lineSummary(
                    preview.originalCandidate,
                    locale: locale,
                    walkOnlyLabel: l10n.replanWalkOnly,
                  ),
                  transfers: preview.originalCandidate.transfers,
                  emphasized: false,
                ),
                const SizedBox(height: 12),
                if (candidates.isEmpty)
                  const _NoRouteFoundCard()
                else ...[
                  if (candidates.length > 1) ...[
                    Text(
                      l10n.replanNewRouteCandidates,
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
                                l10n.replanCandidate(
                                  index + 1,
                                  RouteReplanPreview.arrivalLabel(
                                    candidate,
                                    unknownLabel: l10n.replanUnknownTime,
                                  ),
                                ),
                              ),
                              onSelected: _closingAfterApply ||
                                      _applying ||
                                      _refreshing
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
                    title: l10n.replanNewRoute,
                    arrivalLabel: l10n.replanArrivalPlanned(
                      RouteReplanPreview.arrivalLabel(
                        selected!,
                        unknownLabel: l10n.replanUnknownTime,
                      ),
                    ),
                    lineSummary: RouteReplanPreview.lineSummary(
                      selected!,
                      locale: locale,
                      walkOnlyLabel: l10n.replanWalkOnly,
                    ),
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
                    child: Text(
                      l10n.replanCompareOnly,
                      style: const TextStyle(fontSize: 13),
                    ),
                  ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: _closingAfterApply || _applying
                            ? null
                            : () => Navigator.of(context).pop(false),
                        child: Text(l10n.replanKeepOriginal),
                      ),
                    ),
                    if (widget.onApply != null && selected != null) ...[
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton(
                          onPressed: _closingAfterApply ||
                                  _applying ||
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
                                  ? Text(l10n.researching)
                                  : Text(l10n.replanApply),
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ),
    );
  }

  Future<void> _refreshFor(RouteReplanRequest requested) async {
    if (_closingAfterApply || _refreshing || _applying) return;

    setState(() {
      _refreshing = true;
      _refreshError = null;
      _failedRequest = null;
    });

    var target = requested;
    try {
      while (mounted && !_closingAfterApply) {
        final result = await widget.onRefresh(target);
        if (!mounted || _closingAfterApply) return;

        final latestRequest = widget.controller.currentRequest;
        if (latestRequest == null) {
          throw StateError(
            widget.controller.blockedReason ??
                '再検索中に現在の再探索起点を取得できなくなりました',
          );
        }

        if (!sameRouteReplanRequestState(latestRequest, target)) {
          target = latestRequest;
          continue;
        }

        final nextPreview = RouteReplanPreview.build(
          trip: widget.controller.trip,
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
          _failedRequest = null;
        });
        break;
      }
    } catch (error) {
      if (!mounted || _closingAfterApply) return;
      setState(() {
        _refreshError = error;
        _failedRequest = target;
      });
    } finally {
      if (mounted && !_closingAfterApply) {
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
    if (onApply == null || _closingAfterApply || _applying || _refreshing) {
      return;
    }

    final currentRequest = widget.controller.currentRequest;
    if (currentRequest == null ||
        !sameRouteReplanRequestState(currentRequest, _preview.request)) {
      if (currentRequest != null) {
        await _refreshFor(currentRequest);
      }
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l10n.replanUpdatedNotice)),
      );
      return;
    }

    setState(() => _applying = true);
    try {
      await onApply(_preview, selected);
      if (!mounted) return;

      // Applying the route updates providers watched by this sheet. Mark the
      // sheet as closing before popping so that those provider changes cannot
      // trigger an automatic preview refresh while the route is unmounting.
      _closingAfterApply = true;
      Navigator.of(context).pop(true);
    } catch (error) {
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l10n.replanApplyFailed(error.toString()))),
      );
    } finally {
      // Do not call setState after a successful apply. Navigator.pop starts
      // teardown asynchronously, and marking this sheet dirty during that
      // window races Riverpod's refresh/dispose scheduling.
      if (mounted && !_closingAfterApply) {
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
    final l10n = AppLocalizations.of(context);
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
          Text(l10n.replanRefreshFailed(error.toString())),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: Text(l10n.replanRefreshAgain),
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
    final l10n = AppLocalizations.of(context);
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
            l10n.replanTransfers(transfers),
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
    final l10n = AppLocalizations.of(context);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.orange.shade50,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.orange.shade200),
      ),
      child: Text(l10n.replanNoRoute),
    );
  }
}

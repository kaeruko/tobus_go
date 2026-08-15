import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/route_replan_patcher.dart';
import '../logic/route_replan_preview.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../providers/route_replanner_provider.dart';
import '../providers/trip_provider.dart';
import '../services/route_replan_commit_service.dart';
import '../services/route_replanner.dart';
import 'route_replan_comparison_sheet.dart';

class RouteReplanPreviewButton extends ConsumerStatefulWidget {
  final Trip trip;

  const RouteReplanPreviewButton({
    super.key,
    required this.trip,
  });

  @override
  ConsumerState<RouteReplanPreviewButton> createState() =>
      _RouteReplanPreviewButtonState();
}

class _RouteReplanPreviewButtonState
    extends ConsumerState<RouteReplanPreviewButton> {
  bool _loading = false;

  @override
  Widget build(BuildContext context) {
    final request = ref.watch(currentRouteReplanRequestProvider);
    if (request == null) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: OutlinedButton.icon(
        onPressed: _loading ? null : _openPreview,
        icon: _loading
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.alt_route),
        label: Text(_loading ? '新しい経路を検索中…' : '経路を見直す'),
      ),
    );
  }

  Future<void> _openPreview() async {
    final request = ref.read(currentRouteReplanRequestProvider);
    if (request == null || _loading) return;

    setState(() => _loading = true);
    try {
      final result = await ref.read(routeReplannerProvider).replan(request);
      final latestRequest = ref.read(currentRouteReplanRequestProvider);
      if (latestRequest == null || !_sameRequestState(latestRequest, request)) {
        throw StateError(
          '検索中に移動状況が変わりました。もう一度「経路を見直す」を押してください。',
        );
      }
      final latestTrip = ref.read(tripStreamProvider).value;
      if (latestTrip == null) {
        throw StateError('現在のTripを取得できません');
      }
      final preview = RouteReplanPreview.build(
        trip: latestTrip,
        request: latestRequest,
        result: result,
      );
      if (!mounted) return;

      final applied = await showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (_) => RouteReplanComparisonSheet(
          preview: preview,
          onApply: (candidate) => _applyCandidate(preview, candidate),
        ),
      );
      if (!mounted || applied != true) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${preview.request.anchor.placeName}からの新しい経路に変更しました',
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('新しい経路を検索できませんでした: $error')),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _applyCandidate(
    RouteReplanPreview preview,
    Candidate selectedCandidate,
  ) async {
    final currentRequest = ref.read(currentRouteReplanRequestProvider);
    if (currentRequest == null ||
        !_sameRequestState(currentRequest, preview.request)) {
      throw StateError(
        '比較表示中に移動状況が変わりました。いったん閉じて、もう一度経路を見直してください。',
      );
    }

    final tripAsync = ref.read(tripStreamProvider);
    final currentTrip = tripAsync.value;
    if (currentTrip == null) {
      throw StateError('現在のTripを取得できません');
    }
    if (!currentTrip.isSolo) {
      throw StateError('この経路変更操作は一人移動専用です');
    }

    final patch = RouteReplanPatcher.build(
      trip: currentTrip,
      request: currentRequest,
      selectedCandidate: selectedCandidate,
    );
    await RouteReplanCommitService().apply(
      tripId: currentTrip.id,
      patch: patch,
    );
  }

  bool _sameRequestState(RouteReplanRequest a, RouteReplanRequest b) {
    return a.activeStepId == b.activeStepId &&
        a.originalCandidateId == b.originalCandidateId &&
        a.destination == b.destination &&
        a.destinationName == b.destinationName &&
        a.preference == b.preference &&
        a.anchor.source == b.anchor.source &&
        a.anchor.routeStepId == b.anchor.routeStepId &&
        a.anchor.stopId == b.anchor.stopId &&
        a.anchor.placeName == b.anchor.placeName &&
        a.anchor.point == b.anchor.point &&
        a.anchor.availableAt.isAtSameMomentAs(b.anchor.availableAt);
  }
}

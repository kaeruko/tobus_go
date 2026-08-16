import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/replan_debug_log.dart';
import '../logic/route_replan_patcher.dart';
import '../logic/route_replan_preview.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../providers/route_replanner_provider.dart';
import '../providers/trip_provider.dart';
import '../services/route_replan_commit_service.dart';
import '../services/route_replanner.dart';
import '../services/user_service.dart';
import 'route_replan_comparison_sheet.dart';

class RouteReplanPreviewButton extends ConsumerStatefulWidget {
  final Trip trip;
  final bool allowGroupLeaderApply;

  const RouteReplanPreviewButton({
    super.key,
    required this.trip,
    this.allowGroupLeaderApply = false,
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
    final blockedReason = ref.watch(routeReplanBlockedReasonProvider);
    if (request == null) {
      if (blockedReason == null) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.only(top: 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            OutlinedButton.icon(
              onPressed: null,
              icon: const Icon(Icons.alt_route),
              label: const Text('経路を見直す'),
            ),
            const SizedBox(height: 6),
            Text(
              blockedReason,
              style: const TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ],
        ),
      );
    }

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
    if (request == null || _loading) {
      ReplanDebugLog.emit('replan_preview_tap_ignored', {
        'tripId': widget.trip.id,
        'requestNull': request == null,
        'loading': _loading,
        'blockedReason': ref.read(routeReplanBlockedReasonProvider),
      });
      return;
    }

    ReplanDebugLog.emit('replan_preview_tap', {
      'tripId': widget.trip.id,
      'allowGroupLeaderApply': widget.allowGroupLeaderApply,
      'activeStepId': request.activeStepId,
      'originalCandidateId': request.originalCandidateId,
      ...ReplanDebugLog.anchorFields(request.anchor),
    });

    setState(() => _loading = true);
    try {
      final result = await ref.read(routeReplannerProvider).replan(request);
      final latestRequest = ref.read(currentRouteReplanRequestProvider);
      if (latestRequest == null ||
          !sameRouteReplanRequestState(latestRequest, request)) {
        ReplanDebugLog.emit('replan_preview_search_became_stale', {
          'tripId': widget.trip.id,
          'searchedActiveStepId': request.activeStepId,
          'latestRequestNull': latestRequest == null,
          'blockedReason': ref.read(routeReplanBlockedReasonProvider),
          'searchedAnchorPlace': request.anchor.placeName,
          'searchedAnchorAt': request.anchor.availableAt.toIso8601String(),
          'latestAnchorPlace': latestRequest?.anchor.placeName,
          'latestAnchorAt': latestRequest?.anchor.availableAt.toIso8601String(),
          'candidateCount': result.candidates.length,
        });
        throw StateError(
          '検索中に移動状況が変わりました。もう一度「経路を見直す」を押してください。',
        );
      }
      final latestTrip = ref.read(tripStreamProvider).value;
      if (latestTrip == null) {
        throw StateError('現在のTripを取得できません');
      }
      _validateApplyPermission(latestTrip);

      final preview = RouteReplanPreview.build(
        trip: latestTrip,
        request: latestRequest,
        result: result,
      );
      ReplanDebugLog.emit('replan_preview_ready', {
        'tripId': latestTrip.id,
        'activeStepId': latestRequest.activeStepId,
        'candidateCount': preview.newCandidates.length,
        ...ReplanDebugLog.anchorFields(latestRequest.anchor),
      });
      if (!mounted) return;

      final applied = await showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (_) => RouteReplanComparisonSheet(
          preview: preview,
          onApply: (latestPreview, candidate) =>
              _applyCandidate(latestPreview, candidate),
        ),
      );
      ReplanDebugLog.emit('replan_preview_closed', {
        'tripId': latestTrip.id,
        'applied': applied == true,
        'blockedReasonAfterClose': ref.read(routeReplanBlockedReasonProvider),
      });
      if (!mounted || applied != true) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${ref.read(currentRouteReplanRequestProvider)?.anchor.placeName ?? preview.request.anchor.placeName}からの新しい経路に変更しました',
          ),
        ),
      );
    } catch (error) {
      ReplanDebugLog.emit('replan_preview_error', {
        'tripId': widget.trip.id,
        'error': error.toString(),
        'blockedReason': ref.read(routeReplanBlockedReasonProvider),
      });
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
        !sameRouteReplanRequestState(currentRequest, preview.request)) {
      ReplanDebugLog.emit('replan_apply_blocked_stale_preview', {
        'tripId': widget.trip.id,
        'selectedCandidateId': selectedCandidate.id,
        'currentRequestNull': currentRequest == null,
        'blockedReason': ref.read(routeReplanBlockedReasonProvider),
        'previewAnchorPlace': preview.request.anchor.placeName,
        'previewAnchorAt': preview.request.anchor.availableAt.toIso8601String(),
        'currentAnchorPlace': currentRequest?.anchor.placeName,
        'currentAnchorAt': currentRequest?.anchor.availableAt.toIso8601String(),
      });
      throw StateError(
        '比較表示中に移動状況が変わりました。最新の経路へ更新してから選び直してください。',
      );
    }

    final tripAsync = ref.read(tripStreamProvider);
    final currentTrip = tripAsync.value;
    if (currentTrip == null) {
      throw StateError('現在のTripを取得できません');
    }
    _validateApplyPermission(currentTrip);

    final actorUserId = UserService().currentUserId;
    if (actorUserId == null || actorUserId.trim().isEmpty) {
      throw StateError('経路変更を行うユーザーIDを取得できません');
    }

    final patch = RouteReplanPatcher.build(
      trip: currentTrip,
      request: currentRequest,
      selectedCandidate: selectedCandidate,
    );
    ReplanDebugLog.emit('replan_apply_start', {
      'tripId': currentTrip.id,
      'activeStepId': currentRequest.activeStepId,
      'selectedCandidateId': selectedCandidate.id,
      ...ReplanDebugLog.anchorFields(currentRequest.anchor),
    });
    await RouteReplanCommitService().apply(
      tripId: currentTrip.id,
      actorUserId: actorUserId,
      patch: patch,
    );
    ReplanDebugLog.emit('replan_apply_success', {
      'tripId': currentTrip.id,
      'selectedCandidateId': selectedCandidate.id,
    });
  }

  void _validateApplyPermission(Trip trip) {
    if (trip.isSolo) return;
    if (!widget.allowGroupLeaderApply) {
      throw StateError('この画面からグループ経路は変更できません');
    }

    final actorUserId = UserService().currentUserId;
    if (actorUserId == null || actorUserId.trim().isEmpty) {
      throw StateError('経路変更を行うユーザーIDを取得できません');
    }
    if (actorUserId != trip.leaderId) {
      throw StateError('グループの経路を変更できるのはリーダーだけです');
    }
  }
}

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
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
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context);
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
              label: Text(l10n.replanReviewAction),
            ),
            const SizedBox(height: 6),
            Text(
              locale.languageCode == 'ja' ? blockedReason : l10n.replanBlocked,
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
        label: Text(_loading ? l10n.replanSearching : l10n.replanReviewAction),
      ),
    );
  }

  Future<void> _openPreview() async {
    final providerContainer = ProviderScope.containerOf(context, listen: false);
    final l10n = AppLocalizations.of(context);
    final request = providerContainer.read(currentRouteReplanRequestProvider);
    final blockedReasonAtStart =
        providerContainer.read(routeReplanBlockedReasonProvider);
    if (request == null || _loading) {
      ReplanDebugLog.emit('replan_preview_tap_ignored', {
        'tripId': widget.trip.id,
        'requestNull': request == null,
        'loading': _loading,
        'blockedReason': blockedReasonAtStart,
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
      final result =
          await providerContainer.read(routeReplannerProvider).replan(request);
      final latestRequest =
          providerContainer.read(currentRouteReplanRequestProvider);
      if (latestRequest == null ||
          !sameRouteReplanRequestState(latestRequest, request)) {
        ReplanDebugLog.emit('replan_preview_search_became_stale', {
          'tripId': widget.trip.id,
          'searchedActiveStepId': request.activeStepId,
          'latestRequestNull': latestRequest == null,
          'blockedReason':
              providerContainer.read(routeReplanBlockedReasonProvider),
          'searchedAnchorPlace': request.anchor.placeName,
          'searchedAnchorAt': request.anchor.availableAt.toIso8601String(),
          'latestAnchorPlace': latestRequest?.anchor.placeName,
          'latestAnchorAt': latestRequest?.anchor.availableAt.toIso8601String(),
          'candidateCount': result.candidates.length,
        });
        throw StateError(l10n.replanSearchStateChanged);
      }
      final latestTrip = providerContainer.read(tripStreamProvider).value;
      if (latestTrip == null) {
        throw StateError(l10n.replanTripUnavailable);
      }

      final allowGroupLeaderApply = widget.allowGroupLeaderApply;
      _validateApplyPermission(
        latestTrip,
        allowGroupLeaderApply: allowGroupLeaderApply,
        l10n: l10n,
      );

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

      final comparisonController = RouteReplanComparisonController(
        trip: latestTrip,
        currentRequest: latestRequest,
        blockedReason:
            providerContainer.read(routeReplanBlockedReasonProvider),
      );

      void syncComparisonController() {
        final tripAsync = providerContainer.read(tripStreamProvider);
        final syncedTrip = tripAsync.hasValue ? tripAsync.value : null;
        if (syncedTrip == null) {
          comparisonController.sync(
            trip: comparisonController.trip,
            currentRequest: null,
            blockedReason: l10n.replanTripUnavailable,
          );
          return;
        }
        comparisonController.sync(
          trip: syncedTrip,
          currentRequest:
              providerContainer.read(currentRouteReplanRequestProvider),
          blockedReason:
              providerContainer.read(routeReplanBlockedReasonProvider),
        );
      }

      final tripSubscription = providerContainer.listen(
        tripStreamProvider,
        (_, __) => syncComparisonController(),
      );
      final requestSubscription = providerContainer.listen(
        currentRouteReplanRequestProvider,
        (_, __) => syncComparisonController(),
      );
      final blockedSubscription = providerContainer.listen(
        routeReplanBlockedReasonProvider,
        (_, __) => syncComparisonController(),
      );

      final fallbackTripId = latestTrip.id;
      bool? applied;
      try {
        applied = await showModalBottomSheet<bool>(
          context: context,
          isScrollControlled: true,
          enableDrag: false,
          backgroundColor: Colors.transparent,
          builder: (_) => RouteReplanComparisonSheet(
            preview: preview,
            controller: comparisonController,
            onRefresh: (requested) => providerContainer
                .read(routeReplannerProvider)
                .replan(requested),
            onApply: (latestPreview, candidate) => _applyCandidate(
              providerContainer: providerContainer,
              preview: latestPreview,
              selectedCandidate: candidate,
              allowGroupLeaderApply: allowGroupLeaderApply,
              l10n: l10n,
              fallbackTripId: fallbackTripId,
            ),
          ),
        );
      } finally {
        tripSubscription.close();
        requestSubscription.close();
        blockedSubscription.close();
        comparisonController.dispose();
      }

      ReplanDebugLog.emit('replan_preview_closed', {
        'tripId': latestTrip.id,
        'applied': applied == true,
        'blockedReasonAfterClose': mounted
            ? providerContainer.read(routeReplanBlockedReasonProvider)
            : null,
      });
      if (!mounted || applied != true) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            l10n.replanAppliedFrom(
              providerContainer
                      .read(currentRouteReplanRequestProvider)
                      ?.anchor
                      .placeName ??
                  preview.request.anchor.placeName,
            ),
          ),
        ),
      );
    } catch (error) {
      ReplanDebugLog.emit('replan_preview_error', {
        'tripId': widget.trip.id,
        'error': error.toString(),
        'blockedReason': mounted
            ? providerContainer.read(routeReplanBlockedReasonProvider)
            : blockedReasonAtStart,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(l10n.replanSearchFailed(error.toString()))),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  static Future<void> _applyCandidate({
    required ProviderContainer providerContainer,
    required RouteReplanPreview preview,
    required Candidate selectedCandidate,
    required bool allowGroupLeaderApply,
    required AppLocalizations l10n,
    required String fallbackTripId,
  }) async {
    var stage = 'resolve_current_request';

    try {
      final currentRequest =
          providerContainer.read(currentRouteReplanRequestProvider);
      if (currentRequest == null ||
          !sameRouteReplanRequestState(currentRequest, preview.request)) {
        ReplanDebugLog.emit('replan_apply_blocked_stale_preview', {
          'tripId': fallbackTripId,
          'selectedCandidateId': selectedCandidate.id,
          'currentRequestNull': currentRequest == null,
          'blockedReason':
              providerContainer.read(routeReplanBlockedReasonProvider),
          'previewAnchorPlace': preview.request.anchor.placeName,
          'previewAnchorAt': preview.request.anchor.availableAt.toIso8601String(),
          'currentAnchorPlace': currentRequest?.anchor.placeName,
          'currentAnchorAt': currentRequest?.anchor.availableAt.toIso8601String(),
        });
        throw StateError(l10n.replanPreviewStateChanged);
      }

      stage = 'resolve_current_trip';
      final tripAsync = providerContainer.read(tripStreamProvider);
      final currentTrip = tripAsync.value;
      if (currentTrip == null) {
        throw StateError(l10n.replanTripUnavailable);
      }
      _validateApplyPermission(
        currentTrip,
        allowGroupLeaderApply: allowGroupLeaderApply,
        l10n: l10n,
      );

      stage = 'resolve_actor';
      final actorUserId = UserService().currentUserId;
      if (actorUserId == null || actorUserId.trim().isEmpty) {
        throw StateError(l10n.replanUserUnavailable);
      }

      stage = 'build_patch';
      final patch = RouteReplanPatcher.build(
        trip: currentTrip,
        request: currentRequest,
        selectedCandidate: selectedCandidate,
      );

      stage = 'commit_firestore';
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

      stage = 'done';
      ReplanDebugLog.emit('replan_apply_success', {
        'tripId': currentTrip.id,
        'selectedCandidateId': selectedCandidate.id,
      });
    } catch (error, stackTrace) {
      ReplanDebugLog.emit('replan_apply_error', {
        'tripId': fallbackTripId,
        'selectedCandidateId': selectedCandidate.id,
        'stage': stage,
        'error': error.toString(),
      });
      if (kDebugMode) {
        debugPrint(
          '[ReplanTrace] replan_apply_error stage=$stage error=$error',
        );
        debugPrintStack(stackTrace: stackTrace);
      }
      rethrow;
    }
  }

  static void _validateApplyPermission(
    Trip trip, {
    required bool allowGroupLeaderApply,
    required AppLocalizations l10n,
  }) {
    if (trip.isSolo) return;
    if (!allowGroupLeaderApply) {
      throw StateError(l10n.groupReplanUnavailableHere);
    }

    final actorUserId = UserService().currentUserId;
    if (actorUserId == null || actorUserId.trim().isEmpty) {
      throw StateError(l10n.replanUserUnavailable);
    }
    if (actorUserId != trip.leaderId) {
      throw StateError(l10n.groupReplanLeaderOnly);
    }
  }
}

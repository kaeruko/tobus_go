import 'package:flutter/material.dart';
import '../l10n/app_localizations.dart';
import '../l10n/city_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/group_leader_active_navigation.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';
import '../providers/city_profile_provider.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/trip_provider.dart';
import '../services/trip_service.dart';
import '../widgets/active_trip_navigation_view.dart';
import '../widgets/active_trip_realtime_actions.dart';
import '../widgets/group_leader_route_replan_panel.dart';
import '../widgets/trip_navigation_status_card.dart';
import '../widgets/trip_schedule_window_card.dart';
import 'group_detail_page.dart';
import 'ride_stops_navigation.dart';

class GroupLeaderActiveTripPage extends StatelessWidget {
  final String tripId;
  final VoidCallback onOpenManagement;

  const GroupLeaderActiveTripPage({
    super.key,
    required this.tripId,
    required this.onOpenManagement,
  });

  @override
  Widget build(BuildContext context) {
    final normalizedTripId = tripId.trim();
    if (normalizedTripId.isEmpty) {
      throw ArgumentError.value(tripId, 'tripId', 'must not be empty');
    }

    return ProviderScope(
      overrides: [
        tripStreamProvider.overrideWith(
          (ref) => TripService()
              .streamTrip(normalizedTripId)
              .map<Trip?>((trip) => trip),
        ),
        memberNavProgressProvider.overrideWith(
          (ref) => MemberNavProgressNotifier(),
        ),
      ],
      child: _GroupLeaderActiveTripBody(onOpenManagement: onOpenManagement),
    );
  }
}

class _GroupLeaderActiveTripBody extends ConsumerStatefulWidget {
  final VoidCallback onOpenManagement;

  const _GroupLeaderActiveTripBody({required this.onOpenManagement});

  @override
  ConsumerState<_GroupLeaderActiveTripBody> createState() =>
      _GroupLeaderActiveTripBodyState();
}

class _GroupLeaderActiveTripBodyState
    extends ConsumerState<_GroupLeaderActiveTripBody> {
  final TripService _tripService = TripService();
  bool _primaryActionRunning = false;

  String _travelPhaseLabel(TravelPhase phase) {
    final l10n = AppLocalizations.of(context);
    return switch (phase) {
      TravelPhase.planning => l10n.travelPhasePlanning,
      TravelPhase.active => l10n.travelPhaseActive,
      TravelPhase.completed => l10n.travelPhaseCompleted,
      TravelPhase.cancelled => l10n.travelPhaseCancelled,
    };
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ref.read(memberNavProgressProvider.notifier).reset();
      ref.read(memberModeControllerProvider.notifier).initialize();
    });
  }

  @override
  Widget build(BuildContext context) {
    final tripAsync = ref.watch(tripStreamProvider);
    final uiAsync = ref.watch(memberUiStateProvider);
    final appName = localizedCityAppName(
      AppLocalizations.of(context),
      ref.watch(cityProfileProvider).city,
    );

    return tripAsync.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (error, stack) => Scaffold(
        appBar: AppBar(title: Text(appName)),
        body: Center(
          child: Text(
            AppLocalizations.of(context).groupLoadFailed(error.toString()),
          ),
        ),
      ),
      data: (trip) {
        if (trip == null) {
          return Scaffold(
            body: Center(
              child: Text(AppLocalizations.of(context).groupNotFound),
            ),
          );
        }
        if (trip.tripType != TripType.group) {
          throw StateError(
            'Group leader画面にSolo tripが渡されました: tripId=${trip.id}',
          );
        }
        if (trip.travelPhase != TravelPhase.active) {
          return Scaffold(
            appBar: AppBar(title: Text(appName)),
            body: Center(
              child: Text(
                AppLocalizations.of(
                  context,
                ).groupNotActive(_travelPhaseLabel(trip.travelPhase)),
              ),
            ),
          );
        }

        return uiAsync.when(
          loading: () =>
              const Scaffold(body: Center(child: CircularProgressIndicator())),
          error: (error, stack) => Scaffold(
            appBar: AppBar(title: Text(appName)),
            body: Center(
              child: Text(
                AppLocalizations.of(
                  context,
                ).navigationLoadFailed(error.toString()),
              ),
            ),
          ),
          data: (uiState) => _buildNavigation(trip, uiState),
        );
      },
    );
  }

  Widget _buildNavigation(Trip trip, MemberUiState uiState) {
    final appName = localizedCityAppName(
      AppLocalizations.of(context),
      ref.watch(cityProfileProvider).city,
    );
    final primaryAction = resolveGroupLeaderActivePrimaryAction(
      trip,
      resolvedEntry: uiState.resolvedEntry,
    );

    return ActiveTripNavigationView(
      navState: uiState.navState,
      tripTitle: trip.displayTitle,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: ActiveTripAppBarTitle(
          appName: appName,
          tripTitle: trip.displayTitle,
          contextLabel: AppLocalizations.of(context).groupLeaderTraveling,
        ),
        leading: IconButton(
          tooltip: AppLocalizations.of(context).groupGuideTitle,
          icon: const Icon(Icons.menu_book),
          onPressed: () => _openGroupDetail(trip),
        ),
        actions: [
          const ActiveTripRealtimeActions(),
          IconButton(
            tooltip: AppLocalizations.of(context).groupManagement,
            icon: const Icon(Icons.tune),
            onPressed: widget.onOpenManagement,
          ),
        ],
      ),
      onTapStops: () => openCurrentRideStops(
        context: context,
        trip: trip,
        currentStepId: ref.read(memberNavProgressProvider).currentStepId,
      ),
      beforeScheduleSections: const [GroupLeaderRouteReplanContent()],
      scheduleSection: TripScheduleWindowCard(
        title: AppLocalizations.of(context).groupTodaySchedule,
        resolvedEntry: uiState.resolvedEntry,
        entries: uiState.windowEntries,
        completedCount: uiState.completedCount,
        activeLabel: uiState.activeLabel,
        counterLabelBuilder: (completedCount, totalCount) =>
            AppLocalizations.of(context).groupCompletedCount(completedCount),
        appearance: TripScheduleWindowAppearance.boxedRows,
        activeDetail: TripNavigationInlineStatus(
          navState: uiState.navState,
          onTapStops: () => openCurrentRideStops(
            context: context,
            trip: trip,
            currentStepId: ref.read(memberNavProgressProvider).currentStepId,
          ),
        ),
        emptyLabel: AppLocalizations.of(context).groupScheduleAllCompleted,
        onTapEntry: (entry) {
          if (entry.itemKind != ScheduleEntryKind.ride) return;
          openRideStops(context: context, trip: trip, entry: entry);
        },
      ),
      afterScheduleSections: [
        OutlinedButton.icon(
          onPressed: widget.onOpenManagement,
          icon: const Icon(Icons.tune),
          label: Text(AppLocalizations.of(context).groupOpenManagement),
        ),
      ],
      bottomNavigationBar: primaryAction == null
          ? null
          : _GroupLeaderPrimaryActionBar(
              action: primaryAction,
              running: _primaryActionRunning,
              onPressed: () => _runPrimaryAction(trip, primaryAction),
            ),
    );
  }

  void _openGroupDetail(Trip trip) {
    Navigator.of(
      context,
      rootNavigator: true,
    ).push(MaterialPageRoute(builder: (_) => GroupDetailPage(trip: trip)));
  }

  Future<void> _runPrimaryAction(
    Trip trip,
    GroupLeaderActivePrimaryAction action,
  ) async {
    if (_primaryActionRunning) return;

    switch (action) {
      case GroupLeaderActivePrimaryAction.arriveAtGoal:
        await _arriveAtGoal(trip);
      case GroupLeaderActivePrimaryAction.completeTrip:
        await _completeTrip(trip);
    }
  }

  Future<void> _arriveAtGoal(Trip trip) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(AppLocalizations.of(context).groupArrivedTitle),
        content: Text(AppLocalizations.of(context).groupArrivedQuestion),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(AppLocalizations.of(context).groupNo),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(AppLocalizations.of(context).groupYes),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _primaryActionRunning = true);
    try {
      await _tripService.updateCompletedLegIndex(trip.id, 0);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(AppLocalizations.of(context).groupArrivalRecorded),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            AppLocalizations.of(context).groupUpdateFailed(error.toString()),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _primaryActionRunning = false);
    }
  }

  Future<void> _completeTrip(Trip trip) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(AppLocalizations.of(context).groupEndTitle),
        content: Text(AppLocalizations.of(context).groupEndQuestion),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(AppLocalizations.of(context).cancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(AppLocalizations.of(context).groupEndAction),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _primaryActionRunning = true);
    try {
      await _tripService.completeTrip(trip.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(AppLocalizations.of(context).groupEnded)),
      );
      Navigator.of(context).pop();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            AppLocalizations.of(context).groupEndFailed(error.toString()),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _primaryActionRunning = false);
    }
  }
}

class _GroupLeaderPrimaryActionBar extends StatelessWidget {
  final GroupLeaderActivePrimaryAction action;
  final bool running;
  final VoidCallback onPressed;

  const _GroupLeaderPrimaryActionBar({
    required this.action,
    required this.running,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final isOutbound = action == GroupLeaderActivePrimaryAction.arriveAtGoal;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: FilledButton.icon(
          onPressed: running ? null : onPressed,
          style: FilledButton.styleFrom(
            backgroundColor: isOutbound
                ? Colors.green.shade600
                : Colors.grey.shade700,
            foregroundColor: Colors.white,
          ),
          icon: running
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Icon(isOutbound ? Icons.flag : Icons.check_circle),
          label: Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              running
                  ? AppLocalizations.of(context).groupUpdating
                  : isOutbound
                  ? AppLocalizations.of(context).groupArriveAndReturn
                  : AppLocalizations.of(context).groupEndTrip,
            ),
          ),
        ),
      ),
    );
  }
}

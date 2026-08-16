import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/group_leader_active_navigation.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/trip_provider.dart';
import '../services/trip_service.dart';
import '../widgets/active_trip_navigation_view.dart';
import '../widgets/active_trip_realtime_actions.dart';
import '../widgets/group_leader_route_replan_panel.dart';
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
      child: _GroupLeaderActiveTripBody(
        onOpenManagement: onOpenManagement,
      ),
    );
  }
}

class _GroupLeaderActiveTripBody extends ConsumerStatefulWidget {
  final VoidCallback onOpenManagement;

  const _GroupLeaderActiveTripBody({
    required this.onOpenManagement,
  });

  @override
  ConsumerState<_GroupLeaderActiveTripBody> createState() =>
      _GroupLeaderActiveTripBodyState();
}

class _GroupLeaderActiveTripBodyState
    extends ConsumerState<_GroupLeaderActiveTripBody> {
  final TripService _tripService = TripService();
  bool _primaryActionRunning = false;

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

    return tripAsync.when(
      loading: () =>
          const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (error, stack) => Scaffold(
        appBar: AppBar(title: const Text('移動中')),
        body: Center(child: Text('おでかけを読み込めませんでした: $error')),
      ),
      data: (trip) {
        if (trip == null) {
          return const Scaffold(body: Center(child: Text('おでかけが見つかりません')));
        }
        if (trip.tripType != TripType.group) {
          throw StateError('Group leader画面にSolo tripが渡されました: tripId=${trip.id}');
        }
        if (trip.travelPhase != TravelPhase.active) {
          return Scaffold(
            appBar: AppBar(title: const Text('移動中')),
            body: Center(
              child: Text('移動中ではありません: ${trip.travelPhase.name}'),
            ),
          );
        }

        return uiAsync.when(
          loading: () =>
              const Scaffold(body: Center(child: CircularProgressIndicator())),
          error: (error, stack) => Scaffold(
            appBar: AppBar(title: const Text('移動中')),
            body: Center(child: Text('ナビを表示できませんでした: $error')),
          ),
          data: (uiState) => _buildNavigation(trip, uiState),
        );
      },
    );
  }

  Widget _buildNavigation(Trip trip, MemberUiState uiState) {
    final primaryAction = resolveGroupLeaderActivePrimaryAction(trip);

    return ActiveTripNavigationView(
      navState: uiState.navState,
      tripTitle: trip.displayTitle,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'リーダー移動中',
              style: TextStyle(fontSize: 13, color: Colors.black54),
            ),
            Text(
              trip.displayTitle,
              style: const TextStyle(
                color: Colors.black,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
        leading: IconButton(
          tooltip: 'おでかけのしおり',
          icon: const Icon(Icons.menu_book),
          onPressed: () => _openGroupDetail(trip),
        ),
        actions: [
          const ActiveTripRealtimeActions(),
          IconButton(
            tooltip: 'おでかけ管理',
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
      beforeScheduleSections: const [
        GroupLeaderRouteReplanContent(),
      ],
      scheduleSection: TripScheduleWindowCard(
        title: '今日の予定',
        resolvedEntry: uiState.resolvedEntry,
        entries: uiState.windowEntries,
        completedCount: uiState.completedCount,
        activeLabel: uiState.activeLabel,
        counterLabelBuilder: (completedCount, totalCount) =>
            '完了 $completedCount 件',
        appearance: TripScheduleWindowAppearance.boxedRows,
        emptyLabel: 'すべての予定を完了しました。',
        onTapEntry: (entry) {
          if (entry.itemKind != ScheduleEntryKind.ride) return;
          openRideStops(context: context, trip: trip, entry: entry);
        },
      ),
      afterScheduleSections: [
        OutlinedButton.icon(
          onPressed: widget.onOpenManagement,
          icon: const Icon(Icons.tune),
          label: const Text('おでかけ管理を開く'),
        ),
      ],
      bottomNavigationBar: _GroupLeaderPrimaryActionBar(
        action: primaryAction,
        running: _primaryActionRunning,
        onPressed: () => _runPrimaryAction(trip, primaryAction),
      ),
    );
  }

  void _openGroupDetail(Trip trip) {
    Navigator.of(context, rootNavigator: true).push(
      MaterialPageRoute(builder: (_) => GroupDetailPage(trip: trip)),
    );
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
        title: const Text('目的地に到着'),
        content: const Text(
          '往路（行き）が完了しましたか？\n'
          '「はい」を押すと、帰りのナビゲーションが準備されます。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('いいえ'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('はい'),
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
        const SnackBar(content: Text('到着を記録しました。帰りもお気をつけて！')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('更新に失敗しました: $error')),
      );
    } finally {
      if (mounted) setState(() => _primaryActionRunning = false);
    }
  }

  Future<void> _completeTrip(Trip trip) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('おでかけ終了'),
        content: const Text('本当に終了しますか？\nメンバーの画面も「終了」に切り替わります。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('キャンセル'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('終了する'),
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
        const SnackBar(content: Text('おでかけを終了しました')),
      );
      Navigator.of(context).pop();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('終了処理に失敗しました: $error')),
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
                  ? '更新中…'
                  : isOutbound
                      ? '目的地に到着（帰り支度）'
                      : 'おでかけを終了する',
            ),
          ),
        ),
      ),
    );
  }
}

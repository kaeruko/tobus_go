import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../logic/route_replan_presentation.dart';
import '../logic/solo_trip_lifecycle.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';
import '../providers/delay_impact_provider.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/trip_provider.dart';
import '../services/trip_service.dart';
import '../widgets/active_trip_navigation_view.dart';
import '../widgets/active_trip_realtime_actions.dart';
import '../widgets/delay_recovery_card.dart';
import '../widgets/route_replan_preview_button.dart';
import '../widgets/trip_schedule_window_card.dart';
import 'ride_stops_navigation.dart';
import 'solo_trip_detail_page.dart';

class SoloTripScreen extends StatelessWidget {
  final String tripId;

  const SoloTripScreen({super.key, required this.tripId});

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      overrides: [
        tripStreamProvider.overrideWith(
          (ref) => TripService().streamTrip(tripId).map<Trip?>((trip) => trip),
        ),
      ],
      child: SoloTripView(tripId: tripId),
    );
  }
}

class SoloTripView extends ConsumerStatefulWidget {
  final String tripId;

  const SoloTripView({
    super.key,
    required this.tripId,
  });

  @override
  ConsumerState<SoloTripView> createState() => _SoloTripViewState();
}

class _SoloTripViewState extends ConsumerState<SoloTripView> {
  final TripService _tripService = TripService();
  bool _completionRequested = false;
  bool _completionFailed = false;
  bool _cancelling = false;
  MemberUiState? _arrivalUiSnapshot;

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

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.dark.copyWith(
        statusBarColor: Colors.transparent,
        systemNavigationBarColor: Colors.white,
        systemNavigationBarIconBrightness: Brightness.dark,
      ),
      child: tripAsync.when(
        loading: () =>
            const Scaffold(body: Center(child: CircularProgressIndicator())),
        error: (error, stack) => Scaffold(
          appBar: AppBar(
            systemOverlayStyle: SystemUiOverlayStyle.dark,
            title: const Text('移動'),
          ),
          body: Center(child: Text('移動を読み込めませんでした: $error')),
        ),
        data: (trip) {
          if (trip == null) {
            return const Scaffold(body: Center(child: Text('移動が見つかりません')));
          }
          if (trip.travelPhase == TravelPhase.completed) {
            final arrivalUiSnapshot = _arrivalUiSnapshot;
            if (arrivalUiSnapshot != null) {
              return _buildTripScaffold(
                trip: trip,
                uiState: arrivalUiSnapshot,
                terminalArrival: true,
                completed: true,
              );
            }
            return _buildCompleted();
          }
          if (trip.travelPhase == TravelPhase.cancelled) {
            return _buildCancelled();
          }

          return uiAsync.when(
            loading: () => const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            ),
            error: (error, stack) => Scaffold(
              appBar: AppBar(
                systemOverlayStyle: SystemUiOverlayStyle.dark,
                title: const Text('移動'),
              ),
              body: Center(child: Text('ナビを表示できませんでした: $error')),
            ),
            data: (uiState) {
              final terminalArrival = shouldAutoCompleteSoloTrip(
                trip: trip,
                resolvedEntry: uiState.resolvedEntry,
              );
              if (terminalArrival) {
                _requestAutoCompletion(trip, uiState);
              }

              return _buildTripScaffold(
                trip: trip,
                uiState: uiState,
                terminalArrival: terminalArrival,
                completed: false,
              );
            },
          );
        },
      ),
    );
  }

  Widget _buildTripScaffold({
    required Trip trip,
    required MemberUiState uiState,
    required bool terminalArrival,
    required bool completed,
  }) {
    final delayResolution = ref.watch(resolvedDelayImpactProvider);
    final delayImpact = delayResolution.impact;
    final presentation = RouteReplanPresentation.fromDelayImpact(delayImpact);
    final showDelayWarning =
        !completed && !terminalArrival && presentation.showWarning;
    final showStandaloneReplan =
        !completed &&
        !terminalArrival &&
        !showDelayWarning &&
        presentation.showAction;
    final realtimeDiagnostic = delayResolution.nextRideRealtimeError == null
        ? null
        : '次便のRealtime確認に失敗したため、予定時刻で判定しています: '
            '${delayResolution.nextRideRealtimeError}';

    final beforeScheduleSections = <Widget>[];
    if (showDelayWarning) {
      beforeScheduleSections.add(
        DelayRecoveryCard(
          impact: delayImpact!,
          nextRideRealtime: delayResolution.nextRideRealtime,
          scheduledNextDepartureAt: delayResolution.scheduledNextDepartureAt,
          realtimeDiagnostic: realtimeDiagnostic,
          helperText: '予定はまだ変更していません。新しい経路を確認してから選べます。',
          action: RouteReplanPreviewButton(trip: trip),
        ),
      );
    } else if (showStandaloneReplan) {
      beforeScheduleSections.add(RouteReplanPreviewButton(trip: trip));
    }

    return ActiveTripNavigationView(
      navState: uiState.navState,
      tripTitle: trip.displayTitle,
      appBar: AppBar(
        systemOverlayStyle: SystemUiOverlayStyle.dark,
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: Text(
          trip.displayTitle,
          style: const TextStyle(
            color: Colors.black,
            fontWeight: FontWeight.bold,
          ),
        ),
        actions: [
          if (!completed) const ActiveTripRealtimeActions(),
        ],
      ),
      onTapStops: () => openCurrentRideStops(
        context: context,
        trip: trip,
        currentStepId: ref.read(memberNavProgressProvider).currentStepId,
      ),
      beforeScheduleSections: beforeScheduleSections,
      scheduleSection: TripScheduleWindowCard(
        title: '今回の経路',
        resolvedEntry: uiState.resolvedEntry,
        entries: uiState.windowEntries,
        completedCount: completed
            ? trip.schedule.length
            : uiState.completedCount,
        totalCount: trip.schedule.length,
        activeLabel: uiState.activeLabel,
        counterLabelBuilder: (completedCount, totalCount) {
          if (totalCount == null) {
            throw StateError('Soloの予定ウィンドウにtotalCountがありません');
          }
          return '$completedCount / $totalCount ステップ';
        },
        appearance: TripScheduleWindowAppearance.listTiles,
        onTapEntry: (entry) {
          if (entry.itemKind != ScheduleEntryKind.ride) return;
          openRideStops(context: context, trip: trip, entry: entry);
        },
      ),
      afterScheduleSections: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => SoloTripDetailPage(trip: trip),
                ),
              ),
              icon: const Icon(Icons.route),
              label: const Text('経路全体を見る'),
            ),
            const SizedBox(height: 8),
            if (completed)
              FilledButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('閉じる'),
              )
            else if (terminalArrival)
              if (_completionFailed)
                TextButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('閉じる'),
                )
              else
                const SizedBox.shrink()
            else
              TextButton(
                onPressed: _cancelling ? null : () => _cancelTrip(trip),
                child: Text(
                  _cancelling ? '終了処理中…' : '移動を中止する',
                ),
              ),
          ],
        ),
      ],
    );
  }

  void _requestAutoCompletion(Trip trip, MemberUiState uiState) {
    if (_completionRequested || _completionFailed) return;

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || _completionRequested || _completionFailed) return;

      setState(() {
        _arrivalUiSnapshot = uiState;
        _completionRequested = true;
      });

      try {
        await _tripService.completeTrip(trip.id);
      } catch (error) {
        if (!mounted) return;
        setState(() {
          _completionRequested = false;
          _completionFailed = true;
        });
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('到着の保存に失敗しました: $error')));
      }
    });
  }

  Future<void> _cancelTrip(Trip trip) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('移動を中止しますか？'),
        content: const Text('この移動は中止として履歴に残ります。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('戻る'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('中止する'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _cancelling = true);
    try {
      await _tripService.cancelTrip(trip.id);
    } catch (error) {
      if (mounted) {
        setState(() => _cancelling = false);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('移動を中止できませんでした: $error')));
      }
    }
  }

  Widget _buildCompleted() {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text(
                  '到着しました',
                  style: TextStyle(fontSize: 32, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 28),
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('閉じる'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCancelled() {
    return Scaffold(
      body: Center(
        child: FilledButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('閉じる'),
        ),
      ),
    );
  }
}

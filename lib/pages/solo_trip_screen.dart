import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../logic/solo_trip_lifecycle.dart';
import '../logic/trip_navigator.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../providers/member_mode_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/trip_provider.dart';
import '../services/bus_location_source.dart';
import '../services/trip_service.dart';
import 'solo_trip_detail_page.dart';
import 'segment_stops_page.dart';

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
    return Scaffold(
      backgroundColor: uiState.navState.color,
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
          if (!completed && ref.read(busLocationSourceProvider) is FakeBusLocationSource)
            IconButton(
              tooltip: 'Fakeバスを次の停留所へ',
              icon: const Icon(Icons.skip_next),
              onPressed: _advanceFakeBus,
            ),
          if (!completed)
            IconButton(
              tooltip: '現在地を更新',
              icon: const Icon(Icons.refresh),
              onPressed: () =>
                  ref.read(memberModeControllerProvider.notifier).pollNow(),
            ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            _SoloStatusCard(
              navState: uiState.navState,
              tripTitle: trip.displayTitle,
              onTapStops: () => _openStops(trip),
            ),
            const SizedBox(height: 14),
            _SoloScheduleCard(
              resolvedEntry: uiState.resolvedEntry,
              entries: uiState.windowEntries,
              completedCount: completed
                  ? trip.schedule.length
                  : uiState.completedCount,
              totalStepCount: trip.schedule.length,
              activeLabel: uiState.activeLabel,
              onTapEntry: (entry) {
                final stepId = entry.routeStepId;
                if (stepId == null) return;

                final step = trip.stepsById[stepId];
                if (step == null) {
                  throw StateError(
                    'ScheduleEntry が存在しない routeStepId を参照しています: $stepId',
                  );
                }

                if (!step.isRide || step.stops.isEmpty) return;

                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => SegmentStopsPage(segment: step),
                  ),
                );
              },
            ),
            const SizedBox(height: 14),
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
      ),
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

  Future<void> _advanceFakeBus() async {
    final source = ref.read(busLocationSourceProvider);
    if (source is! FakeBusLocationSource) return;
    source.advance();
    await ref.read(memberModeControllerProvider.notifier).pollNow();
  }

  void _openStops(Trip trip) {
    final stepId = ref.read(memberNavProgressProvider).currentStepId;
    final step = stepId == null ? null : trip.stepsById[stepId];
    if (step == null || !step.isRide || step.stops.isEmpty) return;
    Navigator.of(
      context,
    ).push(MaterialPageRoute(builder: (_) => _SoloStopsPage(step: step)));
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

class _SoloStatusCard extends StatelessWidget {
  final NavigationState navState;
  final String tripTitle;
  final VoidCallback onTapStops;

  const _SoloStatusCard({
    required this.navState,
    required this.tripTitle,
    required this.onTapStops,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 4,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                Chip(
                  avatar: const Icon(Icons.location_on, size: 18),
                  label: Text(navState.statusLabel),
                ),
                Chip(
                  avatar: const Icon(Icons.route, size: 18),
                  label: Text(tripTitle),
                ),
              ],
            ),
            const SizedBox(height: 18),
            Text(
              navState.mainText,
              style: const TextStyle(fontSize: 42, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Text(
              navState.subText,
              style: const TextStyle(fontSize: 21, fontWeight: FontWeight.bold),
            ),
            if (navState.noticeText != null) ...[
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.amber.shade100,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.amber.shade700),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.sync, size: 22),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        navState.noticeText!,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (navState.remainingStops != null ||
                (navState.nextStopName?.isNotEmpty ?? false)) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                children: [
                  if (navState.remainingStops != null)
                    ActionChip(
                      avatar: const Icon(Icons.directions_bus, size: 18),
                      label: Text('のこり ${navState.remainingStops} 回停車'),
                      onPressed: onTapStops,
                    ),
                  if (navState.nextStopName?.isNotEmpty ?? false)
                    Chip(label: Text('次: ${navState.nextStopName}')),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SoloScheduleCard extends StatelessWidget {
  final ScheduleEntry? resolvedEntry;
  final List<ScheduleEntry> entries;
  final int completedCount;
  final int totalStepCount;
  final String activeLabel;
  final ValueChanged<ScheduleEntry> onTapEntry;

  const _SoloScheduleCard({
    required this.resolvedEntry,
    required this.entries,
    required this.completedCount,
    required this.totalStepCount,
    required this.activeLabel,
    required this.onTapEntry,
  });

  @override
  Widget build(BuildContext context) {
    if (completedCount < 0 ||
        totalStepCount < 0 ||
        completedCount > totalStepCount) {
      throw StateError(
        '経路ステップ数が不正です: completed=$completedCount, total=$totalStepCount',
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  '今回の経路',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                ),
                Text('$completedCount / $totalStepCount ステップ'),
              ],
            ),
            const SizedBox(height: 10),
            ...entries.map((entry) {
              final isActive = resolvedEntry?.id == entry.id;
              return ListTile(
                contentPadding: EdgeInsets.zero,
                onTap: entry.routeStepId == null
                    ? null
                    : () => onTapEntry(entry),
                leading: Icon(
                  entry.itemKind == ScheduleEntryKind.walk
                      ? Icons.directions_walk
                      : entry.itemKind == ScheduleEntryKind.goal
                      ? Icons.flag
                      : Icons.directions_bus,
                ),
                title: Text(entry.label),
                subtitle: isActive ? Text(activeLabel) : null,
                trailing: Text(
                  '${entry.plannedAt.hour.toString().padLeft(2, '0')}:${entry.plannedAt.minute.toString().padLeft(2, '0')}',
                ),
                tileColor: isActive ? Colors.green.shade50 : null,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              );
            }),
          ],
        ),
      ),
    );
  }
}

class _SoloStopsPage extends StatelessWidget {
  final StepSeg step;

  const _SoloStopsPage({required this.step});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        systemOverlayStyle: SystemUiOverlayStyle.dark,
        title: Text(step.title),
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: step.stops.length,
        itemBuilder: (context, index) {
          final stop = step.stops[index];
          final isFirst = index == 0;
          final isLast = index == step.stops.length - 1;
          return ListTile(
            leading: Icon(
              isFirst || isLast ? Icons.circle : Icons.circle_outlined,
              color: Colors.green,
            ),
            title: Text(
              stop.name,
              style: TextStyle(
                fontWeight: isFirst || isLast
                    ? FontWeight.bold
                    : FontWeight.normal,
              ),
            ),
            subtitle: isFirst
                ? const Text('乗車')
                : isLast
                ? const Text('降車')
                : null,
          );
        },
      ),
    );
  }
}

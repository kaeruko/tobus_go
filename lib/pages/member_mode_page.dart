import 'dart:async';
import 'dart:ui';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../core/app_clock.dart';
import '../models/trip_models.dart';

import '../services/trip_service.dart'; // For sendSOS
import '../models/group_models.dart';
import 'group_detail_page.dart';
import '../logic/trip_navigator.dart'; 
import '../core/api_client.dart'; // Added
import '../logic/trip_coordinator.dart'; // Added
import '../logic/schedule_resolver.dart'; 
import 'settings_page.dart'; // Added for debug link
import 'route_detail_page.dart';
import '../providers/app_session_provider.dart';
import '../providers/trip_provider.dart';
import '../providers/location_provider.dart';
import '../providers/member_nav_progress_provider.dart';
import '../providers/minute_ticker_provider.dart';

class MemberModePage extends ConsumerStatefulWidget {
  const MemberModePage({super.key});

  @override
  ConsumerState<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends ConsumerState<MemberModePage> {
  // Service for SOS only, data is via provider
  final _tripService = TripService();
  // ignore: unused_field
  final TripNavigator _navigator = TripNavigator(); 
  Timer? _realtimeTimer; 
  int? _lastApiStopIndex; 
  String? _lastRealtimeBusId; // Added for delay detection 

  LatLng? _currentPositionForNav() {
    final override = ref.read(locationOverrideProvider);
    if (override != null) {
      return override;
    }

    final posAsync = ref.read(locationStreamProvider);
    if (posAsync.hasValue) {
      final pos = posAsync.value!;
      return LatLng(pos.latitude, pos.longitude);
    }

    return null;
  }

  void _refreshProgressWithTrip(Trip trip) {
    final current = _currentPositionForNav();
    if (current != null) {
      ref.read(memberNavProgressProvider.notifier).updateProgress(trip, current);
    }
  }

  @override
  void initState() {
    super.initState();
    
    // 30秒ごとにバスロケ情報を確認
    _realtimeTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      _pollRealtimeData();
    });

    // Reset any previous navigation state safely
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        ref.read(memberNavProgressProvider.notifier).reset();
      }
    });

    // Listeners moved to initState (manual management)
    ref.listenManual(tripStreamProvider, (prev, next) {
      next.whenData((trip) {
        if (trip != null) {
          _refreshProgressWithTrip(trip);
        }
      });
    });

    ref.listenManual(locationStreamProvider, (prev, next) {
      if (ref.read(locationOverrideProvider) != null) {
        return;
      }
      next.whenData((pos) {
        final tripAsync = ref.read(tripStreamProvider);
        if (!tripAsync.hasValue || tripAsync.value == null) return;

        final trip = tripAsync.value!;
        final currentPos = LatLng(pos.latitude, pos.longitude);
        final nav = ref.read(memberNavProgressProvider);
        
        // TripNavigatorを直接呼び出してGPS補正を適用
        final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
        final routeState = RouteState(
          steps: allSteps,
          currentStepIndex: nav.currentStepIndex,
          nextStopIndex: nav.nextStopIndex,
          isMoving: false,
        );

        TripNavigator.updateRouteOnly(
           routeState,
           currentPos,
           forceStopIndex: _lastApiStopIndex, // ★APIから取れたIndexがあれば強制適用
        );

        // 補正後のインデックスをnavProgressに書き戻す
        ref.read(memberNavProgressProvider.notifier).setIndices(
          stepIndex: routeState.currentStepIndex,
          stopIndex: routeState.nextStopIndex,
        );
      });
    });

    ref.listenManual(locationOverrideProvider, (previous, next) {
      final tripAsync = ref.read(tripStreamProvider);
      if (tripAsync.hasValue && tripAsync.value != null) {
        _refreshProgressWithTrip(tripAsync.value!);
      }
    });
  }

  @override
  void dispose() {
    _realtimeTimer?.cancel();
    super.dispose();
  }

  Future<void> _pollRealtimeData() async {
    final navState = ref.read(memberNavProgressProvider);
    
    final tripAsync = ref.read(tripStreamProvider);
    if (!tripAsync.hasValue || tripAsync.value == null) return;
    final trip = tripAsync.value!;

    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    
    // Check bounds
    if (navState.currentStepIndex < 0 || navState.currentStepIndex >= allSteps.length) return;

    // "isMoving" check: effectively if we are past the start (index > 0) or if we want to confirm active navigation
    // But polling implies we are active. We can check if index > 0.
    if (navState.currentStepIndex == 0) return; 

    final currentStep = allSteps[navState.currentStepIndex];
    
    // バス/電車に乗っている時だけAPIを確認する
    if (currentStep.isRide && currentStep.routeId != null) {
      try {
        final result = await ApiClient.fetchBusLocation(
          routeId: currentStep.routeId!,
          tripId: currentStep.tripId, 
        );
        final fromPoleId = result['odpt:fromBusstopPole'];
        
        if (fromPoleId != null) {
          // Keep API ID for coordinator check
          setState(() {
             _lastRealtimeBusId = fromPoleId;
          });

          final index = currentStep.stops.indexWhere((s) => s.stopId == fromPoleId);
          if (index != -1) {
            setState(() {
              _lastApiStopIndex = index;
            });
            debugPrint("API Update: Bus is at index $index (${currentStep.stops[index].name}) / ID: $fromPoleId");
          }
        }
      } catch (e) {
        // print("Realtime poll failed: $e");
      }
    } else {
      _lastApiStopIndex = null; // Walk中はリセット
    }
  }

  Future<void> _leaveGroup() async {
    await ref.read(appSessionProvider.notifier).leaveMemberMode();
    // RootGate will handle the switch
  }

  void _openGroupDetail(Trip trip) {
    Navigator.of(context, rootNavigator: true).push(
      CupertinoPageRoute(
        builder: (_) => GroupDetailPage(trip: trip),
      ),
    );
  }

  Future<void> _sendSOS(String tripId) async {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('SOS'),
        content: const Text('引率者に通知を送りますか?'),
        actions: [
          CupertinoDialogAction(
            child: const Text('キャンセル'),
            onPressed: () => Navigator.pop(ctx),
          ),
          CupertinoDialogAction(
            isDestructiveAction: true,
            onPressed: () async {
              Navigator.pop(ctx);
              await _tripService.sendSOS(tripId);

              if (mounted) {
                showCupertinoDialog(
                  context: context,
                  builder: (ctx2) => CupertinoAlertDialog(
                    content: const Text('引率者に通知しました!'),
                    actions: [
                      CupertinoDialogAction(
                        child: const Text('OK'),
                        onPressed: () => Navigator.pop(ctx2),
                      ),
                    ],
                  ),
                );
              }
            },
            child: const Text('通知する'),
          ),
        ],
      ),
    );
  }

  List<ScheduleEntry> _sortedSchedule(List<ScheduleEntry> entries) {
    final copy = [...entries];
    sortScheduleEntries(copy);
    return copy;
  }

  @override
  Widget build(BuildContext context) {
    final tripAsync = ref.watch(tripStreamProvider);
    final locationAsync = ref.watch(locationStreamProvider);
    final manualOverride = ref.watch(locationOverrideProvider);
    final navProgress = ref.watch(memberNavProgressProvider);
    
    // 1分ごとに更新される現在時刻を取得（スケジュール自動更新用）
    final nowTick = ref.watch(minuteTickerProvider);
    final now = nowTick.value ?? appClock.now();

    return tripAsync.when(
      loading: () => const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (err, stack) => Scaffold(
        appBar: const CupertinoNavigationBar(middle: Text('エラー')),
        body: Center(child: Text('エラー: $err')),
      ),
      data: (trip) {
        if (trip == null) {
          return const Scaffold(
            appBar: CupertinoNavigationBar(middle: Text('エラー')),
            body: Center(child: Text('グループが見つかりません')),
          );
        }

        if (trip.status == TripStatus.cancelled ||
            trip.status == TripStatus.completed) {
          Future.microtask(() async {
            if (mounted) {
              await ref.read(appSessionProvider.notifier).leaveMemberMode();
            }
          });

          final message = trip.status == TripStatus.cancelled
              ? 'ホストによりグループが解散されました。'
              : 'このグループは終了しました。';

          return Scaffold(
            appBar: AppBar(title: const Text('お知らせ'), backgroundColor: Colors.red),
            body: Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(message, style: const TextStyle(fontSize: 18)),
                  const SizedBox(height: 20),
                  ElevatedButton(
                    onPressed: _leaveGroup,
                    child: const Text('OK'),
                  ),
                ],
              ),
            ),
          );
        }

        // final schedule = _sortedSchedule(trip.schedule); // Unused
        // Use nullable LatLng, do NOT fallback to Tokyo Station default
        final LatLng? currentPos = manualOverride ??
            (locationAsync.value != null
                ? LatLng(locationAsync.value!.latitude, locationAsync.value!.longitude)
                : null); 

        // 1. Resolve Route Navigation (Pure Route State) - 先に実行してGPS補正を適用
        final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
        for (var i = 0; i < allSteps.length; i++) {
          final s = allSteps[i];
          debugPrint(
            "[StepDump] i=$i kind=${s.kind} title=${s.title} from=${s.from} to=${s.to} place=${s.place} stops=${s.stops.length} firstStop=${s.stops.isNotEmpty ? s.stops.first.name : '-'}"
          );
        }


        final routeState = RouteState(
          steps: allSteps,
          currentStepIndex: navProgress.currentStepIndex,
          nextStopIndex: navProgress.nextStopIndex,
          isMoving: false,
        );
        
        if (currentPos != null) {
          TripNavigator.updateRouteOnly(
            routeState,
            currentPos,
            forceStopIndex: _lastApiStopIndex, // ★APIから取れたIndexがあれば強制適用
          );
        }

        // 2. Resolve Schedule (Window + Active) - routeStateの補正後インデックスを使用
        final scheduleResolved = ScheduleResolver.resolve(
          scheduleSorted: _sortedSchedule(trip.schedule),
          now: now,
          trip: trip,
          currentStepIndex: routeState.currentStepIndex,
          nextStopIndex: routeState.nextStopIndex,
        );

        // 3. Coordinate Final Display State
        final navState = TripCoordinator.buildMemberNavigationState(
          trip: trip,
          scheduleState: scheduleResolved,
          routeState: routeState,
          now: now,
          realtimeBusLocationId: _lastRealtimeBusId,
        );

        // Prepare data for UI list
        final activeEntry = scheduleResolved.activeEntry;
        // Use the window provided by resolver instead of manual skip/take
        final upcomingEntries = scheduleResolved.window; 
        // Note: The UI widget _SchedulePeek might check 'upcoming' but here we pass the 'window' 
        // which includes prev/active/next. We might need to adjust _SchedulePeek or passing upcomingEntries.
        // User request said: "Simple screen is Fixed Window (Prev 1 + Now 1 + Next 3)".
        // So we should pass `scheduleResolved.window` to the list widget.
        final completedCount = scheduleResolved.completedCount;
        final activeLabel = scheduleResolved.activeLabel;

        // タイトル生成ロジック (LeaderModePageと同期)
        final displayTitle = trip.displayTitle;

        return Scaffold(
          backgroundColor: navState.color,
          appBar: AppBar(
            backgroundColor: navState.color,
            elevation: 0,
            centerTitle: false,
            titleSpacing: 0,
            title: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('おでかけモード', style: TextStyle(color: Colors.black54, fontSize: 14)),
                Text(
                  displayTitle,
                  style: const TextStyle(
                    color: Colors.black,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            leading: IconButton(
              icon: const Icon(CupertinoIcons.doc_text, color: Colors.black87),
              onPressed: () => _openGroupDetail(trip),
              tooltip: 'たびのしおり',
            ),
            actions: [
              IconButton(
                icon: const Icon(Icons.refresh),
                onPressed: () => _refreshProgressWithTrip(trip),
                tooltip: '手動更新',
              ),
              IconButton(
                icon: const Icon(Icons.settings),
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (context) => const SettingsPage(),
                    ),
                  );
                },
              ),
              TextButton(
                onPressed: () => showCupertinoDialog(
                  context: context,
                  builder: (ctx) => CupertinoAlertDialog(
                    title: const Text('モード終了'),
                    content: const Text('通常モードに戻りますか?'),
                    actions: [
                      CupertinoDialogAction(
                        child: const Text('いいえ'),
                        onPressed: () => Navigator.pop(ctx),
                      ),
                      CupertinoDialogAction(
                        isDestructiveAction: true,
                        child: const Text('はい'),
                        onPressed: () {
                          Navigator.pop(ctx);
                          _leaveGroup();
                        },
                      ),
                    ],
                  ),
                ),
                child: const Text('終了', style: TextStyle(color: CupertinoColors.destructiveRed)),
              ),
            ],
          ),
          body: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _CurrentStatusCard(
                    navState: navState,
                    tripTitle: displayTitle,
                    locationAsync: locationAsync,
                    trip: trip,
                  ),
                  const SizedBox(height: 14),
                  _SchedulePeek(
                    activeEntry: activeEntry,
                    windowEntries: upcomingEntries, // Now holding valid window list
                    completedCount: completedCount,
                    activeLabel: activeLabel,
                  ),
                  const SizedBox(height: 14),
                  _HelperNotice(onHelp: () => _sendSOS(trip.id)),
                  const SizedBox(height: 80),
                ],
              ),
            ),
          ),
          bottomNavigationBar: _MemberActionBar(
            onHelp: () => _sendSOS(trip.id),
            onOpenDetail: () => _openGroupDetail(trip),
            onExit: _leaveGroup,
          ),
        );
      },
    );
  }
}

class _CurrentStatusCard extends StatelessWidget {
  final NavigationState navState;
  final String tripTitle;
  final AsyncValue<Position> locationAsync;
  final Trip trip;

  const _CurrentStatusCard({
    required this.navState,
    required this.tripTitle,
    required this.locationAsync,
    required this.trip,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.92),
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [
          BoxShadow(
            color: Color(0x22000000),
            blurRadius: 14,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _StatusChip(
                label: navState.statusLabel,
                icon: CupertinoIcons.location_solid,
                color: Colors.black87,
              ),
              _StatusChip(
                label: '旅程: $tripTitle',
                icon: CupertinoIcons.flag,
                color: Colors.black54,
              ),
            ],
          ),
          const SizedBox(height: 12),
          const Align(
            alignment: Alignment.centerRight,
            child: _LiveClock(),
          ),
          Text(
            navState.mainText,
            style: const TextStyle(
              fontSize: 46,
              fontWeight: FontWeight.w800,
              color: Colors.black,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            navState.subText,
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (navState.remainingStops != null)
                _StatusChip(
                  label: 'のこり ${navState.remainingStops} 停留所',
                  icon: CupertinoIcons.bus,
                  color: const Color(0xFF0D47A1),
                  background: const Color(0xFFE3F2FD),
                  onTap: () {
                    final activeIndex = trip.activeLegIndex;
                    final candidate = (activeIndex < trip.legs.length) 
                        ? trip.legs[activeIndex].candidate 
                        : trip.legs.first.candidate;
                        
                    Navigator.of(context).push(
                      CupertinoPageRoute(
                        builder: (_) => RouteDetailPage(candidate: candidate),
                      ),
                    );
                  },
                ),
              if (navState.nextStopName != null && navState.nextStopName!.isNotEmpty)
                _StatusChip(
                  label: '次: ${navState.nextStopName}',
                  icon: CupertinoIcons.arrow_right_circle_fill,
                  color: const Color(0xFF1B5E20),
                  background: const Color(0xFFE8F5E9),
                ),
            ],
          ),
          const SizedBox(height: 16),
          _LocationStatus(locationAsync: locationAsync),
        ],
      ),
    );
  }
}

class _LocationStatus extends StatelessWidget {
  final AsyncValue<Position> locationAsync;

  const _LocationStatus({required this.locationAsync});

  @override
  Widget build(BuildContext context) {
    return locationAsync.when(
      data: (_) => Row(
        children: const [
          Icon(CupertinoIcons.dot_radiowaves_left_right, color: Colors.teal),
          SizedBox(width: 8),
          Text('GPSで位置を確認中', style: TextStyle(color: Colors.black87)),
        ],
      ),
      loading: () => Row(
        children: const [
          SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
          SizedBox(width: 8),
          Text('現在地を測定しています...', style: TextStyle(color: Colors.black87)),
        ],
      ),
      error: (err, _) => Row(
        children: [
          const Icon(CupertinoIcons.exclamationmark_triangle_fill, color: Colors.red),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '位置情報が取得できません: $err',
              style: const TextStyle(color: Colors.red),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;
  final Color? background;
  final bool truncateStart;
  final VoidCallback? onTap;

  const _StatusChip({
    required this.label,
    required this.icon,
    required this.color,
    this.background,
    this.truncateStart = false,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: background ?? Colors.black12,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 6),
            Flexible(
              child: truncateStart
                  ? Directionality(
                      textDirection: TextDirection.rtl,
                      child: Text(
                        label,
                        style: TextStyle(color: color, fontWeight: FontWeight.bold),
                        overflow: TextOverflow.ellipsis,
                        textAlign: TextAlign.left, // RTLでも左寄せに見せる
                      ),
                    )
                  : Text(
                      label,
                      style: TextStyle(color: color, fontWeight: FontWeight.bold),
                      overflow: TextOverflow.ellipsis,
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SchedulePeek extends StatelessWidget {
  final ScheduleEntry? activeEntry;
  final List<ScheduleEntry> windowEntries; // Changed from upcomingEntries
  final int completedCount;
  final String activeLabel;

  const _SchedulePeek({
    required this.activeEntry,
    required this.windowEntries,
    required this.completedCount,
    this.activeLabel = 'いま',
  });

  String _kindLabel(ScheduleEntryKind kind) {
    switch (kind) {
      case ScheduleEntryKind.meeting:
        return '集合';
      case ScheduleEntryKind.departure:
        return '出発';
      case ScheduleEntryKind.ride:
        return '移動';
      case ScheduleEntryKind.walk:
        return '徒歩';
      case ScheduleEntryKind.arrival:
        return '到着';
      case ScheduleEntryKind.goal:
        return 'ゴール';
      case ScheduleEntryKind.event:
        return '予定';
    }
  }

  IconData _kindIcon(ScheduleEntryKind kind) {
    switch (kind) {
      case ScheduleEntryKind.meeting:
        return CupertinoIcons.person_2_fill;
      case ScheduleEntryKind.departure:
        return CupertinoIcons.paperplane_fill;
      case ScheduleEntryKind.ride:
        return CupertinoIcons.bus;
      case ScheduleEntryKind.walk:
        return CupertinoIcons.location;
      case ScheduleEntryKind.arrival:
        return CupertinoIcons.checkmark_circle_fill;
      case ScheduleEntryKind.goal:
        return CupertinoIcons.flag_fill;
      case ScheduleEntryKind.event:
        return CupertinoIcons.calendar_today;
    }
  }

  @override
  Widget build(BuildContext context) {
    final timeText = (ScheduleEntry entry) => TimeOfDay.fromDateTime(entry.plannedAt).format(context);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [
          BoxShadow(
            color: Color(0x22000000),
            blurRadius: 14,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                '今日の予定',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
              ),
              Text(
                '完了 $completedCount 件',
                style: const TextStyle(color: Colors.black54),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (windowEntries.isEmpty && activeEntry == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('すべての予定を完了しました。お疲れさまです。'),
            )
          else
            Column(
              children: windowEntries.map((e) {
                // Highlight if it's the active entry
                // Note: Object identity might not persist if copies are made, but assuming from same list.
                // Or check properties. ActiveEntry came from resolver which used the same list so identity should hold if passed correctly.
                final isActive = activeEntry != null && e == activeEntry;
                // Or compare unique fields if ScheduleEntry has ID (it doesn't seem to have ID in snippets viewed, only trip has ID).
                // Equality of plannedAt and label is reasonable fallback if identity fails.
                
                return Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _ScheduleRow(
                      label: e.label,
                      description: e.description,
                      timeLabel: timeText(e),
                      icon: _kindIcon(e.itemKind),
                      pill: isActive ? activeLabel : _kindLabel(e.itemKind),
                      highlighted: isActive,
                    ),
                  );
              }).toList(),
            ),
        ],
      ),
    );
  }
}

class _ScheduleRow extends StatelessWidget {
  final String label;
  final String description;
  final String timeLabel;
  final IconData icon;
  final String pill;
  final bool highlighted;

  const _ScheduleRow({
    required this.label,
    required this.description,
    required this.timeLabel,
    required this.icon,
    required this.pill,
    this.highlighted = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: highlighted ? const Color(0xFFE8F5E9) : Colors.grey.shade100,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.08),
                  blurRadius: 6,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: Icon(icon, color: Colors.black87),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: highlighted ? const Color(0xFF2E7D32) : Colors.black87,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        pill,
                        style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      timeLabel,
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  label,
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                if (description.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(description, style: const TextStyle(color: Colors.black54)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _HelperNotice extends StatelessWidget {
  final VoidCallback onHelp;

  const _HelperNotice({required this.onHelp});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFEBEE),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          const Icon(CupertinoIcons.exclamationmark_triangle_fill, color: Colors.red),
          const SizedBox(width: 12),
          const Expanded(
            child: Text(
              '困ったときは「ヘルプ／連絡する」を押してください。音声で読み上げます。',
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
          ),
          ElevatedButton(
            onPressed: onHelp,
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
            child: const Text('ヘルプ'),
          ),
        ],
      ),
    );
  }
}

class _MemberActionBar extends StatelessWidget {
  final VoidCallback onHelp;
  final VoidCallback onOpenDetail;
  final VoidCallback onExit;

  const _MemberActionBar({
    required this.onHelp,
    required this.onOpenDetail,
    required this.onExit,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: onHelp,
                    icon: const Icon(CupertinoIcons.phone),
                    label: const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        'ヘルプ / 連絡',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                      ),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onOpenDetail,
                    icon: const Icon(CupertinoIcons.doc_text),
                    label: const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        'たびのしおり',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                      ),
                    ),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.black,
                      side: const BorderSide(color: Colors.black87, width: 1.2),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: TextButton(
                onPressed: onExit,
                child: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 10),
                  child: Text(
                    '通常モードに戻る',
                    style: TextStyle(color: Colors.black87, fontWeight: FontWeight.bold),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LiveClock extends StatefulWidget {
  const _LiveClock();

  @override
  State<_LiveClock> createState() => _LiveClockState();
}

class _LiveClockState extends State<_LiveClock> {
  late final Timer _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final now = appClock.now();
    final timeStr = "${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}";
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(CupertinoIcons.clock, size: 16, color: Colors.black54),
          const SizedBox(width: 4),
          Text(
            timeStr,
            style: const TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w600,
              fontFeatures: [FontFeature.tabularFigures()],
              color: Colors.black87,
            ),
          ),
        ],
      ),
    );
  }
}

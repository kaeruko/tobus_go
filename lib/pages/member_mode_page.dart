import 'dart:async';
import 'dart:ui';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_clock.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart';
import '../services/bus_location_source.dart';
import '../providers/app_session_provider.dart';
import '../providers/delay_impact_provider.dart';
import '../providers/group_schedule_impact_provider.dart';
import '../providers/trip_provider.dart';
import '../providers/member_mode_provider.dart'; // 作成したProvider
import '../providers/member_nav_progress_provider.dart';
import '../widgets/delay_recovery_card.dart';
import '../widgets/group_schedule_impact_card.dart';
import '../widgets/trip_navigation_status_card.dart';
import 'group_detail_page.dart';
import 'settings_page.dart';
import 'route_detail_page.dart';
import 'segment_stops_page.dart';

class MemberModePage extends ConsumerStatefulWidget {
  const MemberModePage({super.key});

  @override
  ConsumerState<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends ConsumerState<MemberModePage> {
  final _tripService = TripService();

  @override
  void initState() {
    super.initState();
    
    // コントローラー初期化
    ref.read(memberModeControllerProvider.notifier).initialize();

    // ナビ状態リセット
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(memberNavProgressProvider.notifier).reset();
    });
  }

  @override
  Widget build(BuildContext context) {
    final uiStateAsync = ref.watch(memberUiStateProvider);
    final delayResolution = ref.watch(resolvedDelayImpactProvider);
    final delayImpact = delayResolution.impact;
    final scheduleImpact = ref.watch(groupScheduleImpactProvider);
    final realtimeDiagnostic = delayResolution.nextRideRealtimeError == null
        ? null
        : '次便のRealtime確認に失敗したため、予定時刻で判定しています: '
            '${delayResolution.nextRideRealtimeError}';

    return uiStateAsync.when(
      loading: () => const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (err, stack) => Scaffold(
        appBar: const CupertinoNavigationBar(middle: Text('エラー')),
        body: Center(child: Text('エラーが発生しました: $err')),
      ),
      data: (uiState) {
        // 終了判定
        final trip = ref.read(tripStreamProvider).value!;
        if (trip.status == TripStatus.cancelled || trip.status == TripStatus.completed) {
          Future.microtask(() { if (mounted) _leaveGroup(); });
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }

        return Scaffold(
          backgroundColor: uiState.navState.color,
          appBar: _buildAppBar(context, uiState.displayTitle, trip),
          body: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TripNavigationStatusCard(
                    navState: uiState.navState,
                    tripTitle: uiState.displayTitle,
                    onTapStops: () => _onTapRemainingStops(trip),
                    headerTrailing: const _LiveClock(),
                  ),
                  if (delayImpact?.requiresReplan == true) ...[
                    const SizedBox(height: 10),
                    DelayRecoveryCard(
                      impact: delayImpact!,
                      nextRideRealtime: delayResolution.nextRideRealtime,
                      scheduledNextDepartureAt:
                          delayResolution.scheduledNextDepartureAt,
                      realtimeDiagnostic: realtimeDiagnostic,
                      helperText: '経路変更はリーダーだけが確定できます。必要ならリーダーに確認してください。',
                    ),
                  ],
                  if (scheduleImpact != null) ...[
                    const SizedBox(height: 10),
                    GroupScheduleImpactCard(
                      impact: scheduleImpact,
                      helperText: '予定の変更はリーダーが行います。必要ならリーダーに確認してください。',
                    ),
                  ],
                  const SizedBox(height: 14),
                  _SchedulePeek(
                    resolvedEntry: uiState.resolvedEntry,
                    windowEntries: uiState.windowEntries,
                    completedCount: uiState.completedCount,
                    activeLabel: uiState.activeLabel,
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

  Future<void> _leaveGroup() async {
    await ref.read(appSessionProvider.notifier).leaveMemberMode();
  }

  void _onTapRemainingStops(Trip trip) {
    final currentStepId = ref.read(memberNavProgressProvider).currentStepId;
    final segment = currentStepId == null
        ? null
        : trip.stepsById[currentStepId];

    if (segment == null || !segment.isRide || segment.stops.isEmpty) return;

    Navigator.of(context).push(
      CupertinoPageRoute(builder: (_) => SegmentStopsPage(segment: segment)),
    );
  }

  void _openGroupDetail(Trip trip) {
    Navigator.of(context, rootNavigator: true).push(
      CupertinoPageRoute(builder: (_) => GroupDetailPage(trip: trip)),
    );
  }

  Future<void> _sendSOS(String tripId) async {
    showCupertinoDialog(
      context: context,
      builder: (ctx) => CupertinoAlertDialog(
        title: const Text('SOS'),
        content: const Text('引率者に通知を送りますか?'),
        actions: [
          CupertinoDialogAction(child: const Text('キャンセル'), onPressed: () => Navigator.pop(ctx)),
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
                    actions: [CupertinoDialogAction(child: const Text('OK'), onPressed: () => Navigator.pop(ctx2))],
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

  AppBar _buildAppBar(BuildContext context, String title, Trip trip) {
    return AppBar(
      backgroundColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleSpacing: 0,
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('おでかけモード', style: TextStyle(color: Colors.black54, fontSize: 14)),
          Text(title, style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
        ],
      ),
      leading: IconButton(
        icon: const Icon(CupertinoIcons.doc_text, color: Colors.black87),
        onPressed: () => _openGroupDetail(trip),
      ),
      actions: [
        if (ref.read(busLocationSourceProvider) is FakeBusLocationSource)
          IconButton(
            tooltip: 'Fakeバスを次の停留所へ',
            icon: const Icon(Icons.skip_next),
            onPressed: () async {
              final source = ref.read(busLocationSourceProvider)
                  as FakeBusLocationSource;
              source.advance();
              await ref.read(memberModeControllerProvider.notifier).pollNow();
            },
          ),
        IconButton(
          icon: const Icon(Icons.refresh),
          onPressed: () {
            ref.read(memberModeControllerProvider.notifier).pollNow();
          },
        ),
        IconButton(
          icon: const Icon(Icons.settings),
          onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsPage())),
        ),
        TextButton(
          onPressed: () => showCupertinoDialog(
            context: context,
            builder: (ctx) => CupertinoAlertDialog(
              title: const Text('モード終了'),
              content: const Text('通常モードに戻りますか?'),
              actions: [
                CupertinoDialogAction(child: const Text('いいえ'), onPressed: () => Navigator.pop(ctx)),
                CupertinoDialogAction(
                  isDestructiveAction: true,
                  onPressed: () { Navigator.pop(ctx); _leaveGroup(); },
                  child: const Text('はい'),
                ),
              ],
            ),
          ),
          child: const Text('終了', style: TextStyle(color: CupertinoColors.destructiveRed)),
        ),
      ],
    );
  }
}

// -----------------------------------------------------------------------------
// UI Components
// -----------------------------------------------------------------------------

class _SchedulePeek extends StatelessWidget {
  final ScheduleEntry? resolvedEntry;
  final List<ScheduleEntry> windowEntries;
  final int completedCount;
  final String activeLabel;

  const _SchedulePeek({required this.resolvedEntry, required this.windowEntries, required this.completedCount, required this.activeLabel});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [BoxShadow(color: Color(0x22000000), blurRadius: 14, offset: Offset(0, 8))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('今日の予定', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              Text('完了 $completedCount 件', style: const TextStyle(color: Colors.black54)),
            ],
          ),
          const SizedBox(height: 10),
          if (windowEntries.isEmpty && resolvedEntry == null)
            const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Text('すべての予定を完了しました。'))
          else
            Column(
              children: windowEntries.map((e) {
                // インスタンスが異なっても内容で比較したい場合はモデルに==実装が必要ですが、
                // ここではresolvedEntry自体がwindowEntriesに含まれている前提、もしくは参照が同じであることを期待
                final isActive = resolvedEntry != null && e == resolvedEntry;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _ScheduleRow(entry: e, isActive: isActive, activeLabel: activeLabel),
                );
              }).toList(),
            ),
        ],
      ),
    );
  }
}

class _ScheduleRow extends StatelessWidget {
  final ScheduleEntry entry;
  final bool isActive;
  final String activeLabel;

  const _ScheduleRow({required this.entry, required this.isActive, required this.activeLabel});

  @override
  Widget build(BuildContext context) {
    final timeStr = TimeOfDay.fromDateTime(entry.plannedAt).format(context);
    final icon = _getIcon(entry.itemKind);
    final label = _getLabel(entry.itemKind);
    final pillText = isActive ? activeLabel : label;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: isActive ? const Color(0xFFE8F5E9) : Colors.grey.shade100,
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
              boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.08), blurRadius: 6, offset: const Offset(0, 4))],
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
                        color: isActive ? const Color(0xFF2E7D32) : Colors.black87,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(pillText, style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)),
                    ),
                    const SizedBox(width: 8),
                    Text(timeStr, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                  ],
                ),
                const SizedBox(height: 6),
                Text(entry.label, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                if (entry.description.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(entry.description, style: const TextStyle(color: Colors.black54)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  IconData _getIcon(ScheduleEntryKind kind) {
    switch (kind) {
      case ScheduleEntryKind.meeting: return CupertinoIcons.person_2_fill;
      case ScheduleEntryKind.departure: return CupertinoIcons.paperplane_fill;
      case ScheduleEntryKind.ride: return CupertinoIcons.bus;
      case ScheduleEntryKind.walk: return CupertinoIcons.location;
      case ScheduleEntryKind.arrival: return CupertinoIcons.checkmark_circle_fill;
      case ScheduleEntryKind.goal: return CupertinoIcons.flag_fill;
      case ScheduleEntryKind.event: return CupertinoIcons.calendar_today;
    }
  }

  String _getLabel(ScheduleEntryKind kind) {
    switch (kind) {
      case ScheduleEntryKind.meeting: return '集合';
      case ScheduleEntryKind.departure: return '出発';
      case ScheduleEntryKind.ride: return '移動';
      case ScheduleEntryKind.walk: return '徒歩';
      case ScheduleEntryKind.arrival: return '到着';
      case ScheduleEntryKind.goal: return 'ゴール';
      case ScheduleEntryKind.event: return '予定';
    }
  }
}

class _HelperNotice extends StatelessWidget {
  final VoidCallback onHelp;
  const _HelperNotice({required this.onHelp});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: const Color(0xFFFFEBEE), borderRadius: BorderRadius.circular(16)),
      child: Row(
        children: [
          const Icon(CupertinoIcons.exclamationmark_triangle_fill, color: Colors.red),
          const SizedBox(width: 12),
          const Expanded(child: Text('困ったときは「ヘルプ／連絡する」を押してください。音声で読み上げます。', style: TextStyle(fontWeight: FontWeight.bold))),
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

  const _MemberActionBar({required this.onHelp, required this.onOpenDetail, required this.onExit});

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
                    label: const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: Text('ヘルプ / 連絡', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold))),
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onOpenDetail,
                    icon: const Icon(CupertinoIcons.doc_text),
                    label: const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: Text('たびのしおり', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold))),
                    style: OutlinedButton.styleFrom(foregroundColor: Colors.black, side: const BorderSide(color: Colors.black87, width: 1.2), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: TextButton(
                onPressed: onExit,
                child: const Padding(padding: EdgeInsets.symmetric(vertical: 10), child: Text('通常モードに戻る', style: TextStyle(color: Colors.black87, fontWeight: FontWeight.bold))),
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
    _timer = Timer.periodic(const Duration(seconds: 1), (_) { if (mounted) setState(() {}); });
  }
  @override
  void dispose() { _timer.cancel(); super.dispose(); }
  @override
  Widget build(BuildContext context) {
    final now = appClock.now();
    final timeStr = "${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}";
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(color: Colors.black.withValues(alpha: 0.05), borderRadius: BorderRadius.circular(16)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(CupertinoIcons.clock, size: 16, color: Colors.black54),
          const SizedBox(width: 4),
          Text(timeStr, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600, fontFeatures: [FontFeature.tabularFigures()], color: Colors.black87)),
        ],
      ),
    );
  }
}

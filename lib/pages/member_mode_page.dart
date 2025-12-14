import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../services/trip_service.dart'; // For sendSOS
import '../models/group_models.dart';
import 'schedule_page.dart';
import '../logic/trip_navigator.dart';
import '../providers/app_session_provider.dart';
import '../providers/trip_provider.dart';
import '../providers/location_provider.dart';
import '../providers/member_nav_progress_provider.dart';

class MemberModePage extends ConsumerStatefulWidget {
  const MemberModePage({super.key});

  @override
  ConsumerState<MemberModePage> createState() => _MemberModePageState();
}

class _MemberModePageState extends ConsumerState<MemberModePage> {
  // Service for SOS only, data is via provider
  final _tripService = TripService();

  @override
  void initState() {
    super.initState();

    // Use ref.listen for side-effects (Riverpod-native way)
    ref.listen(tripStreamProvider, (prev, next) {
      next.whenData((trip) {
        if (trip != null) {
          final posAsync = ref.read(locationStreamProvider);
          if (posAsync.hasValue) {
            final pos = posAsync.value!;
            ref
                .read(memberNavProgressProvider.notifier)
                .updateProgress(trip, LatLng(pos.latitude, pos.longitude));
          }
        }
      });
    });

    ref.listen(locationStreamProvider, (prev, next) {
      next.whenData((pos) {
        final tripAsync = ref.read(tripStreamProvider);
        if (tripAsync.hasValue && tripAsync.value != null) {
          ref.read(memberNavProgressProvider.notifier).updateProgress(
                tripAsync.value!,
                LatLng(pos.latitude, pos.longitude),
              );
        }
      });
    });
  }

  Future<void> _leaveGroup() async {
    await ref.read(appSessionProvider.notifier).leaveMemberMode();
    // RootGate will handle the switch
  }

  void _openSchedule(String tripId, List<ScheduleEntry> schedule) {
    Navigator.of(context, rootNavigator: true).push(
      CupertinoPageRoute(
        builder: (_) => SchedulePage(
          tripId: tripId,
          isLeader: false,
          initialSchedule: schedule,
        ),
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
    // Listeners are now in initState

    final tripAsync = ref.watch(tripStreamProvider);
    final locationAsync = ref.watch(locationStreamProvider);
    final navProgress = ref.watch(memberNavProgressProvider);

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

        if (trip.status == TripStatus.cancelled) {
          return Scaffold(
            appBar: AppBar(title: const Text('お知らせ'), backgroundColor: Colors.red),
            body: Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Text('ホストによりグループが解散されました。', style: TextStyle(fontSize: 18)),
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

        final schedule = _sortedSchedule(trip.schedule);
        final currentPos = locationAsync.value != null
            ? LatLng(locationAsync.value!.latitude, locationAsync.value!.longitude)
            : const LatLng(35.6812, 139.7671); // Default Tokyo Station if waiting for GPS

        // Calculate view state using CURRENT progress indices
        final navState = TripNavigator.updateState(
          trip,
          currentPos,
          navProgress.currentStepIndex,
          navProgress.nextStopIndex,
        );

        final activeIndex = schedule.indexWhere((item) => !item.isCompleted);
        final activeEntry = activeIndex >= 0 ? schedule[activeIndex] : null;
        final upcomingEntries = (activeIndex >= 0 ? schedule.skip(activeIndex + 1) : schedule)
            .take(3)
            .toList();
        final completedCount = schedule.where((e) => e.isCompleted).length;

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
                const Text('えんそくモード', style: TextStyle(color: Colors.black54, fontSize: 14)),
                Text(
                  trip.title,
                  style: const TextStyle(
                    color: Colors.black,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            leading: IconButton(
              icon: const Icon(CupertinoIcons.list_bullet, color: Colors.black87),
              onPressed: () => _openSchedule(trip.id, schedule),
              tooltip: 'スケジュールを開く',
            ),
            actions: [
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
                    tripTitle: trip.title,
                    locationAsync: locationAsync,
                  ),
                  const SizedBox(height: 14),
                  _SchedulePeek(
                    activeEntry: activeEntry,
                    upcomingEntries: upcomingEntries,
                    completedCount: completedCount,
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
            onOpenSchedule: () => _openSchedule(trip.id, schedule),
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

  const _CurrentStatusCard({
    required this.navState,
    required this.tripTitle,
    required this.locationAsync,
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

  const _StatusChip({
    required this.label,
    required this.icon,
    required this.color,
    this.background,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
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
          Text(
            label,
            style: TextStyle(color: color, fontWeight: FontWeight.bold),
          ),
        ],
      ),
    );
  }
}

class _SchedulePeek extends StatelessWidget {
  final ScheduleEntry? activeEntry;
  final List<ScheduleEntry> upcomingEntries;
  final int completedCount;

  const _SchedulePeek({
    required this.activeEntry,
    required this.upcomingEntries,
    required this.completedCount,
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
          if (activeEntry != null) ...[
            _ScheduleRow(
              label: activeEntry!.label,
              description: activeEntry!.description,
              timeLabel: timeText(activeEntry!),
              icon: _kindIcon(activeEntry!.itemKind),
              pill: 'いま',
              highlighted: true,
            ),
            const SizedBox(height: 12),
            const Divider(),
            const SizedBox(height: 12),
          ] else
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('すべての予定を完了しました。お疲れさまです。'),
            ),
          Column(
            children: upcomingEntries
                .map(
                  (e) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _ScheduleRow(
                      label: e.label,
                      description: e.description,
                      timeLabel: timeText(e),
                      icon: _kindIcon(e.itemKind),
                      pill: _kindLabel(e.itemKind),
                    ),
                  ),
                )
                .toList(),
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
  final VoidCallback onOpenSchedule;
  final VoidCallback onExit;

  const _MemberActionBar({
    required this.onHelp,
    required this.onOpenSchedule,
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
                    icon: const Icon(CupertinoIcons.sos),
                    label: const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        'ヘルプ / 連絡する',
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
                    onPressed: onOpenSchedule,
                    icon: const Icon(CupertinoIcons.list_bullet),
                    label: const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        '予定をみる',
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

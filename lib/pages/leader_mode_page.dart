// lib/pages/leader_mode_page.dart
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../core/app_clock.dart';
import '../widgets/route_map_preview.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../services/trip_service.dart';
import 'group_detail_page.dart';
import 'schedule_page.dart';
import 'route_detail_page.dart';

class LeaderModePage extends StatefulWidget {
  final String tripId;
  const LeaderModePage({super.key, required this.tripId});

  @override
  State<LeaderModePage> createState() => _LeaderModePageState();
}

class _LeaderModePageState extends State<LeaderModePage> {
  static const int _thresholdMinutes = 5;
  bool _starting = false;
  Timer? _clockTimer;

  @override
  void initState() {
    super.initState();
    _clockTimer = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted) {
        setState(() {});
      }
    });
  }

  @override
  void dispose() {
    _clockTimer?.cancel();
    super.dispose();
  }

  ScheduleEntry? _findFirstByKind(
      List<ScheduleEntry> schedule, ScheduleEntryKind kind) {
    final entries = List<ScheduleEntry>.from(schedule)
      ..sort((a, b) => a.plannedAt.compareTo(b.plannedAt));
    for (final entry in entries) {
      if (entry.itemKind == kind) return entry;
    }
    return null;
  }

  DateTime? _findLastPlannedAt(List<ScheduleEntry> schedule) {
    if (schedule.isEmpty) return null;
    return schedule
        .map((entry) => entry.plannedAt)
        .reduce((a, b) => a.isAfter(b) ? a : b);
  }

  String _formatTime(DateTime dateTime) {
    final hour = dateTime.hour.toString().padLeft(2, '0');
    final minute = dateTime.minute.toString().padLeft(2, '0');
    return '$hour:$minute';
  }

  String _formatScheduleWindow(DateTime? start, DateTime? end) {
    if (start == null || end == null) return '日程情報がありません';
    final dateLabel = '${start.month}/${start.day} (${_weekdayLabel(start.weekday)})';
    final startLabel = _formatTime(start);
    final endLabel = _formatTime(end);
    return '$dateLabel  $startLabel〜$endLabel';
  }

  String _weekdayLabel(int weekday) {
    const labels = ['月', '火', '水', '木', '金', '土', '日'];
    final index = (weekday - 1).clamp(0, labels.length - 1).toInt();
    return labels[index];
  }

  Future<void> _handleStartTrip(Trip trip, TripService service) async {
    if (_starting) return;
    setState(() => _starting = true);

    try {
      final now = appClock.now();
      final planned = trip.plannedDepartureAt ??
          (trip.schedule.isNotEmpty ? trip.schedule.first.plannedAt : now);
      final deltaMinutes = now.difference(planned).inMinutes;

      await service.startTrip(trip.id, now);

      if (!mounted) return;

      if (deltaMinutes.abs() >= _thresholdMinutes) {
        await _showRerouteDialog(trip, service, now, deltaMinutes);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('旅を開始しました')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('開始に失敗しました: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _starting = false);
      }
    }
  }

  Future<void> _showRerouteDialog(
      Trip trip, TripService service, DateTime departure, int delta) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('再検索しますか？'),
        content: Text('予定より${delta.abs()}分ずれています。経路を再計算しますか？'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('そのまま続行')),
          ElevatedButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('再検索する')),
        ],
      ),
    );

    if (result == true) {
      await _rerouteOutward(trip, service, departure);
    }
  }

  Future<void> _rerouteOutward(
      Trip trip, TripService service, DateTime departure) async {
    Leg? outbound;
    for (final leg in trip.legs) {
      if (leg.direction == LegDirection.outbound) {
        outbound = leg;
        break;
      }
    }

    if (outbound == null) return;

    final newOutward = createScheduleFromRoute(
      outbound.candidate,
      startDateTime: departure,
      labelPrefix: '行き',
      legIndex: 0,
      shiftToStart: true,
    );

    final updatedSchedule =
        service.applyRerouteOutwardOnly(trip.schedule, newOutward);

    await service.updateSchedule(trip.id, updatedSchedule);

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('行きの経路を更新しました')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tripService = TripService();

    return StreamBuilder<Trip>(
      stream: tripService.streamTrip(widget.tripId),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Scaffold(
              body: Center(child: Text('エラー: ${snapshot.error}')));
        }
        if (!snapshot.hasData) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }

        final trip = snapshot.data!;

        final meetingEntry = _findFirstByKind(trip.schedule, ScheduleEntryKind.meeting);
        final goalEntry = _findFirstByKind(trip.schedule, ScheduleEntryKind.goal);
        final lastEntryAt = _findLastPlannedAt(trip.schedule);
        final scheduleStart = meetingEntry?.plannedAt ?? trip.plannedDepartureAt;
        final scheduleEnd = lastEntryAt ?? trip.plannedDepartureAt ?? trip.date;
        String titlePrefix;
        String? destName;
        if (trip.legs.isNotEmpty) {
          final outboundLeg = trip.legs.firstWhere(
              (l) => l.direction == LegDirection.outbound,
              orElse: () => trip.legs.first);
          destName = outboundLeg.candidate.destinationName;
        }

        if (destName != null && destName.isNotEmpty) {
          titlePrefix = Trip.extractSimpleName(destName);
        } else {
          titlePrefix = (goalEntry?.label.isNotEmpty ?? false)
              ? goalEntry!.label
              : (trip.title.isNotEmpty ? trip.title : '目的地');
        }

        return Scaffold(
          appBar: AppBar(
            title: const Text('おでかけ編集'),
            backgroundColor: Colors.green,
            actions: [
              IconButton(
                icon: const Icon(Icons.delete_forever),
                tooltip: 'おでかけを中止',
                onPressed: () => _confirmCancel(context, trip),
              ),
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
          body: SafeArea(
            child: Column(
              children: [
                _buildHeader(
                  context,
                  '$titlePrefixへのおでかけ',
                  _formatScheduleWindow(scheduleStart, scheduleEnd),
                  trip,
                ),
                Expanded(
                  child: _buildMainArea(
                    context,
                    trip,
                  ),
                ),
                _buildActionArea(trip, tripService, meetingEntry?.plannedAt),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildHeader(
    BuildContext context,
    String title,
    String scheduleWindow,
    Trip trip,
  ) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
      decoration: BoxDecoration(
        color: Colors.green.shade50,
        border: Border(
          bottom: BorderSide(color: Colors.green.shade100),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.bold,
              color: Colors.black87,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              const Icon(Icons.schedule, color: Colors.green),
              const SizedBox(width: 8),
              Text(
                scheduleWindow,
                style: const TextStyle(fontSize: 14, color: Colors.black87),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.green.shade100),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.03),
                  blurRadius: 8,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '参加コード',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.bold,
                          color: Colors.green,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        trip.joinCode,
                        style: const TextStyle(
                          fontSize: 36,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 6,
                        ),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'いつでも確認・コピーできます',
                        style: TextStyle(color: Colors.grey),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                ElevatedButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: trip.joinCode));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('コードをコピーしました')),
                    );
                  },
                  icon: const Icon(Icons.copy, size: 18),
                  label: const Text('コピー'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.green,
                    foregroundColor: Colors.white,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMainArea(
    BuildContext context,
    Trip trip,
  ) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildScheduleShortcut(context, trip),
          const SizedBox(height: 12),
          _buildGuideLink(context, trip),
          const SizedBox(height: 16),
          _buildMapCard(context, trip),
          const SizedBox(height: 16),
          _buildMemberCard(trip),
          const SizedBox(height: 12),
        ],
      ),
    );
  }

  Widget _buildGuideLink(BuildContext context, Trip trip) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: ListTile(
        leading: const Icon(Icons.menu_book, color: Colors.orange),
        title: const Text(
          'おでかけのしおり',
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: const Text('グループ詳細や参加コードを確認'),
        trailing: const Icon(Icons.arrow_forward_ios,
            size: 16, color: Colors.orange),
        onTap: () {
          Navigator.of(context, rootNavigator: true).push(
            MaterialPageRoute(
              builder: (_) => GroupDetailPage(trip: trip),
            ),
          );
        },
      ),
    );
  }

  Widget _buildScheduleShortcut(BuildContext context, Trip trip) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      color: Colors.green.shade50,
      child: ListTile(
        leading: const Icon(Icons.list_alt, color: Colors.green),
        title: const Text(
          'Schedule Page',
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: const Text('同じ画面からスケジュールを確認・編集'),
        trailing: const Icon(Icons.arrow_forward_ios, size: 16, color: Colors.green),
        onTap: () {
          Navigator.of(context, rootNavigator: true).push(
            MaterialPageRoute(
              builder: (_) => SchedulePage(
                tripId: trip.id,
                isLeader: true,
                initialSchedule: trip.schedule,
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildMapCard(BuildContext context, Trip trip) {
    // 優先的に「行き」のルートポイントを取得する
    List<LatLng> points = [];
    Candidate? candidate;
    if (trip.legs.isNotEmpty) {
      final outbound = trip.legs.firstWhere(
        (l) => l.direction == LegDirection.outbound,
        orElse: () => trip.legs.first,
      );
      points = outbound.candidate.points;
      candidate = outbound.candidate;
    }

    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      elevation: 1,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  Icon(Icons.map, color: Colors.blue.shade700),
                  const SizedBox(width: 8),
                  const Text(
                    '地図 (Map)',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            RouteMapPreview(points: points),
            if (candidate != null) ...[
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => RouteDetailPage(candidate: candidate!),
                      ),
                    );
                  },
                  icon: const Icon(Icons.list, size: 18),
                  label: const Text('目的地までの乗り換え'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildMemberCard(Trip trip) {
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      elevation: 1,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.group, color: Colors.teal.shade700),
                const SizedBox(width: 8),
                const Text(
                  'メンバー (Members)',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 8),
                const Text(
                  '点呼用',
                  style: TextStyle(color: Colors.grey),
                )
              ],
            ),
            const SizedBox(height: 12),
            if (trip.participants.isEmpty)
              const Text('参加者がまだいません')
            else
              ...trip.participants.map((member) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(
                      children: [
                        CircleAvatar(
                          backgroundColor:
                              member.isLeader ? Colors.green : Colors.blue,
                          child: Icon(
                            member.isLeader ? Icons.star : Icons.person,
                            color: Colors.white,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                member.name,
                                style: const TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              Text(
                                member.isLeader ? 'リーダー' : '参加済み',
                                style: const TextStyle(color: Colors.grey),
                              ),
                            ],
                          ),
                        ),
                        if (member.sosCount != null && member.sosCount! > 0)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 10, vertical: 6),
                            decoration: BoxDecoration(
                              color: Colors.red.shade50,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.warning,
                                    color: Colors.red, size: 18),
                                const SizedBox(width: 4),
                                Text(
                                  'SOS ${member.sosCount}',
                                  style: const TextStyle(
                                    color: Colors.red,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  )),
          ],
        ),
      ),
    );
  }

  Widget _buildActionArea(
      Trip trip, TripService service, DateTime? meetingAt) {
    final now = appClock.now();
    final canStart =
        meetingAt != null ? !now.isBefore(meetingAt) && !_starting : false;

    if (trip.travelPhase == TravelPhase.planning) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: Colors.grey.shade200)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.04),
              blurRadius: 8,
              offset: const Offset(0, -2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              meetingAt != null
                  ? '集合時間になると開始できます'
                  : '集合の予定が未設定です',
              style: const TextStyle(color: Colors.grey),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: canStart
                    ? () => _handleStartTrip(trip, service)
                    : null,
                icon: _starting
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.play_arrow),
                label: const Text(
                  'お出かけを開始する',
                  style: TextStyle(fontSize: 18),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.orange,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    }

    if (trip.travelPhase == TravelPhase.active) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: Colors.grey.shade200)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.04),
              blurRadius: 8,
              offset: const Offset(0, -2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: const [
                Icon(Icons.location_on, color: Colors.green),
                SizedBox(width: 8),
                Text(
                  '移動中（位置共有ON）',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: () => _showCompleteDialog(context, trip),
                icon: const Icon(Icons.check_circle),
                label: const Text('お出かけを終了する'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.grey.shade700,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: Colors.grey.shade200)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.04),
            blurRadius: 8,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: Text(
        '状態: ${trip.travelPhase.name}',
        style: const TextStyle(color: Colors.grey),
      ),
    );
  }

  void _showCompleteDialog(BuildContext context, Trip trip) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('お出かけ終了'),
        content: const Text('本当に終了しますか?\nメンバーの画面も「終了」に切り替わります。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('キャンセル'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.green,
              foregroundColor: Colors.white,
            ),
            onPressed: () async {
              Navigator.pop(ctx); // ダイアログを閉じる
              try {
                // 終了処理を実行
                await TripService().completeTrip(trip.id);
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('お出かけを終了しました')),
                  );
                  Navigator.pop(context); // リーダー画面を閉じる
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('終了処理に失敗しました: $e')),
                  );
                }
              }
            },
            child: const Text('終了する'),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmCancel(BuildContext context, Trip trip) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('おでかけを中止しますか？'),
        content: const Text(
            'この操作は取り消せません。\n'
            '中止すると、参加者全員の画面で「解散」と表示され、旅が終了します。'
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('キャンセル'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.red,
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('中止する'),
          ),
        ],
      ),
    );

    if (confirmed == true && mounted) {
      try {
        await TripService().cancelTrip(trip.id);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('おでかけを中止しました')),
          );
          Navigator.pop(context); // Close the leader page
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('エラーが発生しました: $e')),
          );
        }
      }
    }
  }
}

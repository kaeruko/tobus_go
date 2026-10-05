import 'package:flutter/material.dart';
import '../l10n/app_localizations.dart';
import 'package:flutter/services.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import '../logic/group_schedule_sections.dart';
import '../services/user_service.dart';
import '../widgets/group_leader_route_replan_panel.dart';

import 'member_mode_page.dart';
import 'ride_stops_navigation.dart';
import 'schedule_page.dart';

class GroupDetailPage extends StatelessWidget {
  final Trip trip;

  const GroupDetailPage({super.key, required this.trip});

  DateTime _resolveStartDateTime() {
    final scheduledStart = trip.schedule.isNotEmpty
        ? trip.schedule
              .map((entry) => entry.plannedAt)
              .reduce((a, b) => a.isBefore(b) ? a : b)
        : null;
    return trip.plannedDepartureAt ?? scheduledStart ?? trip.date;
  }

  String _formatDateTime(DateTime dateTime) {
    final month = dateTime.month.toString().padLeft(2, '0');
    final day = dateTime.day.toString().padLeft(2, '0');
    final hour = dateTime.hour.toString().padLeft(2, '0');
    final minute = dateTime.minute.toString().padLeft(2, '0');
    return '$month/$day $hour:$minute';
  }

  String _formatScheduleTime(DateTime dt, bool showDate) {
    var time =
        '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    if (showDate) {
      return '${dt.month}/${dt.day} $time';
    }
    return time;
  }

  Future<void> _navigateToMode(BuildContext context) async {
    final uid = UserService().currentUserId;
    final isLeader = (uid == trip.leaderId);

    if (isLeader) {
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => SchedulePage(
            tripId: trip.id,
            isLeader: true,
            initialSchedule: trip.schedule,
          ),
        ),
      );
    } else {
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const MemberModePage()),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final showDate =
        trip.schedule.isNotEmpty &&
        (trip.schedule.first.plannedAt.day !=
                trip.schedule.last.plannedAt.day ||
            trip.schedule.first.plannedAt.month !=
                trip.schedule.last.plannedAt.month);
    final currentUserId = UserService().currentUserId;
    final isLeader = currentUserId != null && currentUserId == trip.leaderId;
    final canReplan = isLeader && trip.travelPhase == TravelPhase.active;
    final scheduleSections = GroupScheduleSections.fromEntries(trip.schedule);

    return Scaffold(
      appBar: AppBar(title: Text(AppLocalizations.of(context).groupGuideTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. タイトルとコード
            Card(
              elevation: 2,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    Text(
                      trip.title,
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: Colors.orange.shade50,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.orange.shade200),
                      ),
                      child: Column(
                        children: [
                          Text(
                            AppLocalizations.of(context).groupJoinCode,
                            style: TextStyle(fontSize: 12, color: Colors.grey),
                          ),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                trip.joinCode,
                                style: const TextStyle(
                                  fontSize: 24,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 4,
                                ),
                              ),
                              const SizedBox(width: 8),
                              IconButton(
                                icon: const Icon(Icons.copy, size: 20),
                                onPressed: () {
                                  Clipboard.setData(
                                    ClipboardData(text: trip.joinCode),
                                  );
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                      content: Text(
                                        AppLocalizations.of(
                                          context,
                                        ).groupJoinCodeCopied,
                                      ),
                                    ),
                                  );
                                },
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),

            // 2. 基本情報
            Text(
              AppLocalizations.of(context).groupBasicInfo,
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            _InfoRow(
              icon: Icons.person,
              label: AppLocalizations.of(context).groupLeader,
              value: trip.participants
                  .firstWhere(
                    (p) => p.isLeader,
                    orElse: () => trip.participants.first,
                  )
                  .name,
            ),
            const SizedBox(height: 8),
            _InfoRow(
              icon: Icons.calendar_today,
              label: AppLocalizations.of(context).groupDate,
              value: _formatDateTime(_resolveStartDateTime()),
            ),

            if (canReplan) ...[
              const SizedBox(height: 16),
              GroupLeaderRouteReplanPanel(tripId: trip.id),
            ],

            const SizedBox(height: 24),

            // 3. 参加者
            Text(
              AppLocalizations.of(context).groupParticipants,
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: trip.participants.map((p) {
                return Chip(
                  avatar: CircleAvatar(
                    backgroundColor: p.isLeader
                        ? Colors.orange
                        : Colors.blue.shade100,
                    child: Text(
                      p.name[0],
                      style: const TextStyle(fontSize: 12, color: Colors.white),
                    ),
                  ),
                  label: Text(p.name),
                  backgroundColor: Colors.white,
                  side: BorderSide(color: Colors.grey.shade300),
                );
              }).toList(),
            ),

            const SizedBox(height: 24),

            // 4. しおり（往路 / 現地予定 / 復路）
            Text(
              AppLocalizations.of(context).groupGuideSchedule,
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 10),
            _GuideScheduleBlock(
              title: AppLocalizations.of(context).groupOutbound,
              icon: Icons.arrow_forward,
              entries: scheduleSections.outboundRoute,
              showDate: showDate,
              formatTime: _formatScheduleTime,
              onTapRide: (entry) => openRideStops(
                context: context,
                trip: trip,
                entry: entry,
              ),
            ),
            const SizedBox(height: 12),
            _GuideScheduleBlock(
              title: AppLocalizations.of(context).groupScheduleOnsite,
              icon: Icons.event_note,
              entries: scheduleSections.onsiteEntries,
              showDate: showDate,
              formatTime: _formatScheduleTime,
              emptyLabel: AppLocalizations.of(
                context,
              ).groupScheduleOnsiteEmpty,
            ),
            const SizedBox(height: 12),
            _GuideScheduleBlock(
              title: AppLocalizations.of(context).groupInbound,
              icon: Icons.arrow_back,
              entries: scheduleSections.inboundRoute,
              showDate: showDate,
              formatTime: _formatScheduleTime,
              onTapRide: (entry) => openRideStops(
                context: context,
                trip: trip,
                entry: entry,
              ),
            ),
            for (final section in scheduleSections.additionalRoutes) ...[
              const SizedBox(height: 12),
              _GuideScheduleBlock(
                title: AppLocalizations.of(
                  context,
                ).groupScheduleAdditionalRoute(section.legIndex + 1),
                icon: Icons.route,
                entries: section.entries,
                showDate: showDate,
                formatTime: _formatScheduleTime,
                onTapRide: (entry) => openRideStops(
                  context: context,
                  trip: trip,
                  entry: entry,
                ),
              ),
            ],

            const SizedBox(height: 40),

            // 下部の余白確保 (FABやBottomBarとかぶらないように)
            const SizedBox(height: 80),
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: SizedBox(
            height: 50,
            child: ElevatedButton.icon(
              onPressed: () => _navigateToMode(context),
              icon: const Icon(Icons.play_arrow),
              label: Text(
                AppLocalizations.of(context).groupEdit,
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.orange,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  const _InfoRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 20, color: Colors.grey),
        const SizedBox(width: 8),
        Text("$label: ", style: const TextStyle(fontWeight: FontWeight.bold)),
        Text(value),
      ],
    );
  }
}


class _GuideScheduleBlock extends StatelessWidget {
  final String title;
  final IconData icon;
  final List<ScheduleEntry> entries;
  final bool showDate;
  final String Function(DateTime, bool) formatTime;
  final String? emptyLabel;
  final ValueChanged<ScheduleEntry>? onTapRide;

  const _GuideScheduleBlock({
    required this.title,
    required this.icon,
    required this.entries,
    required this.showDate,
    required this.formatTime,
    this.emptyLabel,
    this.onTapRide,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      elevation: 1,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(icon, size: 20),
                const SizedBox(width: 8),
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            const Divider(height: 1),
            if (entries.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 16),
                child: Text(
                  emptyLabel ?? '',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              )
            else
              for (final entry in entries)
                _GuideScheduleRow(
                  entry: entry,
                  showDate: showDate,
                  formatTime: formatTime,
                  onTap: entry.itemKind == ScheduleEntryKind.ride &&
                          onTapRide != null
                      ? () => onTapRide!(entry)
                      : null,
                ),
          ],
        ),
      ),
    );
  }
}

class _GuideScheduleRow extends StatelessWidget {
  final ScheduleEntry entry;
  final bool showDate;
  final String Function(DateTime, bool) formatTime;
  final VoidCallback? onTap;

  const _GuideScheduleRow({
    required this.entry,
    required this.showDate,
    required this.formatTime,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: showDate ? 72 : 48,
              child: Text(
                formatTime(entry.plannedAt, showDate),
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    entry.label,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  if (entry.description.trim().isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      entry.description,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 12,
                        color: Theme.of(
                          context,
                        ).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (onTap != null)
              const Padding(
                padding: EdgeInsets.only(left: 6, top: 2),
                child: Icon(Icons.chevron_right, size: 20),
              ),
          ],
        ),
      ),
    );
  }
}

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../models/group_models.dart';

enum TripScheduleWindowAppearance {
  listTiles,
  boxedRows,
}

typedef TripScheduleCounterLabelBuilder = String Function(
  int completedCount,
  int? totalCount,
);

class TripScheduleWindowCard extends StatelessWidget {
  final String title;
  final ScheduleEntry? resolvedEntry;
  final List<ScheduleEntry> entries;
  final int completedCount;
  final int? totalCount;
  final String activeLabel;
  final TripScheduleCounterLabelBuilder counterLabelBuilder;
  final ValueChanged<ScheduleEntry>? onTapEntry;
  final TripScheduleWindowAppearance appearance;
  final String? emptyLabel;

  const TripScheduleWindowCard({
    super.key,
    required this.title,
    required this.resolvedEntry,
    required this.entries,
    required this.completedCount,
    required this.activeLabel,
    required this.counterLabelBuilder,
    required this.appearance,
    this.totalCount,
    this.onTapEntry,
    this.emptyLabel,
  });

  @override
  Widget build(BuildContext context) {
    _validate();

    final counterLabel = counterLabelBuilder(completedCount, totalCount);
    if (counterLabel.trim().isEmpty) {
      throw StateError('予定ウィンドウの件数表示が空です');
    }

    return switch (appearance) {
      TripScheduleWindowAppearance.listTiles => _buildListTiles(
          context,
          counterLabel,
        ),
      TripScheduleWindowAppearance.boxedRows => _buildBoxedRows(
          context,
          counterLabel,
        ),
    };
  }

  void _validate() {
    if (title.trim().isEmpty) {
      throw StateError('予定ウィンドウのタイトルが空です');
    }
    if (completedCount < 0) {
      throw StateError('完了件数が不正です: $completedCount');
    }
    final expectedTotal = totalCount;
    if (expectedTotal != null) {
      if (expectedTotal < 0 || completedCount > expectedTotal) {
        throw StateError(
          '予定件数が不正です: completed=$completedCount, total=$expectedTotal',
        );
      }
    }

    final ids = <String>{};
    for (final entry in entries) {
      if (!ids.add(entry.id)) {
        throw StateError('予定ウィンドウに重複したentry idがあります: ${entry.id}');
      }
    }
  }

  Widget _buildListTiles(BuildContext context, String counterLabel) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildHeader(counterLabel),
            const SizedBox(height: 10),
            if (entries.isEmpty && emptyLabel != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(emptyLabel!),
              )
            else
              ...entries.map((entry) {
                final isActive = resolvedEntry?.id == entry.id;
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  onTap: _entryTap(entry),
                  leading: Icon(_listTileIcon(entry)),
                  title: Text(entry.label),
                  subtitle: isActive ? Text(activeLabel) : null,
                  trailing: Text(_format24Hour(entry.plannedAt)),
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

  Widget _buildBoxedRows(BuildContext context, String counterLabel) {
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
          _buildHeader(counterLabel, counterColor: Colors.black54),
          const SizedBox(height: 10),
          if (entries.isEmpty && resolvedEntry == null && emptyLabel != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(emptyLabel!),
            )
          else
            Column(
              children: entries.map((entry) {
                final isActive = resolvedEntry?.id == entry.id;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _BoxedScheduleRow(
                    entry: entry,
                    isActive: isActive,
                    activeLabel: activeLabel,
                    onTap: _entryTap(entry),
                  ),
                );
              }).toList(),
            ),
        ],
      ),
    );
  }

  Widget _buildHeader(String counterLabel, {Color? counterColor}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
        ),
        Text(counterLabel, style: TextStyle(color: counterColor)),
      ],
    );
  }

  VoidCallback? _entryTap(ScheduleEntry entry) {
    final callback = onTapEntry;
    if (callback == null || entry.routeStepId == null) return null;
    return () => callback(entry);
  }

  IconData _listTileIcon(ScheduleEntry entry) {
    if (entry.routeRole == 'wait_start') {
      return Icons.access_time;
    }
    return switch (entry.itemKind) {
      ScheduleEntryKind.walk => Icons.directions_walk,
      ScheduleEntryKind.goal => Icons.flag,
      _ => Icons.directions_bus,
    };
  }

  String _format24Hour(DateTime dateTime) {
    final hour = dateTime.hour.toString().padLeft(2, '0');
    final minute = dateTime.minute.toString().padLeft(2, '0');
    return '$hour:$minute';
  }
}

class _BoxedScheduleRow extends StatelessWidget {
  final ScheduleEntry entry;
  final bool isActive;
  final String activeLabel;
  final VoidCallback? onTap;

  const _BoxedScheduleRow({
    required this.entry,
    required this.isActive,
    required this.activeLabel,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final timeStr = TimeOfDay.fromDateTime(entry.plannedAt).format(context);
    final label = _categoryLabel(entry.itemKind);
    final pillText = isActive ? activeLabel : label;

    final content = Container(
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
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.08),
                  blurRadius: 6,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: Icon(_categoryIcon(entry), color: Colors.black87),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: isActive
                            ? const Color(0xFF2E7D32)
                            : Colors.black87,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        pillText,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      timeStr,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  entry.label,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                if (entry.description.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    entry.description,
                    style: const TextStyle(color: Colors.black54),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );

    if (onTap == null) return content;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: onTap,
      child: content,
    );
  }

  IconData _categoryIcon(ScheduleEntry entry) {
    if (entry.routeRole == 'wait_start') {
      return CupertinoIcons.clock_fill;
    }
    return switch (entry.itemKind) {
      ScheduleEntryKind.meeting => CupertinoIcons.person_2_fill,
      ScheduleEntryKind.departure => CupertinoIcons.paperplane_fill,
      ScheduleEntryKind.ride => CupertinoIcons.bus,
      ScheduleEntryKind.walk => CupertinoIcons.location,
      ScheduleEntryKind.arrival => CupertinoIcons.checkmark_circle_fill,
      ScheduleEntryKind.goal => CupertinoIcons.flag_fill,
      ScheduleEntryKind.event => CupertinoIcons.calendar_today,
    };
  }

  String _categoryLabel(ScheduleEntryKind kind) {
    return switch (kind) {
      ScheduleEntryKind.meeting => '集合',
      ScheduleEntryKind.departure => '出発',
      ScheduleEntryKind.ride => '移動',
      ScheduleEntryKind.walk => '徒歩',
      ScheduleEntryKind.arrival => '到着',
      ScheduleEntryKind.goal => 'ゴール',
      ScheduleEntryKind.event => '予定',
    };
  }
}

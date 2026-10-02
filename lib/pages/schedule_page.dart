import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../logic/group_schedule_sections.dart';
import '../models/group_models.dart';
import '../services/trip_service.dart';

class SchedulePage extends StatefulWidget {
  final String tripId;
  final bool isLeader;
  final List<ScheduleEntry> initialSchedule;

  const SchedulePage({
    super.key,
    required this.tripId,
    required this.isLeader,
    required this.initialSchedule,
  });

  @override
  State<SchedulePage> createState() => _SchedulePageState();
}

class _SchedulePageState extends State<SchedulePage> {
  late List<ScheduleEntry> _schedule;
  final TripService _tripService = TripService();

  @override
  void initState() {
    super.initState();
    _schedule = List.from(widget.initialSchedule);
    sortScheduleEntries(_schedule);
  }

  GroupScheduleSections get _sections =>
      GroupScheduleSections.fromEntries(_schedule);

  Future<void> _persistSchedule(List<ScheduleEntry> nextSchedule) async {
    sortScheduleEntries(nextSchedule);
    await _tripService.updateSchedule(widget.tripId, nextSchedule);
    if (!mounted) return;
    setState(() {
      _schedule = nextSchedule;
    });
  }

  Future<void> _addScheduleEntry(
    DateTime plannedAt,
    String label,
    String desc,
  ) async {
    final newItem = ScheduleEntry(
      plannedAt: plannedAt,
      label: label,
      description: desc,
      legIndex: 0,
      generatedBy: ScheduleEntrySource.manual,
    );
    final nextSchedule = List<ScheduleEntry>.from(_schedule)..add(newItem);
    await _persistSchedule(nextSchedule);
  }

  Future<void> _editScheduleEntry(
    ScheduleEntry oldItem,
    DateTime plannedAt,
    String label,
    String desc,
  ) async {
    if (oldItem.generatedBy != ScheduleEntrySource.manual) {
      throw StateError(
        'route生成予定はスケジュール画面から編集できません: ${oldItem.id}',
      );
    }

    final index = _schedule.indexWhere((entry) => entry.id == oldItem.id);
    if (index < 0) {
      throw StateError('編集対象の予定が見つかりません: ${oldItem.id}');
    }

    final updated = ScheduleEntry(
      id: oldItem.id,
      plannedAt: plannedAt,
      label: label,
      description: desc,
      itemKind: oldItem.itemKind,
      legIndex: oldItem.legIndex,
      generatedBy: oldItem.generatedBy,
      routeStepId: oldItem.routeStepId,
      routeRole: oldItem.routeRole,
    );

    final nextSchedule = List<ScheduleEntry>.from(_schedule);
    nextSchedule[index] = updated;
    await _persistSchedule(nextSchedule);
  }

  Future<void> _deleteScheduleEntry(ScheduleEntry item) async {
    if (item.generatedBy != ScheduleEntrySource.manual) {
      throw StateError(
        'route生成予定はスケジュール画面から削除できません: ${item.id}',
      );
    }
    final nextSchedule = _schedule
        .where((entry) => entry.id != item.id)
        .toList(growable: true);
    if (nextSchedule.length != _schedule.length - 1) {
      throw StateError('削除対象の予定を一意に特定できません: ${item.id}');
    }
    await _persistSchedule(nextSchedule);
  }

  Future<void> _showScheduleDialog({ScheduleEntry? item}) async {
    final l10n = AppLocalizations.of(context);
    final window = _sections.requireOnsiteWindow();
    final isEditing = item != null;

    if (item != null && item.generatedBy != ScheduleEntrySource.manual) {
      throw StateError(
        'route生成予定は現地予定ダイアログで編集できません: ${item.id}',
      );
    }

    final base = item?.plannedAt ?? window.midpoint;
    var selected = TimeOfDay.fromDateTime(base);
    var label = item?.label ?? '';
    var desc = item?.description ?? '';
    String? validationError;
    var saving = false;

    await showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: Text(
                isEditing
                    ? l10n.groupScheduleEdit
                    : l10n.groupScheduleAdd,
              ),
              content: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      l10n.groupScheduleOnsiteWindow(
                        formatClock(window.start),
                        formatClock(window.end),
                      ),
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 12),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        l10n.groupTimeLabel(selected.format(context)),
                      ),
                      trailing: const Icon(Icons.access_time),
                      onTap: saving
                          ? null
                          : () async {
                              final picked = await showTimePicker(
                                context: context,
                                initialTime: selected,
                              );
                              if (picked != null) {
                                setDialogState(() {
                                  selected = picked;
                                  validationError = null;
                                });
                              }
                            },
                    ),
                    TextFormField(
                      initialValue: label,
                      enabled: !saving,
                      decoration: InputDecoration(
                        labelText: l10n.groupScheduleTitleField,
                      ),
                      onChanged: (value) {
                        label = value;
                        if (validationError != null) {
                          setDialogState(() => validationError = null);
                        }
                      },
                    ),
                    TextFormField(
                      initialValue: desc,
                      enabled: !saving,
                      decoration: InputDecoration(
                        labelText: l10n.groupScheduleDetailsField,
                      ),
                      onChanged: (value) => desc = value,
                    ),
                    if (validationError != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        validationError!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: saving
                      ? null
                      : () => Navigator.pop(dialogContext),
                  child: Text(l10n.cancel),
                ),
                ElevatedButton(
                  onPressed: saving
                      ? null
                      : () async {
                          final normalizedLabel = label.trim();
                          if (normalizedLabel.isEmpty) {
                            setDialogState(() {
                              validationError =
                                  l10n.groupScheduleTitleRequired;
                            });
                            return;
                          }

                          final plannedAt = DateTime(
                            base.year,
                            base.month,
                            base.day,
                            selected.hour,
                            selected.minute,
                          );
                          if (!window.contains(plannedAt)) {
                            setDialogState(() {
                              validationError =
                                  l10n.groupScheduleOnsiteWindowError(
                                    formatClock(window.start),
                                    formatClock(window.end),
                                  );
                            });
                            return;
                          }

                          setDialogState(() => saving = true);
                          if (item == null) {
                            await _addScheduleEntry(
                              plannedAt,
                              normalizedLabel,
                              desc.trim(),
                            );
                          } else {
                            await _editScheduleEntry(
                              item,
                              plannedAt,
                              normalizedLabel,
                              desc.trim(),
                            );
                          }
                          if (dialogContext.mounted) {
                            Navigator.pop(dialogContext);
                          }
                        },
                  child: Text(
                    isEditing ? l10n.settingsSave : l10n.groupAdd,
                  ),
                ),
              ],
            );
          },
        );
      },
    );
  }

  Future<void> _confirmDelete(ScheduleEntry item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          AppLocalizations.of(context).groupScheduleDeleteQuestion,
        ),
        content: Text(
          AppLocalizations.of(
            context,
          ).groupScheduleDeleteDescription(item.label),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: Text(AppLocalizations.of(context).cancel),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(
              AppLocalizations.of(context).delete,
              style: const TextStyle(color: Colors.red),
            ),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _deleteScheduleEntry(item);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sections = _sections;
    return Scaffold(
      appBar: AppBar(title: Text(AppLocalizations.of(context).groupSchedule)),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
        children: [
          _RouteScheduleBlock(
            title: AppLocalizations.of(context).groupOutbound,
            entries: sections.outboundRoute,
          ),
          const SizedBox(height: 18),
          _buildOnsiteSection(context, sections),
          const SizedBox(height: 18),
          _RouteScheduleBlock(
            title: AppLocalizations.of(context).groupInbound,
            entries: sections.inboundRoute,
          ),
          for (final extra in sections.additionalRoutes) ...[
            const SizedBox(height: 18),
            _RouteScheduleBlock(
              title: AppLocalizations.of(
                context,
              ).groupScheduleAdditionalRoute(extra.legIndex + 1),
              entries: extra.entries,
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildOnsiteSection(
    BuildContext context,
    GroupScheduleSections sections,
  ) {
    final l10n = AppLocalizations.of(context);
    final window = sections.requireOnsiteWindow();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          l10n.groupScheduleOnsite,
          style: const TextStyle(
            fontSize: 19,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 3),
        Text(
          l10n.groupScheduleOnsiteWindow(
            formatClock(window.start),
            formatClock(window.end),
          ),
          style: TextStyle(
            fontSize: 13,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 10),
        if (sections.onsiteEntries.isEmpty)
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: 16,
              vertical: 20,
            ),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerLow,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Text(
              l10n.groupScheduleOnsiteEmpty,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          )
        else
          ...sections.onsiteEntries.map(
            (entry) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _OnsiteScheduleCard(
                entry: entry,
                canEdit: widget.isLeader,
                onEdit: () => _showScheduleDialog(item: entry),
                onDelete: () => _confirmDelete(entry),
              ),
            ),
          ),
        if (widget.isLeader) ...[
          const SizedBox(height: 6),
          OutlinedButton.icon(
            onPressed: () => _showScheduleDialog(),
            icon: const Icon(Icons.add),
            label: Text(l10n.groupScheduleAdd),
          ),
        ],
      ],
    );
  }
}

class _RouteScheduleBlock extends StatelessWidget {
  final String title;
  final List<ScheduleEntry> entries;

  const _RouteScheduleBlock({
    required this.title,
    required this.entries,
  });

  @override
  Widget build(BuildContext context) {
    if (entries.isEmpty) {
      return const SizedBox.shrink();
    }

    final l10n = AppLocalizations.of(context);
    final first = entries.first.plannedAt;
    final last = entries.last.plannedAt;

    return Card(
      margin: EdgeInsets.zero,
      elevation: 1,
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        leading: const Icon(Icons.route),
        title: Text(
          title,
          style: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        subtitle: Text(
          l10n.groupScheduleRouteSummary(
            formatClock(first),
            formatClock(last),
            entries.length,
          ),
        ),
        children: [
          const Divider(height: 1),
          for (final entry in entries)
            _RouteScheduleRow(entry: entry),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 6, 16, 14),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                l10n.groupScheduleRouteManaged,
                style: TextStyle(
                  fontSize: 12,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _RouteScheduleRow extends StatelessWidget {
  final ScheduleEntry entry;

  const _RouteScheduleRow({required this.entry});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 50,
            child: Text(
              formatClock(entry.plannedAt),
              style: const TextStyle(
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(entry.label),
                if (entry.description.isNotEmpty)
                  Text(
                    entry.description,
                    style: TextStyle(
                      fontSize: 12,
                      color: Theme.of(
                        context,
                      ).colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _OnsiteScheduleCard extends StatelessWidget {
  final ScheduleEntry entry;
  final bool canEdit;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  const _OnsiteScheduleCard({
    required this.entry,
    required this.canEdit,
    required this.onEdit,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      elevation: 1,
      child: InkWell(
        onTap: canEdit ? onEdit : null,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
          child: Row(
            children: [
              SizedBox(
                width: 52,
                child: Text(
                  formatClock(entry.plannedAt),
                  style: const TextStyle(
                    fontSize: 16,
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
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    if (entry.description.isNotEmpty)
                      Text(
                        entry.description,
                        style: TextStyle(
                          color: Theme.of(
                            context,
                          ).colorScheme.onSurfaceVariant,
                        ),
                      ),
                  ],
                ),
              ),
              if (canEdit) ...[
                IconButton(
                  tooltip: AppLocalizations.of(context).groupScheduleEdit,
                  onPressed: onEdit,
                  icon: const Icon(Icons.edit_outlined),
                ),
                IconButton(
                  tooltip: AppLocalizations.of(context).delete,
                  onPressed: onDelete,
                  icon: const Icon(
                    Icons.delete_outline,
                    color: Colors.red,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import '../core/app_clock.dart';
import '../models/group_models.dart';
import '../services/trip_service.dart';
import '../logic/schedule_resolver.dart';

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
  final Map<String, GlobalKey> _itemKeys = {};
  final TripService _tripService = TripService();

  @override
  void initState() {
    super.initState();
    _schedule = List.from(widget.initialSchedule);
    sortScheduleEntries(_schedule);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _scrollToCurrentTask();
    });
  }

  void _scrollToCurrentTask() {
    final resolved = ScheduleResolver.resolve(
      scheduleSorted: _schedule, 
      now: appClock.now(),
    );
    final activeEntry = resolved.activeEntry;

    if (activeEntry != null) {
      final key = _itemKeys[activeEntry.id];
      if (key?.currentContext != null) {
        Scrollable.ensureVisible(
          key!.currentContext!,
          duration: const Duration(milliseconds: 600),
          curve: Curves.easeInOut,
          alignment: 0.5,
        );
      }
    }
  }

  Future<void> _addScheduleEntry(
    DateTime plannedAt,
    String label,
    String desc,
    int legIndex,
  ) async {
    final newItem = ScheduleEntry(
      plannedAt: plannedAt,
      label: label,
      description: desc,
      legIndex: legIndex,
      generatedBy: ScheduleEntrySource.manual,
    );

    setState(() {
      _schedule.add(newItem);
      sortScheduleEntries(_schedule);
    });

    await _tripService.updateSchedule(widget.tripId, _schedule);
  }

  Future<void> _deleteScheduleEntry(int index) async {
    setState(() {
      _schedule.removeAt(index);
    });
    await _tripService.updateSchedule(widget.tripId, _schedule);
  }

  void _showScheduleDialog({int? index, ScheduleEntry? item}) {
    final isEditing = (index != null && item != null);
    DateTime base = item?.plannedAt ?? (_schedule.isNotEmpty ? _schedule.last.plannedAt : appClock.now());
    TimeOfDay selected = TimeOfDay.fromDateTime(base);
    String label = item?.label ?? '';
    String desc = item?.description ?? '';
    int legIndex = item?.legIndex ?? 0;

    showDialog(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(builder: (context, setStateDialog) {
          return AlertDialog(
            title: Text(isEditing ? '予定を編集' : '予定を追加'),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  ListTile(
                    title: Text('時刻: ${selected.format(context)}'),
                    trailing: const Icon(Icons.access_time),
                    onTap: () async {
                      final picked = await showTimePicker(
                        context: context,
                        initialTime: selected,
                      );
                      if (picked != null) {
                        setStateDialog(() {
                          selected = picked;
                        });
                      }
                    },
                  ),
                  DropdownButtonFormField<int>(
                    value: legIndex,
                    items: const [
                      DropdownMenuItem(value: 0, child: Text('行き')), 
                      DropdownMenuItem(value: 1, child: Text('帰り')),
                    ],
                    onChanged: (v) {
                      if (v != null) setStateDialog(() => legIndex = v);
                    },
                    decoration: const InputDecoration(labelText: 'leg'),
                  ),
                  TextField(
                    decoration: const InputDecoration(labelText: 'タイトル'),
                    controller: TextEditingController(text: label),
                    onChanged: (v) => label = v,
                  ),
                  TextField(
                    decoration: const InputDecoration(labelText: '詳細 (任意)'),
                    controller: TextEditingController(text: desc),
                    onChanged: (v) => desc = v,
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('キャンセル'),
              ),
              ElevatedButton(
                onPressed: () {
                  if (label.isNotEmpty) {
                    final date = DateTime(base.year, base.month, base.day, selected.hour, selected.minute);
                    if (isEditing) {
                      _editScheduleEntry(index!, date, label, desc, legIndex, item!);
                    } else {
                      _addScheduleEntry(date, label, desc, legIndex);
                    }
                    Navigator.pop(ctx);
                  }
                },
                child: Text(isEditing ? '保存' : '追加'),
              ),
            ],
          );
        });
      },
    );
  }

  Future<void> _editScheduleEntry(
    int index,
    DateTime plannedAt,
    String label,
    String desc,
    int legIndex,
    ScheduleEntry oldItem,
  ) async {
    final updated = ScheduleEntry(
      id: oldItem.id, // Keep ID
      plannedAt: plannedAt,
      label: label,
      description: desc,
      itemKind: oldItem.itemKind,
      legIndex: legIndex,
      generatedBy: oldItem.generatedBy,
      locked: oldItem.locked,
    );

    setState(() {
      _schedule[index] = updated;
      sortScheduleEntries(_schedule);
    });

    await _tripService.updateSchedule(widget.tripId, _schedule);
  }

  @override
  Widget build(BuildContext context) {
    final resolved = ScheduleResolver.resolve(
      scheduleSorted: _schedule,
      now: appClock.now(),
    );
    final activeIndex = resolved.activeIndex;

    return Scaffold(
      appBar: AppBar(
        title: const Text('スケジュール'),
        actions: [
          IconButton(
            icon: const Icon(Icons.center_focus_strong),
            tooltip: '現在地へ移動',
            onPressed: _scrollToCurrentTask,
          ),
        ],
      ),
      floatingActionButton: widget.isLeader
          ? FloatingActionButton.extended(
              onPressed: () => _showScheduleDialog(),
              icon: const Icon(Icons.add),
              label: const Text('予定を追加'),
              backgroundColor: Colors.orange,
            )
          : null,
      body: ListView.builder(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 80),
        itemCount: _schedule.length,
        itemBuilder: (context, index) {
          final item = _schedule[index];
          // Determine status based on resolver
          // - Active: index == activeIndex
          // - Completed: index < activeIndex
          // - Future: index > activeIndex
          final isActive = (index == activeIndex);
          final isCompleted = (activeIndex != -1 && index < activeIndex); // If activeIndex is -1 (all future), nothing completed?
                                                                          // Or if activeIndex -1 means NO ACTIVE, wait.
                                                                          // Resolver says: active=-1 if empty. active=0 if all future.
                                                                          // So if active=0, index<0 false. No completion. correct.
          
          if (!_itemKeys.containsKey(item.id)) {
            _itemKeys[item.id] = GlobalKey();
          }

          final cardContent = Card(
            key: _itemKeys[item.id],
            elevation: isActive ? 4 : 1,
            color: isActive
                ? Colors.orange.shade50
                : (isCompleted ? Colors.grey.shade100 : Colors.white),
            shape: isActive
                ? RoundedRectangleBorder(
                    side: const BorderSide(color: Colors.orange, width: 2),
                    borderRadius: BorderRadius.circular(12),
                  )
                : null,
            margin: const EdgeInsets.only(bottom: 12),
            child: InkWell(
              onTap: null, // Removed tap to complete
              onLongPress: widget.isLeader
                  ? () {
                      _showScheduleDialog(index: index, item: item);
                    }
                  : null,
              borderRadius: BorderRadius.circular(12),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    Column(
                      children: [
                        Text(
                          formatClock(item.plannedAt),
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 16,
                            color: isCompleted ? Colors.grey : Colors.black,
                          ),
                        ),
                        if (isActive) ...[
                          const SizedBox(height: 4),
                          Text(resolved.activeLabel, // Use label from resolver
                              style: const TextStyle(
                                  color: Colors.orange,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 10)),
                        ]
                      ],
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            item.label,
                            style: TextStyle(
                              fontSize: isActive ? 18 : 16,
                              fontWeight:
                                  isActive ? FontWeight.bold : FontWeight.normal,
                              color: isCompleted ? Colors.grey : Colors.black,
                              // No strict strikethrough logic requested, but "Finished" look.
                              // User: "Card appearance... active before dim grey... active emphasize... future normal"
                              // "Check mark or strikethrough remove or separate display"
                              // Let's keep strikethrough for completed as visual cue, or remove if user prefers "Shiori reader".
                              // User: "Check mark or strikethrough: Delete OR change to display use"
                              // "Example: Before active is light grey".
                              // I'll stick to color grey for completed and NO strikethrough to make it cleaner "log".
                            ),
                          ),
                          if (item.description.isNotEmpty)
                            Text(
                              item.description,
                              style: TextStyle(
                                  color: isCompleted
                                      ? Colors.grey
                                      : Colors.grey.shade700),
                            ),
                        ],
                      ),
                    ),
                    if (isCompleted)
                      // Small dot or check to indicate past? Or just nothing?
                      // User said "Check mark ... delete".
                      // I will replace with a simple small dot if needed, or nothing.
                      // Let's keep it clean. Just greyed out is enough.
                      const SizedBox.shrink() 
                    else if (isActive)
                      const Icon(Icons.directions_walk, color: Colors.orange)
                    else
                      const Icon(Icons.circle_outlined, color: Colors.grey, size: 12), // Future dot
                  ],
                ),
              ),
            ),
          );

          if (widget.isLeader) {
            return Dismissible(
              key: Key('dismiss_${item.id}'),
              direction: DismissDirection.endToStart,
              background: Container(
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 20),
                color: Colors.red,
                child: const Icon(Icons.delete, color: Colors.white),
              ),
              confirmDismiss: (direction) async {
                return await showDialog(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: const Text('削除しますか？'),
                    content: Text('「${item.label}」をスケジュールから削除します。'),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(ctx, false),
                          child: const Text('キャンセル')),
                      TextButton(
                          onPressed: () => Navigator.pop(ctx, true),
                          child: const Text('削除',
                              style: TextStyle(color: Colors.red))),
                    ],
                  ),
                );
              },
              onDismissed: (direction) {
                _deleteScheduleEntry(index);
              },
              child: cardContent,
            );
          }

          return cardContent;
        },
      ),
    );
  }
}

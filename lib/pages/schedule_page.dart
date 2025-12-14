import 'package:flutter/material.dart';
import '../core/app_clock.dart';
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
  final Map<int, GlobalKey> _itemKeys = {};
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
    int currentIndex = _schedule.indexWhere((item) => !item.isCompleted);
    if (currentIndex == -1 && _schedule.isNotEmpty) {
      currentIndex = _schedule.length - 1;
    } else if (currentIndex == -1) {
      return;
    }

    final key = _itemKeys[currentIndex];
    if (key?.currentContext != null) {
      Scrollable.ensureVisible(
        key!.currentContext!,
        duration: const Duration(milliseconds: 600),
        curve: Curves.easeInOut,
        alignment: 0.5,
      );
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
      plannedAt: plannedAt,
      label: label,
      description: desc,
      itemKind: oldItem.itemKind,
      legIndex: legIndex,
      generatedBy: oldItem.generatedBy,
      locked: oldItem.locked,
      isCompleted: oldItem.isCompleted,
    );

    setState(() {
      _schedule[index] = updated;
      sortScheduleEntries(_schedule);
    });

    await _tripService.updateSchedule(widget.tripId, _schedule);
  }

  @override
  Widget build(BuildContext context) {
    int currentIndex = _schedule.indexWhere((item) => !item.isCompleted);

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
          final isCurrent = (index == currentIndex);
          final isDone = item.isCompleted;

          if (!_itemKeys.containsKey(index)) {
            _itemKeys[index] = GlobalKey();
          }

          final cardContent = Card(
            key: _itemKeys[index],
            elevation: isCurrent ? 4 : 1,
            color: isCurrent
                ? Colors.orange.shade50
                : (isDone ? Colors.grey.shade100 : Colors.white),
            shape: isCurrent
                ? RoundedRectangleBorder(
                    side: const BorderSide(color: Colors.orange, width: 2),
                    borderRadius: BorderRadius.circular(12),
                  )
                : null,
            margin: const EdgeInsets.only(bottom: 12),
            child: InkWell(
              onTap: widget.isLeader
                  ? () async {
                      setState(() {
                        item.isCompleted = !item.isCompleted;
                      });
                      await _tripService.updateSchedule(widget.tripId, _schedule);
                    }
                  : null,
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
                            color: isDone ? Colors.grey : Colors.black,
                          ),
                        ),
                        if (isCurrent) ...[
                          const SizedBox(height: 4),
                          const Text('NOW',
                              style: TextStyle(
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
                              fontSize: isCurrent ? 18 : 16,
                              fontWeight:
                                  isCurrent ? FontWeight.bold : FontWeight.normal,
                              color: isDone ? Colors.grey : Colors.black,
                              decoration:
                                  isDone ? TextDecoration.lineThrough : null,
                            ),
                          ),
                          if (item.description.isNotEmpty)
                            Text(
                              item.description,
                              style: TextStyle(
                                  color: isDone
                                      ? Colors.grey
                                      : Colors.grey.shade700),
                            ),
                        ],
                      ),
                    ),
                    if (isDone)
                      const Icon(Icons.check_circle, color: Colors.green)
                    else if (isCurrent)
                      const Icon(Icons.directions_walk, color: Colors.orange)
                    else
                      const Icon(Icons.radio_button_unchecked,
                          color: Colors.grey),
                  ],
                ),
              ),
            ),
          );

          if (widget.isLeader) {
            return Dismissible(
              key: Key('${item.plannedAt.toIso8601String()}_${item.label}'),
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

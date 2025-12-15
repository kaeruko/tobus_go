import 'package:flutter/material.dart';
import '../core/app_clock.dart'; // Still needed for add dialog datetime
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
    return Scaffold(
      appBar: AppBar(
        title: const Text('スケジュール'),
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
          
          final cardContent = Card(
            elevation: 1,
            color: Colors.white,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
            margin: const EdgeInsets.only(bottom: 12),
            child: InkWell(
              onTap: null, 
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
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 16,
                            color: Colors.black,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            item.label,
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.normal,
                              color: Colors.black,
                            ),
                          ),
                          if (item.description.isNotEmpty)
                            Text(
                              item.description,
                              style: TextStyle(
                                  color: Colors.grey.shade700),
                            ),
                        ],
                      ),
                    ),
                    const Icon(Icons.circle_outlined, color: Colors.grey, size: 12),
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

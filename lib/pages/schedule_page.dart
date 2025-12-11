// lib/pages/schedule_page.dart

import 'package:flutter/material.dart';
import '../models/group_models.dart';
import '../services/group_service.dart';
import '../data/global_state.dart';

class SchedulePage extends StatefulWidget {
  final bool isLeader; // リーダーかメンバーか
  final List<ScheduleItem> initialSchedule;
  
  const SchedulePage({
    super.key,
    this.isLeader = false,
    this.initialSchedule = const [],
  });

  @override
  State<SchedulePage> createState() => _SchedulePageState();
}

class _SchedulePageState extends State<SchedulePage> {
  final _groupService = GroupService();
  late List<ScheduleItem> _schedule;

  @override
  void initState() {
    super.initState();
    _schedule = List.from(widget.initialSchedule);
  }

  // アイコンを取得
  IconData _getIcon(ScheduleType type) {
    switch (type) {
      case ScheduleType.meeting:
        return Icons.people;
      case ScheduleType.departure:
        return Icons.directions_walk;
      case ScheduleType.ride:
        return Icons.directions_bus;
      case ScheduleType.walk:
        return Icons.directions_walk;
      case ScheduleType.arrival:
        return Icons.place;
      case ScheduleType.goal:
        return Icons.flag;
      case ScheduleType.event:
        return Icons.event;
    }
  }

  // 色を取得
  Color _getColor(ScheduleType type) {
    switch (type) {
      case ScheduleType.meeting:
        return Colors.blue;
      case ScheduleType.departure:
        return Colors.green;
      case ScheduleType.ride:
        return Colors.orange;
      case ScheduleType.walk:
        return Colors.teal;
      case ScheduleType.arrival:
        return Colors.purple;
      case ScheduleType.goal:
        return Colors.red;
      case ScheduleType.event:
        return Colors.grey;
    }
  }

  // チェック状態を切り替え
  Future<void> _toggleComplete(int index) async {
    if (kCurrentGroupId == null) return;
    
    setState(() {
      _schedule[index].isCompleted = !_schedule[index].isCompleted;
    });

    // Firestoreに保存
    await _groupService.toggleScheduleItem(
      kCurrentGroupId!,
      index,
      _schedule[index].isCompleted,
    );
  }

  // スケジュールアイテムを追加
  void _addScheduleItem() {
    showDialog(
      context: context,
      builder: (ctx) => _ScheduleItemDialog(
        onSave: (item) {
          setState(() {
            _schedule.add(item);
          });
          _saveSchedule();
        },
      ),
    );
  }

  // スケジュールアイテムを編集
  void _editScheduleItem(int index) {
    showDialog(
      context: context,
      builder: (ctx) => _ScheduleItemDialog(
        item: _schedule[index],
        onSave: (item) {
          setState(() {
            _schedule[index] = item;
          });
          _saveSchedule();
        },
      ),
    );
  }

  // スケジュールアイテムを削除
  void _deleteScheduleItem(int index) {
    setState(() {
      _schedule.removeAt(index);
    });
    _saveSchedule();
  }

  // Firestoreに保存
  Future<void> _saveSchedule() async {
    if (kCurrentGroupId == null) return;
    await _groupService.updateSchedule(kCurrentGroupId!, _schedule);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('スケジュール'),
        actions: widget.isLeader
            ? [
                IconButton(
                  icon: const Icon(Icons.add),
                  onPressed: _addScheduleItem,
                ),
              ]
            : null,
      ),
      body: _schedule.isEmpty
          ? const Center(
              child: Text('スケジュールがありません'),
            )
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: _schedule.length,
              itemBuilder: (context, index) {
                final item = _schedule[index];
                return Card(
                  margin: const EdgeInsets.only(bottom: 12),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: _getColor(item.type),
                      child: Icon(_getIcon(item.type), color: Colors.white),
                    ),
                    title: Row(
                      children: [
                        Text(
                          item.time,
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 16,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            item.title,
                            style: TextStyle(
                              decoration: item.isCompleted
                                  ? TextDecoration.lineThrough
                                  : null,
                            ),
                          ),
                        ),
                      ],
                    ),
                    subtitle: item.description.isNotEmpty
                        ? Text(item.description)
                        : null,
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        // チェックボックス
                        Checkbox(
                          value: item.isCompleted,
                          onChanged: (val) => _toggleComplete(index),
                        ),
                        // リーダーのみ編集・削除可能
                        if (widget.isLeader) ...[
                          IconButton(
                            icon: const Icon(Icons.edit, size: 20),
                            onPressed: () => _editScheduleItem(index),
                          ),
                          IconButton(
                            icon: const Icon(Icons.delete, size: 20),
                            color: Colors.red,
                            onPressed: () => _deleteScheduleItem(index),
                          ),
                        ],
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }
}

// スケジュールアイテム追加・編集ダイアログ
class _ScheduleItemDialog extends StatefulWidget {
  final ScheduleItem? item;
  final Function(ScheduleItem) onSave;

  const _ScheduleItemDialog({
    this.item,
    required this.onSave,
  });

  @override
  State<_ScheduleItemDialog> createState() => _ScheduleItemDialogState();
}

class _ScheduleItemDialogState extends State<_ScheduleItemDialog> {
  late TextEditingController _timeController;
  late TextEditingController _titleController;
  late TextEditingController _descriptionController;
  late ScheduleType _selectedType;

  @override
  void initState() {
    super.initState();
    _timeController = TextEditingController(text: widget.item?.time ?? '');
    _titleController = TextEditingController(text: widget.item?.title ?? '');
    _descriptionController = TextEditingController(text: widget.item?.description ?? '');
    _selectedType = widget.item?.type ?? ScheduleType.event;
  }

  @override
  void dispose() {
    _timeController.dispose();
    _titleController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  void _save() {
    if (_timeController.text.isEmpty || _titleController.text.isEmpty) {
      return;
    }

    final item = ScheduleItem(
      time: _timeController.text,
      title: _titleController.text,
      description: _descriptionController.text,
      type: _selectedType,
      isCompleted: widget.item?.isCompleted ?? false,
    );

    widget.onSave(item);
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.item == null ? 'スケジュール追加' : 'スケジュール編集'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _timeController,
              decoration: const InputDecoration(
                labelText: '時刻 (例: 10:00)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(
                labelText: 'タイトル',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _descriptionController,
              decoration: const InputDecoration(
                labelText: '説明 (オプション)',
                border: OutlineInputBorder(),
              ),
              maxLines: 2,
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<ScheduleType>(
              value: _selectedType,
              decoration: const InputDecoration(
                labelText: 'タイプ',
                border: OutlineInputBorder(),
              ),
              items: ScheduleType.values.map((type) {
                return DropdownMenuItem(
                  value: type,
                  child: Text(_getTypeLabel(type)),
                );
              }).toList(),
              onChanged: (val) {
                if (val != null) {
                  setState(() => _selectedType = val);
                }
              },
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('キャンセル'),
        ),
        ElevatedButton(
          onPressed: _save,
          child: const Text('保存'),
        ),
      ],
    );
  }

  String _getTypeLabel(ScheduleType type) {
    switch (type) {
      case ScheduleType.meeting:
        return '集合';
      case ScheduleType.departure:
        return '出発';
      case ScheduleType.ride:
        return '乗車';
      case ScheduleType.walk:
        return '徒歩';
      case ScheduleType.arrival:
        return '到着';
      case ScheduleType.goal:
        return 'ゴール';
      case ScheduleType.event:
        return 'イベント';
    }
  }
}

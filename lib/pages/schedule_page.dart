import 'package:flutter/material.dart';
import '../models/group_models.dart';
import '../services/trip_service.dart'; // 保存用にインポート

class SchedulePage extends StatefulWidget {
  final String tripId; // ★保存に必要なので追加
  final bool isLeader;
  final List<ScheduleItem> initialSchedule;

  const SchedulePage({
    super.key,
    required this.tripId, // ★追加
    required this.isLeader,
    required this.initialSchedule,
  });

  @override
  State<SchedulePage> createState() => _SchedulePageState();
}

class _SchedulePageState extends State<SchedulePage> {
  late List<ScheduleItem> _schedule;
  final Map<int, GlobalKey> _itemKeys = {};
  final TripService _tripService = TripService(); // サービスインスタンス

  @override
  void initState() {
    super.initState();
    // リストをコピーして変更可能にする
    _schedule = List.from(widget.initialSchedule);
    
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

  // ★ スケジュール追加・保存処理
  Future<void> _addScheduleItem(String time, String title, String desc) async {
    // legIndexを推測する
    int legIndex = 0;
    // 既に帰り(legIndex=1)の予定がある場合、その最小時刻より後なら帰り扱いにする単純ロジック
    final returnItems = _schedule.where((s) => s.legIndex == 1).toList();
    if (returnItems.isNotEmpty) {
      // "00:00"などが混ざると厄介だが、文字列比較で簡易判定
      final minReturnTime = returnItems.map((e) => e.time).reduce((a, b) => a.compareTo(b) < 0 ? a : b);
      if (time.compareTo(minReturnTime) >= 0) {
        legIndex = 1;
      }
    }

    final newItem = ScheduleItem(
      time: time,
      title: title,
      description: desc,
      isCompleted: false,
      legIndex: legIndex,
    );

    setState(() {
      _schedule.add(newItem);
      // legIndex優先、そのあと時刻順
      _schedule.sort((a, b) {
        if (a.legIndex != b.legIndex) {
          return a.legIndex.compareTo(b.legIndex);
        }
        return a.time.compareTo(b.time);
      });
    });

    // Firestore保存
    await _tripService.updateSchedule(widget.tripId, _schedule);
  }

  // ★ スケジュール削除・保存処理
  Future<void> _deleteScheduleItem(int index) async {
    setState(() {
      _schedule.removeAt(index);
    });
    // Firestore保存
    await _tripService.updateSchedule(widget.tripId, _schedule);
  }

  // ★ スケジュール追加・編集ダイアログの表示
  void _showScheduleDialog({int? index, ScheduleItem? item}) {
    final isEditing = (index != null && item != null);
    String time = isEditing
        ? item.time
        : "${DateTime.now().hour.toString().padLeft(2, '0')}:${DateTime.now().minute.toString().padLeft(2, '0')}";
    String title = isEditing ? item.title : "";
    String desc = isEditing ? item.description : "";

    showDialog(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: Text(isEditing ? "予定を編集" : "予定を追加"),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // 時刻選択
                ListTile(
                  title: Text("時刻: $time"),
                  trailing: const Icon(Icons.access_time),
                  onTap: () async {
                    // 現在設定されている時刻を初期値にする
                    final parts = time.split(':');
                    final initHour = int.tryParse(parts[0]) ?? DateTime.now().hour;
                    final initMinute = int.tryParse(parts[1]) ?? DateTime.now().minute;

                    final t = await showTimePicker(
                      context: context,
                      initialTime: TimeOfDay(hour: initHour, minute: initMinute),
                    );
                    if (t != null) {
                      time = "${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}";
                      (ctx as Element).markNeedsBuild(); // 強制再描画
                    }
                  },
                ),
                TextField(
                  decoration: const InputDecoration(labelText: "タイトル (例: 昼食)"),
                  controller: TextEditingController(text: title), // 初期値
                  onChanged: (v) => title = v,
                ),
                TextField(
                  decoration: const InputDecoration(labelText: "詳細 (任意)"),
                  controller: TextEditingController(text: desc), // 初期値
                  onChanged: (v) => desc = v,
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("キャンセル"),
            ),
            ElevatedButton(
              onPressed: () {
                if (title.isNotEmpty) {
                  if (isEditing) {
                    _editScheduleItem(index!, time, title, desc);
                  } else {
                    _addScheduleItem(time, title, desc);
                  }
                  Navigator.pop(ctx);
                }
              },
              child: Text(isEditing ? "保存" : "追加"),
            ),
          ],
        );
      },
    );
  }

  // ★ 既存スケジュールの編集
  Future<void> _editScheduleItem(int index, String time, String title, String desc) async {
    final oldItem = _schedule[index];
    final newItem = ScheduleItem(
      time: time,
      title: title,
      description: desc,
      type: oldItem.type, // タイプは維持
      legIndex: oldItem.legIndex, // legIndexも維持（必要ならここも編集可能にするが一旦維持）
      isCompleted: oldItem.isCompleted,
    );

    setState(() {
      _schedule[index] = newItem;
      // ソートし直し
      _schedule.sort((a, b) {
        if (a.legIndex != b.legIndex) {
          return a.legIndex.compareTo(b.legIndex);
        }
        return a.time.compareTo(b.time);
      });
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
      // ★ リーダーの場合のみ追加ボタンを表示
      floatingActionButton: widget.isLeader
          ? FloatingActionButton.extended(
              onPressed: () => _showScheduleDialog(),
              icon: const Icon(Icons.add),
              label: const Text("予定を追加"),
              backgroundColor: Colors.orange,
            )
          : null,
      
      body: ListView.builder(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 80), // FABとかぶらないように下を空ける
        itemCount: _schedule.length,
        itemBuilder: (context, index) {
          final item = _schedule[index];
          final isCurrent = (index == currentIndex);
          final isDone = item.isCompleted;

          if (!_itemKeys.containsKey(index)) {
            _itemKeys[index] = GlobalKey();
          }

          // カードの中身
          final cardContent = Card(
            key: _itemKeys[index],
            elevation: isCurrent ? 4 : 1,
            color: isCurrent ? Colors.orange.shade50 : (isDone ? Colors.grey.shade100 : Colors.white),
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
                      // 進捗変更も保存
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
                    // 時刻
                    Column(
                      children: [
                        Text(
                          item.time,
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 16,
                            color: isDone ? Colors.grey : Colors.black,
                          ),
                        ),
                        if (isCurrent) ...[
                          const SizedBox(height: 4),
                          const Text("NOW", style: TextStyle(color: Colors.orange, fontWeight: FontWeight.bold, fontSize: 10)),
                        ]
                      ],
                    ),
                    const SizedBox(width: 16),
                    // 内容
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            item.title,
                            style: TextStyle(
                              fontSize: isCurrent ? 18 : 16,
                              fontWeight: isCurrent ? FontWeight.bold : FontWeight.normal,
                              color: isDone ? Colors.grey : Colors.black,
                              decoration: isDone ? TextDecoration.lineThrough : null,
                            ),
                          ),
                          if (item.description.isNotEmpty)
                            Text(
                              item.description,
                              style: TextStyle(color: isDone ? Colors.grey : Colors.grey.shade700),
                            ),
                        ],
                      ),
                    ),
                    // アイコン
                    if (isDone)
                      const Icon(Icons.check_circle, color: Colors.green)
                    else if (isCurrent)
                      const Icon(Icons.directions_walk, color: Colors.orange)
                    else
                      const Icon(Icons.radio_button_unchecked, color: Colors.grey),
                  ],
                ),
              ),
            ),
          );

          // ★ リーダーならスワイプで削除可能にする
          if (widget.isLeader) {
            return Dismissible(
              key: Key("${item.time}_${item.title}"), // 一意なキーが必要
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
                    title: const Text("削除しますか？"),
                    content: Text("「${item.title}」をスケジュールから削除します。"),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("キャンセル")),
                      TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("削除", style: TextStyle(color: Colors.red))),
                    ],
                  ),
                );
              },
              onDismissed: (direction) {
                _deleteScheduleItem(index);
              },
              child: cardContent,
            );
          }

          // リーダーでなければ通常のカードのみ
          return cardContent;
        },
      ),
    );
  }
}
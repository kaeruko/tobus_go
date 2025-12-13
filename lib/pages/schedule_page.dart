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
    final newItem = ScheduleItem(
      time: time,
      title: title,
      description: desc,
      isCompleted: false,
    );

    setState(() {
      _schedule.add(newItem);
      // 時刻順にソート (HH:MM 文字列比較でOK)
      _schedule.sort((a, b) => a.time.compareTo(b.time));
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

  // ★ 追加ダイアログの表示
  void _showAddDialog() {
    String time = "${DateTime.now().hour.toString().padLeft(2, '0')}:${DateTime.now().minute.toString().padLeft(2, '0')}";
    String title = "";
    String desc = "";

    showDialog(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: const Text("予定を追加"),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // 時刻選択
                ListTile(
                  title: Text("時刻: $time"),
                  trailing: const Icon(Icons.access_time),
                  onTap: () async {
                    final t = await showTimePicker(
                      context: context,
                      initialTime: TimeOfDay.now(),
                    );
                    if (t != null) {
                      // ダイアログ内の再描画が必要なためStatefulBuilderを使うか、
                      // 簡易的にNavigatorを閉じて再表示する手もあるが、
                      // ここでは簡易実装として変数を更新するだけにしておく（本来はState管理が必要）
                      // ※ 厳密にやるならこのDialog自体をStatefulWidgetにするのがベスト
                      time = "${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}";
                      (ctx as Element).markNeedsBuild(); // 強制再描画(荒技)
                    }
                  },
                ),
                TextField(
                  decoration: const InputDecoration(labelText: "タイトル (例: 昼食)"),
                  onChanged: (v) => title = v,
                ),
                TextField(
                  decoration: const InputDecoration(labelText: "詳細 (任意)"),
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
                  _addScheduleItem(time, title, desc);
                  Navigator.pop(ctx);
                }
              },
              child: const Text("追加"),
            ),
          ],
        );
      },
    );
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
              onPressed: _showAddDialog,
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
import 'package:flutter/material.dart';
import '../models/group_models.dart';

class SchedulePage extends StatefulWidget {
  final bool isLeader; // リーダーならタップして完了にできる
  final List<ScheduleItem> initialSchedule;

  const SchedulePage({
    super.key,
    required this.isLeader,
    required this.initialSchedule,
  });

  @override
  State<SchedulePage> createState() => _SchedulePageState();
}

class _SchedulePageState extends State<SchedulePage> {
  late List<ScheduleItem> _schedule;
  
  // 自動スクロールのために、各行に「目印（Key）」をつける
  final Map<int, GlobalKey> _itemKeys = {};

  @override
  void initState() {
    super.initState();
    _schedule = widget.initialSchedule;

    // 画面の描画が終わった直後に、自動スクロールを実行
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _scrollToCurrentTask();
    });
  }

  // 「今のタスク」の場所までスクロールする
  void _scrollToCurrentTask() {
    // 完了していない最初のタスクを探す
    int currentIndex = _schedule.indexWhere((item) => !item.isCompleted);
    
    // 全部完了していたら最後尾へ、見つからなければ何もしない
    if (currentIndex == -1 && _schedule.isNotEmpty) {
      currentIndex = _schedule.length - 1;
    } else if (currentIndex == -1) {
      return;
    }

    final key = _itemKeys[currentIndex];
    // そのキーの場所までスクロール
    if (key?.currentContext != null) {
      Scrollable.ensureVisible(
        key!.currentContext!,
        duration: const Duration(milliseconds: 600), // 0.6秒かけて移動
        curve: Curves.easeInOut,
        alignment: 0.5, // 画面の真ん中に持ってくる（0.0なら上端、1.0なら下端）
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    // 現在のタスク（未完了の先頭）のインデックス
    int currentIndex = _schedule.indexWhere((item) => !item.isCompleted);

    return Scaffold(
      appBar: AppBar(
        title: const Text('スケジュール'),
        actions: [
          // 「今ここ」ボタン（手動で戻れるように）
          IconButton(
            icon: const Icon(Icons.center_focus_strong),
            tooltip: '現在地へ移動',
            onPressed: _scrollToCurrentTask,
          ),
        ],
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _schedule.length,
        itemBuilder: (context, index) {
          final item = _schedule[index];
          
          // 今のタスクかどうか
          final isCurrent = (index == currentIndex);
          
          // 完了済みかどうか
          final isDone = item.isCompleted;

          // Keyを生成して登録
          if (!_itemKeys.containsKey(index)) {
            _itemKeys[index] = GlobalKey();
          }

          return Card(
            key: _itemKeys[index], // ここにKeyをセット
            
            // ★見た目の工夫: 現在地なら色と枠線をつける
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
              // リーダーならタップして進捗を切り替えられる（実際はFirestore更新処理が必要）
              onTap: widget.isLeader
                  ? () {
                      setState(() {
                        item.isCompleted = !item.isCompleted;
                      });
                      // TODO: ここで TripService().toggleScheduleItem(...) を呼ぶ
                    }
                  : null,
              borderRadius: BorderRadius.circular(12),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    // 1. 左側：時刻
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
                    
                    // 2. 真ん中：内容
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
                    
                    // 3. 右側：アイコン
                    if (isDone)
                      const Icon(Icons.check_circle, color: Colors.green)
                    else if (isCurrent)
                      const Icon(Icons.directions_walk, color: Colors.orange) // 進行中アイコン
                    else
                      const Icon(Icons.radio_button_unchecked, color: Colors.grey),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

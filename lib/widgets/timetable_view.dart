import 'package:flutter/material.dart';
import 'dart:async'; // 時計更新用
import '../services/timetable_service.dart'; // さっき作ったファイル

class TimetableView extends StatefulWidget {
  final String routeId;
  final String stopId;

  const TimetableView({
    super.key,
    required this.routeId,
    required this.stopId,
  });

  @override
  State<TimetableView> createState() => _TimetableViewState();
}

class _TimetableViewState extends State<TimetableView> {
  final TimetableService _service = TimetableService();
  List<String> _nextBuses = [];
  String _dayType = "";
  DateTime _now = DateTime.now();
  Timer? _timer;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _initData();
    
    // 1分ごとに画面を更新して「次のバス」を最新にする
    _timer = Timer.periodic(const Duration(minutes: 1), (timer) {
      setState(() {
        _now = DateTime.now();
        _updateBusInfo();
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _initData() async {
    await _service.loadTimetable();
    if (mounted) {
      setState(() {
        _dayType = _service.getTodayType();
        _isLoading = false;
        _updateBusInfo();
      });
    }
  }

  void _updateBusInfo() {
    // ウィジェットに渡されたIDを使って検索
    _nextBuses = _service.getNextBuses(widget.routeId, widget.stopId);
  }

  @override
  Widget build(BuildContext context) {
    // 曜日を日本語表記にする用
    final dayTypeJa = {
      'Weekday': '平日',
      'Saturday': '土曜',
      'Holiday': '休日'
    }[_dayType] ?? _dayType;

    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    // Cardの中に入れるので、ここでのCardは削除してContainerやColumnだけにする
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // ヘッダー (文字サイズを小さめに)
        Row(
          children: [
            Icon(Icons.timer, size: 16, color: Colors.grey[600]),
            const SizedBox(width: 4),
            Text(
              "次のバス ($dayTypeJaダイヤ)",
              style: TextStyle(fontSize: 14, color: Colors.grey[600]),
            ),
            const Spacer(),
            // 現在時刻
            Text(
              "現在 ${testTimeFormat(_now)}",
              style: TextStyle(fontSize: 14, color: Colors.grey[600]),
            ),
          ],
        ),
        const SizedBox(height: 8),
        
        // 時刻リスト (横並びで見やすく)
        if (_nextBuses.isEmpty)
          const Text("本日の運行終了", style: TextStyle(fontWeight: FontWeight.bold))
        else
          Row(
            children: _nextBuses.map((time) {
              final isFirst = time == _nextBuses.first;
              return Container(
                margin: const EdgeInsets.only(right: 12.0),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: isFirst ? BoxDecoration(
                  color: Colors.green[100], // 先頭だけ色をつける
                  borderRadius: BorderRadius.circular(4),
                ) : null,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Text(
                      time,
                      style: TextStyle(
                        fontSize: isFirst ? 20 : 16, // サイズ調整
                        fontWeight: FontWeight.bold,
                        color: isFirst ? Colors.green[900] : Colors.black87,
                      ),
                    ),
                    if (isFirst) ...[
                      const SizedBox(width: 2),
                      const Text("発", style: TextStyle(fontSize: 10, color: Colors.green)),
                    ]
                  ],
                ),
              );
            }).toList(),
          ),
      ],
    );
  }

  String testTimeFormat(DateTime dt) {
    return "${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}";
  }
}
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

    return Card(
      margin: const EdgeInsets.all(16.0),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ヘッダー部分（時刻と曜日）
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  "現在 ${testTimeFormat(_now)}",
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _dayType == 'Weekday' ? Colors.blue[100] : Colors.red[100],
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    "$dayTypeJaダイヤ",
                    style: TextStyle(
                      color: _dayType == 'Weekday' ? Colors.blue[800] : Colors.red[800],
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            const Text("【次のバス】", style: TextStyle(color: Colors.grey)),
            const SizedBox(height: 8),
            
            // バス時刻リスト表示
            if (_nextBuses.isEmpty)
              const Text("本日の運行は終了しました", style: TextStyle(fontSize: 16))
            else
              Row(
                children: _nextBuses.map((time) {
                  // 先頭だけ大きく強調表示
                  final isFirst = time == _nextBuses.first;
                  return Padding(
                    padding: const EdgeInsets.only(right: 16.0),
                    child: Text(
                      time,
                      style: TextStyle(
                        fontSize: isFirst ? 32 : 20,
                        fontWeight: FontWeight.bold,
                        color: isFirst ? Colors.black : Colors.black54,
                      ),
                    ),
                  );
                }).toList(),
              ),
          ],
        ),
      ),
    );
  }

  String testTimeFormat(DateTime dt) {
    return "${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}";
  }
}
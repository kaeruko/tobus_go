import 'package:flutter/material.dart';
import 'dart:async';
import '../core/app_clock.dart';
import '../l10n/app_localizations.dart';
import '../services/timetable_service.dart';

class TimetableView extends StatefulWidget {
  final String routeId;
  final String stopId;
  final String? targetPoleId; // 追加

  const TimetableView({
    super.key,
    required this.routeId,
    required this.stopId,
    this.targetPoleId,
  });

  @override
  State<TimetableView> createState() => _TimetableViewState();
}

class _TimetableViewState extends State<TimetableView> {
  final TimetableService _service = TimetableService();
  
  // 構造: [ {"destinationName": "上野行き", "times": ["12:10", "12:30"]}, ... ]
  List<Map<String, dynamic>> _busGroups = [];

  String _dayType = "";
  DateTime _now = appClock.now();
  Timer? _timer;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _initData();
    _timer = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted) {
        setState(() {
          _now = appClock.now();
          _updateBusInfo();
        });
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _initData() async {
    // API版ではloadTimetable不要だが、念のため呼んでおくか、あるいは不要なら削除
    // await _service.loadTimetable(); 
    if (mounted) {
      setState(() {
        _dayType = _service.getTodayType();
        _inputDate(); // APIからデータ取得
      });
    }
  }

  Future<void> _inputDate() async {
    setState(() => _isLoading = true);
    await _updateBusInfo();
    if (mounted) {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _updateBusInfo() async {
    // 変更点: API版のメソッドを非同期で呼ぶ
    final groups = await _service.getNextBusesFromApi(widget.routeId, widget.stopId, targetPoleId: widget.targetPoleId);
    if (mounted) {
      setState(() {
         _busGroups = groups;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (_isLoading) return const SizedBox.shrink();

    final dayTypeLabel = switch (_dayType) {
      'Weekday' => l10n.dayWeekday,
      'Saturday' => l10n.daySaturday,
      'Holiday' => l10n.dayHoliday,
      _ => throw StateError('Unsupported timetable day type: $_dayType'),
    };
    if (_busGroups.isEmpty) {
      // データがない場合は何も表示しない（あるいは運行終了を表示）
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 全体のヘッダー
        Row(
          children: [
            Icon(Icons.access_time, size: 14, color: Colors.grey[600]),
            const SizedBox(width: 4),
            Text(
              l10n.nextBus(dayTypeLabel),
              style: TextStyle(fontSize: 12, color: Colors.grey[600]),
            ),
          ],
        ),
        const SizedBox(height: 4),
        
        // 行き先ごとにリストを表示
        ..._busGroups.map((group) {
          final destName = group['destinationName'] as String;
          final times = group['times'] as List<String>;
          
          return Padding(
            padding: const EdgeInsets.only(bottom: 8.0),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                // 行き先名バッジ
                Container(
                  constraints: const BoxConstraints(maxWidth: 100), // 幅制限
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.blue[50],
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: Colors.blue[100]!),
                  ),
                  child: Text(
                    destName,
                    style: TextStyle(fontSize: 11, color: Colors.blue[900], fontWeight: FontWeight.bold),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 8),
                
                // 時刻リスト
                Expanded(
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: times.map((t) {
                        final isFirst = t == times.first;
                        return Padding(
                          padding: const EdgeInsets.only(right: 8.0),
                          child: Text(
                            t,
                            style: TextStyle(
                              fontSize: isFirst ? 16 : 14,
                              fontWeight: FontWeight.bold,
                              color: isFirst ? Colors.black87 : Colors.grey[500],
                            ),
                          ),
                        );
                      }).toList(),
                    ),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ],
    );
  }
}
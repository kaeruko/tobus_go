import 'dart:convert';
import 'package:flutter/services.dart';

class TimetableService {
  Map<String, dynamic>? _timetableData;

  // JSONファイルを読み込む
  Future<void> loadTimetable() async {
    // すでに読み込み済みなら何もしない
    if (_timetableData != null) return;
    
    try {
      final jsonString = await rootBundle.loadString('assets/data/app_timetable.json');
      _timetableData = json.decode(jsonString);
    } catch (e) {
      print("時刻表の読み込みに失敗したよ: $e");
      _timetableData = {};
    }
  }

  // 今日の曜日タイプを判定する (Weekday, Saturday, Holiday)
  String getTodayType() {
    final now = DateTime.now();
    
    // 単純な曜日判定（必要なら祝日判定ライブラリを入れてね）
    if (now.weekday == DateTime.sunday) return "Holiday";
    if (now.weekday == DateTime.saturday) return "Saturday";
    return "Weekday";
  }

  // 現在時刻と曜日をもとに、次のバス3本を取得する
  List<String> getNextBuses(String routeId, String stopId) {
    if (_timetableData == null) return [];

    final dayType = getTodayType();
    
    // JSONの階層をたどって時刻リストを取得
    // 例: data["RouteA"]["Stop1"]["Weekday"]
    final routeData = _timetableData![routeId];
    if (routeData == null) return [];
    
    final stopData = routeData[stopId];
    if (stopData == null) return [];

    final List<dynamic>? rawTimes = stopData[dayType];
    if (rawTimes == null || rawTimes.isEmpty) return [];

    // dynamicリストをStringリストに変換
    final times = rawTimes.cast<String>();

    // 現在時刻を取得して "HH:mm" 形式にする
    final now = DateTime.now();
    var hour = now.hour;
    final minute = now.minute;

    // バスの時刻表は深夜25時などの表記があるため、0~3時は24を足して調整する
    if (hour < 3) {
      hour += 24;
    }

    final currentStr = "${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}";

    // 現在時刻より未来のものをフィルタリングして、先頭3つを返す
    final nextTimes = times.where((t) => t.compareTo(currentStr) >= 0).take(3).toList();

    return nextTimes;
  }
}
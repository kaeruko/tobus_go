import 'dart:convert';
import 'package:flutter/services.dart';

class TimetableService {
  // シングルトンパターン（アプリ内で1つだけインスタンスを作る）
  static final TimetableService _instance = TimetableService._internal();
  factory TimetableService() => _instance;
  TimetableService._internal();

  // データキャッシュ
  Map<String, dynamic>? _timetableData;
  Map<String, dynamic>? _directionNames; // route_directions.json用

  Future<void> loadTimetable() async {
    if (_timetableData != null) return;

    try {
      // 1. 時刻表データの読み込み
      final jsonString = await rootBundle.loadString('assets/data/app_timetable.json');
      _timetableData = json.decode(jsonString);
    } catch (e) {
      print("時刻表JSONの読み込み失敗: $e");
      _timetableData = {};
    }

    try {
      // 2. 行き先名リストの読み込み (作成した route_directions.json)
      final dirString = await rootBundle.loadString('assets/data/route_directions.json');
      _directionNames = json.decode(dirString);
    } catch (e) {
      print("行き先リストの読み込み失敗 (まだファイルがないかも?): $e");
      _directionNames = {};
    }
  }

  String getTodayType() {
    final now = DateTime.now();
    // 祝日判定ロジックは別途必要ですが、まずは簡易的に土日判定
    if (now.weekday == DateTime.sunday) return "Holiday";
    if (now.weekday == DateTime.saturday) return "Saturday";
    return "Weekday";
  }

  // 指定された系統・バス停における、全方向の次のバスを取得する
  // 戻り値: [ { "directionId": "1", "name": "上野行き", "times": ["12:14", ...] }, ... ]
  List<Map<String, dynamic>> getNextBusesAllDirections(String routeId, String stopId) {
    print('[TimetableService] getNextBusesAllDirections呼び出し:');
    print('  - routeId: $routeId');
    print('  - stopId: $stopId');
    
    if (_timetableData == null) {
      print('  - エラー: _timetableData is null');
      return [];
    }

    final dayType = getTodayType();
    print('  - dayType: $dayType');
    
    final routeData = _timetableData![routeId];
    if (routeData == null) {
      print('  - エラー: routeId "$routeId" がapp_timetable.jsonに存在しません');
      print('  - 利用可能なrouteId: ${_timetableData!.keys.take(5).join(", ")}...');
      return [];
    }

    final stopData = routeData[stopId]; // ここには方向ID (0, 1) がキーとして入っている
    if (stopData == null || stopData is! Map) {
      print('  - エラー: stopId "$stopId" がroute "$routeId" に存在しません');
      print('  - 利用可能なstopId: ${routeData.keys.take(5).join(", ")}...');
      return [];
    }

    print('  - stopDataの方向ID: ${stopData.keys.join(", ")}');
    
    // 現在時刻の準備
    final now = DateTime.now();
    var hour = now.hour;
    if (hour < 3) hour += 24; // 25時対応
    final currentStr = "${hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}";

    List<Map<String, dynamic>> results = [];

    // 存在するすべての方向 (0, 1など) についてループ
    stopData.forEach((directionId, dayMap) {
      if (dayMap is! Map) return;
      
      // その方向の、今日のダイヤを取得
      final rawTimes = dayMap[dayType];
      if (rawTimes != null && rawTimes is List) {
        final times = rawTimes.cast<String>();
        
        // 未来のバスを3本抽出
        final nextTimes = times.where((t) => t.compareTo(currentStr) >= 0).take(3).toList();

        if (nextTimes.isNotEmpty) {
          // 行き先名を取得 (例: "上野松坂屋前")
          String headsign = "方面$directionId"; // デフォルト
          if (_directionNames != null && 
              _directionNames![routeId] != null &&
              _directionNames![routeId][directionId] != null) {
            headsign = _directionNames![routeId][directionId];
          }

          results.add({
            "directionId": directionId,
            "destinationName": headsign,
            "times": nextTimes,
          });
        }
      }
    });

    return results;
  }
}
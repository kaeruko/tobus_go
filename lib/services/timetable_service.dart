import 'dart:convert';
import 'package:flutter/services.dart';
import '../core/app_clock.dart';
import '../core/api_client.dart';

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
    final now = appClock.now();
    // 祝日判定ロジックは別途必要ですが、まずは簡易的に土日判定
    if (now.weekday == DateTime.sunday) return "Holiday";
    if (now.weekday == DateTime.saturday) return "Saturday";
    return "Weekday";
  }

  // 指定された系統・バス停における、全方向の次のバスを取得する (API版)
  // 戻り値: [ { "directionId": "1", "name": "上野行き", "times": ["12:14", ...] }, ... ]
  Future<List<Map<String, dynamic>>> getNextBusesFromApi(String routeId, String poleId, {String? targetPoleId}) async {
    if (routeId.trim().isEmpty || poleId.trim().isEmpty) {
      return [];
    }
    print('[TimetableService] getNextBusesFromApi呼び出し:');
    print('  - routeId: $routeId');
    print('  - poleId: $poleId');
    print('  - targetPoleId: $targetPoleId');

    try {
      final params = {
        'pole_id': poleId,
        'route_id': routeId,
        'limit': '3',
        'debug': 'true',
      };
      if (targetPoleId != null && targetPoleId.isNotEmpty) {
        params['target_pole_id'] = targetPoleId;
      }

      final json = await ApiClient.get('/bus/next', params: params);
      final destinations = json['destinations'] as List?;
      if (destinations == null) return [];

      List<Map<String, dynamic>> results = [];
      for (var dest in destinations) {
        if (dest is! Map) continue;
        final name = dest['destination_name']?.toString() ?? '行き先不明';
        final times = (dest['times'] as List?)?.map((e) => e.toString()).toList() ?? [];

        if (times.isNotEmpty) {
          results.add({
            "destinationName": name,
            "times": times,
          });
        }
      }
      return results;

    } catch (e) {
      print('[TimetableService] API呼び出し失敗: $e');
      return [];
    }
  }

  // 指定された系統・バス停における、全方向の次のバスを取得する (ローカル版 - 旧)
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
    final now = appClock.now();
    var hour = now.hour;
    if (hour < 3) hour += 24; // 25時対応
    final currentStr = "${hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}";

    List<Map<String, dynamic>> results = [];

    // 存在するすべての方向 (0, 1など) についてループ
    stopData.forEach((directionId, dayMap) {
      if (dayMap is! Map) return;
      
      // その方向の、今日のダイヤを取得
      // 変更: 新しい構造は [ {"destination": "...", "times": [...]}, ... ]
      final rawData = dayMap[dayType];
      
      if (rawData != null && rawData is List) {
        for (var group in rawData) {
          if (group is! Map) continue;
          if (!group.containsKey('destination') || !group.containsKey('times')) continue;

          final destination = group['destination'] as String;
          final times = (group['times'] as List).cast<String>();
          
          // 未来のバスを3本抽出
          final nextTimes = times.where((t) => t.compareTo(currentStr) >= 0).take(3).toList();

          if (nextTimes.isNotEmpty) {
            results.add({
              "directionId": directionId,
              "destinationName": destination, // data/route_directions.jsonよりも、JSON内の具体的な行き先を優先
              "times": nextTimes,
            });
          }
        }
      }
    });

    return results;
  }
}

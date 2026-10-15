import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../constants.dart';
import '../core/city_profile.dart';
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

  // The API may use realtime delays to select "upcoming" departures.
  // Only allTimes (the fixed daily schedule) is persisted here.
  static const _fixedSchedulePrefix = 'bus_static_schedule_v1:';
  static const _fixedScheduleLifetime = Duration(hours: 24);
  final Map<String, Future<_SavedBusSchedule>> _pendingFixedSchedules = {};

  /// Persist a static timetable across page visits and app restarts.
  /// Calendar date, direction, city, API endpoint and all source IDs are scoped
  /// independently. This cache never holds live vehicles or predicted delays.
  Future<List<Map<String, dynamic>>> getSavedFullDayBusesFromApi(
    String routeId,
    String poleId, {
    String? targetPoleId,
    String? patternTripId,
    String? preferredPatternTripId,
    bool includeStopCluster = false,
    String? dayType,
    DateTime? referenceTime,
    int limit = 3,
    void Function(String dayType)? onResolvedDayType,
  }) async {
    if (routeId.trim().isEmpty || poleId.trim().isEmpty) {
      throw ArgumentError('Static timetable requires routeId and poleId');
    }
    if (limit < 1) {
      throw ArgumentError.value(limit, 'limit', 'must be at least 1');
    }
    if (dayType != null &&
        !const {'Weekday', 'Saturday', 'Holiday'}.contains(dayType)) {
      throw ArgumentError.value(dayType, 'dayType', 'unsupported day type');
    }

    final time = referenceTime ?? appClock.now();
    final selector = dayType == null
        ? 'date:' + time.year.toString().padLeft(4, '0') + '-' +
            time.month.toString().padLeft(2, '0') + '-' +
            time.day.toString().padLeft(2, '0')
        : 'day:$dayType';
    final key = _fixedSchedulePrefix + jsonEncode([
      kApiBase, configuredCityKey, selector, routeId, poleId, targetPoleId,
      patternTripId, preferredPatternTripId, includeStopCluster, limit,
    ]);
    final preferences = await SharedPreferences.getInstance();
    final cached = preferences.getString(key);
    if (cached != null) {
      final entry = _SavedBusSchedule.decode(cached);
      final age = DateTime.now().millisecondsSinceEpoch - entry.savedAtMillis;
      if (age >= 0 && age < _fixedScheduleLifetime.inMilliseconds) {
        if (dayType != null && entry.dayType != dayType) {
          throw const FormatException('Cached timetable day type mismatch');
        }
        onResolvedDayType?.call(entry.dayType);
        return _scheduledUpcoming(entry.groups, time, limit);
      }
      await preferences.remove(key);
    }

    final pending = _pendingFixedSchedules.putIfAbsent(key, () async {
      String? resolved;
      final groups = await getNextBusesFromApi(
        routeId,
        poleId,
        targetPoleId: targetPoleId,
        patternTripId: patternTripId,
        preferredPatternTripId: preferredPatternTripId,
        includeStopCluster: includeStopCluster,
        dayType: dayType,
        referenceTime: time,
        limit: limit,
        includeAllDay: true,
        onResolvedDayType: (value) => resolved = value,
      );
      if (resolved == null) {
        throw StateError('Full-day timetable is missing its service-day type');
      }
      _scheduledUpcoming(groups, time, limit); // Validate before persisting.
      final entry = _SavedBusSchedule(
        savedAtMillis: DateTime.now().millisecondsSinceEpoch,
        dayType: resolved!,
        groups: groups,
      );
      if (!await preferences.setString(key, entry.encode())) {
        throw StateError('Could not persist the static bus timetable');
      }
      return entry;
    });
    try {
      final entry = await pending;
      onResolvedDayType?.call(entry.dayType);
      return _scheduledUpcoming(entry.groups, time, limit);
    } finally {
      if (identical(_pendingFixedSchedules[key], pending)) {
        _pendingFixedSchedules.remove(key);
      }
    }
  }

  List<Map<String, dynamic>> _scheduledUpcoming(
    List<Map<String, dynamic>> groups,
    DateTime referenceTime,
    int limit,
  ) {
    var hour = referenceTime.hour;
    if (hour < 3) hour += 24;
    final currentMinute = hour * 60 + referenceTime.minute;
    return [
      for (final group in groups)
        {
          ...group,
          'times': _checkedFullDayTimes(group)
              .where((value) => _scheduledMinute(value) >= currentMinute)
              .take(limit)
              .toList(),
        },
    ];
  }

  static List<String> _checkedFullDayTimes(Map<String, dynamic> group) {
    final times = group['allTimes'];
    if (times is! List || times.any((value) => value is! String)) {
      throw const FormatException('Full-day timetable requires string allTimes');
    }
    final typed = times.cast<String>();
    for (final value in typed) {
      _scheduledMinute(value);
    }
    return typed;
  }

  static int _scheduledMinute(String text) {
    final match = RegExp(r'^(\d{1,2}):([0-5]\d)  // 戻り値: [ { "directionId": "1", "name": "上野行き", "times": ["12:14", ...] }, ... ]
  Future<List<Map<String, dynamic>>> getNextBusesFromApi(
    String routeId,
    String poleId, {
    String? targetPoleId,
    String? patternTripId,
    String? preferredPatternTripId,
    bool includeStopCluster = false,
    String? dayType,
    DateTime? referenceTime,
    int limit = 3,
    bool includeAllDay = false,
    void Function(String dayType)? onResolvedDayType,
  }) async {
    if (routeId.trim().isEmpty) {
      throw ArgumentError.value(routeId, 'routeId', 'must not be empty');
    }
    if (poleId.trim().isEmpty) {
      throw ArgumentError.value(poleId, 'poleId', 'must not be empty');
    }
    if (limit < 1) {
      throw ArgumentError.value(limit, 'limit', 'must be at least 1');
    }
    const supportedDayTypes = {'Weekday', 'Saturday', 'Holiday'};
    if (dayType != null && !supportedDayTypes.contains(dayType)) {
      throw ArgumentError.value(
        dayType,
        'dayType',
        'must be Weekday, Saturday, or Holiday',
      );
    }

    print('[TimetableService] getNextBusesFromApi呼び出し:');
    print('  - routeId: $routeId');
    print('  - poleId: $poleId');
    print('  - targetPoleId: $targetPoleId');
    print('  - patternTripId: $patternTripId');
    print('  - preferredPatternTripId: $preferredPatternTripId');
    print('  - includeStopCluster: $includeStopCluster');
    print('  - dayType: $dayType');
    print('  - includeAllDay: $includeAllDay');

    final effectiveReferenceTime = referenceTime ?? appClock.now();
    final params = {
      'pole_id': poleId,
      'route_id': routeId,
      'time':
          '${effectiveReferenceTime.hour.toString().padLeft(2, '0')}:'
          '${effectiveReferenceTime.minute.toString().padLeft(2, '0')}',
      'limit': '$limit',
      'debug': 'true',
    };
    if (dayType == null) {
      params['date'] =
          '${effectiveReferenceTime.year.toString().padLeft(4, '0')}-'
          '${effectiveReferenceTime.month.toString().padLeft(2, '0')}-'
          '${effectiveReferenceTime.day.toString().padLeft(2, '0')}';
    }
    if (targetPoleId != null && targetPoleId.isNotEmpty) {
      params['target_pole_id'] = targetPoleId;
    }
    if (patternTripId != null && patternTripId.isNotEmpty) {
      params['pattern_trip_id'] = patternTripId;
    }
    if (preferredPatternTripId != null && preferredPatternTripId.isNotEmpty) {
      params['preferred_pattern_trip_id'] = preferredPatternTripId;
    }
    if (includeStopCluster) {
      params['include_stop_cluster'] = 'true';
    }
    if (dayType != null) {
      params['day_type'] = dayType.toLowerCase();
    }
    if (includeAllDay) {
      params['include_all'] = 'true';
    }

    final json = await ApiClient.get('/bus/next', params: params);
    // An explicit date is authoritative. Use the backend's calendar result
    // instead of guessing Japanese holidays from DateTime.weekday.
    if (onResolvedDayType != null) {
      final responseDayType = json['day_type'];
      if (responseDayType is! String ||
          !const {'weekday', 'saturday', 'holiday'}.contains(responseDayType)) {
        throw FormatException(
          'Invalid /bus/next day_type: $responseDayType '
          '(routeId=$routeId, poleId=$poleId, referenceTime=$effectiveReferenceTime)',
        );
      }
      final resolvedDayType = switch (responseDayType) {
        'weekday' => 'Weekday',
        'saturday' => 'Saturday',
        'holiday' => 'Holiday',
        _ => throw StateError('Unreachable day_type: $responseDayType'),
      };
      if (dayType != null && resolvedDayType != dayType) {
        throw StateError(
          'Timetable day type mismatch: requested=$dayType, '
          'resolved=$resolvedDayType, routeId=$routeId, poleId=$poleId',
        );
      }
      onResolvedDayType(resolvedDayType);
    }
    final destinations = json['destinations'];
    if (destinations is! List) {
      throw StateError(
        'Invalid /bus/next response: destinations must be a list',
      );
    }

    final results = <Map<String, dynamic>>[];
    for (final dest in destinations) {
      if (dest is! Map) {
        throw StateError(
          'Invalid /bus/next response: destination must be an object',
        );
      }
      final rawName = dest['destination_name'];
      if (rawName == null || rawName.toString().trim().isEmpty) {
        throw StateError(
          'Invalid /bus/next response: destination_name is required',
        );
      }
      final name = rawName.toString();
      final destinationPoleId = dest['destination_pole_id']?.toString();
      final rawNameEn = dest['destination_name_en'];
      if (rawNameEn == null || rawNameEn.toString().trim().isEmpty) {
        throw StateError(
          'Invalid /bus/next response: destination_name_en is required: '
          'destinationPoleId=${destinationPoleId ?? '<unknown>'}',
        );
      }
      final nameEn = rawNameEn.toString().trim();
      final rawTimes = dest['times'];
      if (rawTimes is! List) {
        throw StateError(
          'Invalid /bus/next response: times must be a list',
        );
      }
      final times = rawTimes.map((e) => e.toString()).toList();
      final rawAllTimes = dest['all_times'];
      if (includeAllDay && rawAllTimes is! List) {
        throw StateError(
          'Invalid /bus/next response: all_times must be a list',
        );
      }
      final allTimes = rawAllTimes is List
          ? rawAllTimes.map((e) => e.toString()).toList()
          : const <String>[];

      if (times.isNotEmpty || allTimes.isNotEmpty) {
        results.add({
          'destinationName': name,
          'destinationNameEn': nameEn,
          'destinationPoleId': destinationPoleId,
          'times': times,
          'allTimes': allTimes,
        });
      }
    }
    return results;
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
).firstMatch(text);
    if (match == null) {
      throw FormatException('Invalid static timetable clock: $text');
    }
    final hour = int.parse(match.group(1)!);
    if (hour > 47) {
      throw FormatException('Invalid static timetable hour: $text');
    }
    return hour * 60 + int.parse(match.group(2)!);
  }

  // 指定された系統・バス停における、全方向の次のバスを取得する (API版)
  // 戻り値: [ { "directionId": "1", "name": "上野行き", "times": ["12:14", ...] }, ... ]
  Future<List<Map<String, dynamic>>> getNextBusesFromApi(
    String routeId,
    String poleId, {
    String? targetPoleId,
    String? patternTripId,
    String? preferredPatternTripId,
    bool includeStopCluster = false,
    String? dayType,
    DateTime? referenceTime,
    int limit = 3,
    bool includeAllDay = false,
    void Function(String dayType)? onResolvedDayType,
  }) async {
    if (routeId.trim().isEmpty) {
      throw ArgumentError.value(routeId, 'routeId', 'must not be empty');
    }
    if (poleId.trim().isEmpty) {
      throw ArgumentError.value(poleId, 'poleId', 'must not be empty');
    }
    if (limit < 1) {
      throw ArgumentError.value(limit, 'limit', 'must be at least 1');
    }
    const supportedDayTypes = {'Weekday', 'Saturday', 'Holiday'};
    if (dayType != null && !supportedDayTypes.contains(dayType)) {
      throw ArgumentError.value(
        dayType,
        'dayType',
        'must be Weekday, Saturday, or Holiday',
      );
    }

    print('[TimetableService] getNextBusesFromApi呼び出し:');
    print('  - routeId: $routeId');
    print('  - poleId: $poleId');
    print('  - targetPoleId: $targetPoleId');
    print('  - patternTripId: $patternTripId');
    print('  - preferredPatternTripId: $preferredPatternTripId');
    print('  - includeStopCluster: $includeStopCluster');
    print('  - dayType: $dayType');
    print('  - includeAllDay: $includeAllDay');

    final effectiveReferenceTime = referenceTime ?? appClock.now();
    final params = {
      'pole_id': poleId,
      'route_id': routeId,
      'time':
          '${effectiveReferenceTime.hour.toString().padLeft(2, '0')}:'
          '${effectiveReferenceTime.minute.toString().padLeft(2, '0')}',
      'limit': '$limit',
      'debug': 'true',
    };
    if (dayType == null) {
      params['date'] =
          '${effectiveReferenceTime.year.toString().padLeft(4, '0')}-'
          '${effectiveReferenceTime.month.toString().padLeft(2, '0')}-'
          '${effectiveReferenceTime.day.toString().padLeft(2, '0')}';
    }
    if (targetPoleId != null && targetPoleId.isNotEmpty) {
      params['target_pole_id'] = targetPoleId;
    }
    if (patternTripId != null && patternTripId.isNotEmpty) {
      params['pattern_trip_id'] = patternTripId;
    }
    if (preferredPatternTripId != null && preferredPatternTripId.isNotEmpty) {
      params['preferred_pattern_trip_id'] = preferredPatternTripId;
    }
    if (includeStopCluster) {
      params['include_stop_cluster'] = 'true';
    }
    if (dayType != null) {
      params['day_type'] = dayType.toLowerCase();
    }
    if (includeAllDay) {
      params['include_all'] = 'true';
    }

    final json = await ApiClient.get('/bus/next', params: params);
    // An explicit date is authoritative. Use the backend's calendar result
    // instead of guessing Japanese holidays from DateTime.weekday.
    if (onResolvedDayType != null) {
      final responseDayType = json['day_type'];
      if (responseDayType is! String ||
          !const {'weekday', 'saturday', 'holiday'}.contains(responseDayType)) {
        throw FormatException(
          'Invalid /bus/next day_type: $responseDayType '
          '(routeId=$routeId, poleId=$poleId, referenceTime=$effectiveReferenceTime)',
        );
      }
      final resolvedDayType = switch (responseDayType) {
        'weekday' => 'Weekday',
        'saturday' => 'Saturday',
        'holiday' => 'Holiday',
        _ => throw StateError('Unreachable day_type: $responseDayType'),
      };
      if (dayType != null && resolvedDayType != dayType) {
        throw StateError(
          'Timetable day type mismatch: requested=$dayType, '
          'resolved=$resolvedDayType, routeId=$routeId, poleId=$poleId',
        );
      }
      onResolvedDayType(resolvedDayType);
    }
    final destinations = json['destinations'];
    if (destinations is! List) {
      throw StateError(
        'Invalid /bus/next response: destinations must be a list',
      );
    }

    final results = <Map<String, dynamic>>[];
    for (final dest in destinations) {
      if (dest is! Map) {
        throw StateError(
          'Invalid /bus/next response: destination must be an object',
        );
      }
      final rawName = dest['destination_name'];
      if (rawName == null || rawName.toString().trim().isEmpty) {
        throw StateError(
          'Invalid /bus/next response: destination_name is required',
        );
      }
      final name = rawName.toString();
      final destinationPoleId = dest['destination_pole_id']?.toString();
      final rawNameEn = dest['destination_name_en'];
      if (rawNameEn == null || rawNameEn.toString().trim().isEmpty) {
        throw StateError(
          'Invalid /bus/next response: destination_name_en is required: '
          'destinationPoleId=${destinationPoleId ?? '<unknown>'}',
        );
      }
      final nameEn = rawNameEn.toString().trim();
      final rawTimes = dest['times'];
      if (rawTimes is! List) {
        throw StateError(
          'Invalid /bus/next response: times must be a list',
        );
      }
      final times = rawTimes.map((e) => e.toString()).toList();
      final rawAllTimes = dest['all_times'];
      if (includeAllDay && rawAllTimes is! List) {
        throw StateError(
          'Invalid /bus/next response: all_times must be a list',
        );
      }
      final allTimes = rawAllTimes is List
          ? rawAllTimes.map((e) => e.toString()).toList()
          : const <String>[];

      if (times.isNotEmpty || allTimes.isNotEmpty) {
        results.add({
          'destinationName': name,
          'destinationNameEn': nameEn,
          'destinationPoleId': destinationPoleId,
          'times': times,
          'allTimes': allTimes,
        });
      }
    }
    return results;
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

class _SavedBusSchedule {
  final int savedAtMillis;
  final String dayType;
  final List<Map<String, dynamic>> groups;

  const _SavedBusSchedule({
    required this.savedAtMillis,
    required this.dayType,
    required this.groups,
  });

  String encode() => jsonEncode({
        'schema': 1,
        'saved_at_millis': savedAtMillis,
        'day_type': dayType,
        'groups': groups,
      });

  static _SavedBusSchedule decode(String raw) {
    final Object? decoded = jsonDecode(raw);
    if (decoded is! Map ||
        decoded['schema'] != 1 ||
        decoded['saved_at_millis'] is! int ||
        decoded['day_type'] is! String ||
        decoded['groups'] is! List) {
      throw const FormatException('Malformed saved bus timetable');
    }
    final day = decoded['day_type'] as String;
    if (!const {'Weekday', 'Saturday', 'Holiday'}.contains(day)) {
      throw const FormatException('Unsupported cached timetable day type');
    }
    final groups = <Map<String, dynamic>>[];
    for (final item in decoded['groups'] as List) {
      if (item is! Map) {
        throw const FormatException('Malformed saved timetable destination');
      }
      final group = Map<String, dynamic>.from(item);
      if (group['destinationName'] is! String ||
          group['destinationNameEn'] is! String ||
          group['allTimes'] is! List) {
        throw const FormatException('Incomplete saved timetable destination');
      }
      TimetableService._checkedFullDayTimes(group);
      groups.add(group);
    }
    return _SavedBusSchedule(
      savedAtMillis: decoded['saved_at_millis'] as int,
      dayType: day,
      groups: groups,
    );
  }
}

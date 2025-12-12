// lib/models/group_models.dart

import 'route_models.dart';

enum ScheduleType {
  meeting,   // 集合
  departure, // 出発
  ride,      // 乗車(バス・電車)
  walk,      // 徒歩
  arrival,   // 到着(経由地)
  goal,      // 目的地
  event,     // その他イベント(食事など)
}

class ScheduleItem {
  final String time;        // "10:00" 形式
  final String title;       // "施設集合"
  final String description; // "玄関前"
  final ScheduleType type;  // アイコン出し分け用
  bool isCompleted;         // チェック済みか

  ScheduleItem({
    required this.time,
    required this.title,
    this.description = '',
    this.type = ScheduleType.event,
    this.isCompleted = false,
  });

  // JSONから復元
  factory ScheduleItem.fromJson(Map<String, dynamic> json) {
    return ScheduleItem(
      time: json['time'] as String? ?? '',
      title: json['title'] as String? ?? '',
      description: json['description'] as String? ?? '',
      type: ScheduleType.values.firstWhere(
        (e) => e.name == (json['type'] as String?),
        orElse: () => ScheduleType.event,
      ),
      isCompleted: json['isCompleted'] as bool? ?? false,
    );
  }

  // JSONへ変換
  Map<String, dynamic> toJson() {
    return {
      'time': time,
      'title': title,
      'description': description,
      'type': type.name, // "meeting" などの文字列になる
      'isCompleted': isCompleted,
    };
  }
}

// Candidate(検索結果)からスケジュールリストを作る便利関数
List<ScheduleItem> createScheduleFromRoute(
  Candidate route, {
  String? startTime,
  String? labelPrefix,
}) {
  final list = <ScheduleItem>[];
  final prefix = (labelPrefix != null && labelPrefix.isNotEmpty)
      ? '$labelPrefix '
      : '';
  
  // 1. 出発(集合)
  final departureTime = startTime ?? _formatTime(DateTime.now());
  list.add(ScheduleItem(
    time: departureTime,
    title: "${prefix}出発",
    description: "みんな揃っているか確認しましょう",
    type: ScheduleType.departure,
  ));

  // 2. 移動工程(Steps)を変換
  for (final step in route.steps) {
    if (step.kind == 'walk') {
      // 徒歩は長ければ入れる、短ければ省略など調整
      if ((step.minutes ?? 0) > 3) {
        list.add(ScheduleItem(
          time: step.departureTime ?? "??:??",
          title: "${prefix}歩く (${step.minutes}分)",
          description: step.from ?? '',
          type: ScheduleType.walk,
        ));
      }
    } else {
      // バス・電車
      list.add(ScheduleItem(
        time: step.departureTime ?? "??:??",
        title: "${prefix}${step.title} に乗る",
        description: "${step.from ?? ''} から",
        type: ScheduleType.ride,
      ));

      list.add(ScheduleItem(
        time: step.arrivalTime ?? "??:??",
        title: "${prefix}${step.to ?? ''} に着く",
        description: step.edges > 0 ? "${step.edges}駅" : '',
        type: ScheduleType.arrival,
      ));
    }
  }

  // 3. 到着(ゴール)
  if (route.steps.isNotEmpty) {
    list.add(ScheduleItem(
      time: route.steps.last.arrivalTime ?? "??:??",
      title: "${prefix}目的地 到着",
      description: "お疲れ様でした!",
      type: ScheduleType.goal,
    ));
  }

  return list;
}

List<ScheduleItem> createRoundTripSchedule({
  required Candidate outbound,
  required Candidate inbound,
}) {
  final outboundSchedule = createScheduleFromRoute(outbound, labelPrefix: '行き');

  final inboundStartTime =
      inbound.departureDate != null ? _formatTime(inbound.departureDate!) : null;
  final inboundSchedule = createScheduleFromRoute(
    inbound,
    startTime: inboundStartTime,
    labelPrefix: '帰り',
  );

  return [
    ...outboundSchedule,
    ScheduleItem(
      time: inboundStartTime ?? "??:??",
      title: "帰りの集合",
      description: "帰りの経路を開始する前に人数を確認しましょう",
      type: ScheduleType.meeting,
    ),
    ...inboundSchedule,
  ];
}

// 時刻を "HH:mm" 形式にフォーマット
String _formatTime(DateTime dt) {
  return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
}

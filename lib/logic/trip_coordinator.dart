import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import 'trip_navigator.dart'; // RouteNavState
import 'schedule_resolver.dart';

class TripCoordinator {
  // Helper to parse "HH:mm"
  static DateTime _parseTime(DateTime date, String timeStr) {
    final parts = timeStr.split(':');
    if (parts.length < 2) return date;
    final h = int.tryParse(parts[0]) ?? 0;
    final m = int.tryParse(parts[1]) ?? 0;
    return DateTime(date.year, date.month, date.day, h, m);
  }

  /// 最終的なナビゲーション状態を構築する
  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required ScheduleResolveResult scheduleState,
    required RouteState? routeState, // ★RouteNavState -> RouteState (mutable object passed for checking)
    required DateTime now,
  }) {
    // 1. TripStatus Check
    if (trip.status == TripStatus.completed) {
      return NavigationState(
        mainText: "終了",
        subText: "お疲れ様でした",
        color: Colors.grey,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "お出かけ終了",
        isMoving: false,
      );
    }
    if (trip.status == TripStatus.cancelled) {
       return NavigationState(
        mainText: "中止",
        subText: "グループは解散されました",
        color: Colors.red,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "中止",
        isMoving: false,
      );
    }

    // 1b. Route Arrival Check (Prioritize GPS arrival over schedule)
    // routeState が null の場合は考慮しない
    if (routeState != null && routeState.currentStepIndex >= routeState.steps.length) {
      return NavigationState(
        mainText: "到着",
        subText: "目的地周辺です",
        color: Colors.orange,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "到着",
        nextStopName: "目的地",
        remainingStops: 0,
        isMoving: true,
      );
    }

    // ★重要: スケジュールによる強制開始判定
    // Current Step の departure_time を過ぎていたら、GPSで動いていなくても「移動中」とみなす
    bool shouldStart = false;
    if (routeState != null && routeState.currentStepIndex < routeState.steps.length) {
      final step = routeState.steps[routeState.currentStepIndex];
      // 出発時間が設定されている場合
      if (step.departureTime != null) {
        final departureDt = _parseTime(now, step.departureTime!);
        // 現在時刻が出発予定より1分以上過ぎているなら強制開始
        // (GPSが取れなくてWaitのままになるのを防ぐ)
        if (now.isAfter(departureDt.add(const Duration(minutes: 1)))) {
           shouldStart = true;
        }
      }
    }

    // ★開始前 ActiveIndex == -1 かつ 未来の予定がある
    if (!shouldStart && scheduleState.activeIndex == -1 && scheduleState.window.isNotEmpty) {
      ScheduleEntry? futureEntry;
      for (final e in scheduleState.window) {
        if (e.plannedAt.isAfter(now)) {
          futureEntry = e;
          break;
        }
      }

      if (futureEntry != null) {
        // ... (existing helper logic for dates)
        final diff = futureEntry.plannedAt.difference(now);
        final today = DateTime(now.year, now.month, now.day);
        final targetDay = DateTime(futureEntry.plannedAt.year, futureEntry.plannedAt.month, futureEntry.plannedAt.day);
        final dayDiff = targetDay.difference(today).inDays;

        final dateStr = dayDiff == 0
            ? "今日"
            : dayDiff == 1
                ? "明日"
                : "${targetDay.month}月${targetDay.day}日";
        final timeStr =
            "${futureEntry.plannedAt.hour.toString().padLeft(2, '0')}:${futureEntry.plannedAt.minute.toString().padLeft(2, '0')}";

        final totalMin = diff.inMinutes;
        final h = totalMin ~/ 60;
        final m = totalMin % 60;
        final remainder = h > 0 ? "あと${h}時間${m}分" : "あと${m}分";
        final mainLabel = futureEntry.label.isNotEmpty ? futureEntry.label : "予定";

        return NavigationState(
          mainText: mainLabel,
          subText: "$dateStr $timeStr 開始まで $remainder",
          color: Colors.white,
          currentStepIndex: routeState?.currentStepIndex ?? 0,
          nextStopIndex: routeState?.nextStopIndex ?? 0,
          statusLabel: "開始前",
          isMoving: false,
        );
      }
    }

    // 2. 移動中ならルートナビ優先
    // ただし、スケジュールが待機系（集合、出発、到着、ゴール）ならスケジュールを最優先
    final entry = scheduleState.activeEntry;
    
    // スケジュールが待機系ならスケジュールを最優先
    // ride または walk の時だけルートナビを使う
    final isScheduleWait = entry != null && 
        (entry.itemKind == ScheduleEntryKind.meeting || 
         entry.itemKind == ScheduleEntryKind.departure || 
         entry.itemKind == ScheduleEntryKind.arrival || 
         entry.itemKind == ScheduleEntryKind.goal);

    // 強制開始(shouldStart) または ルートがMoving または スケジュールが移動系 の場合
    if ((shouldStart || (routeState != null && routeState.isMoving)) && !isScheduleWait) {
       // ルート情報を使って NavigationState.navigating を返す
       if (routeState != null && routeState.currentStepIndex < routeState.steps.length) {
         final step = routeState.steps[routeState.currentStepIndex];
         return NavigationState.navigating(
           step: step,
           stopIndex: routeState.nextStopIndex,
           statusLabel: shouldStart ? "定刻出発" : "移動中",
         );
       }
    }

    // 3. 移動していない場合 -> スケジュールを確認
    // entry は既に上で定義済み
    if (entry != null) {
      final diff = entry.plannedAt.difference(now);

      // A. 開始前 (20分以上前)
      if (diff.inMinutes > 20) {
        // ... (omit logic for brevity, assuming standard wait display)
         final remainder = "あと ${diff.inHours}時間${diff.inMinutes % 60}分"; // simplified
         return NavigationState(
           mainText: entry.label,
           subText: "開始まで $remainder",
           color: Colors.white,
           currentStepIndex: routeState?.currentStepIndex ?? 0,
           nextStopIndex: routeState?.nextStopIndex ?? 0,
           statusLabel: "開始前",
           isMoving: false,
         );
      }

      // B. 集合 (Meeting)
      if (entry.itemKind == ScheduleEntryKind.meeting) {
        return NavigationState(
          mainText: entry.label,
          subText: entry.description.isNotEmpty ? entry.description : "集合場所へ向かいましょう",
          color: const Color(0xFFC8E6C9), // 薄い緑
          currentStepIndex: routeState?.currentStepIndex ?? 0,
          nextStopIndex: routeState?.nextStopIndex ?? 0,
          statusLabel: "集合",
          isMoving: false,
        );
      }
      
      // C. 出発 (Departure)
      if (entry.itemKind == ScheduleEntryKind.departure) {
         return NavigationState(
          mainText: entry.label,
          subText: "出発の準備をしましょう",
          color: const Color(0xFFFFF59D), // 薄い黄色
          currentStepIndex: routeState?.currentStepIndex ?? 0,
          nextStopIndex: routeState?.nextStopIndex ?? 0,
          statusLabel: "出発",
          isMoving: false,
        );
      }

      // D. 到着 / ゴール (Arrival / Goal)
      if (entry.itemKind == ScheduleEntryKind.arrival || entry.itemKind == ScheduleEntryKind.goal) {
         return NavigationState(
          mainText: entry.label,
          subText: entry.description.isNotEmpty ? entry.description : "到着しました",
          color: const Color(0xFFFFCC80), // オレンジ
          currentStepIndex: routeState?.currentStepIndex ?? 0,
          nextStopIndex: routeState?.nextStopIndex ?? 0,
          statusLabel: "到着",
          isMoving: false,
        );
      }
    }

    // 4. どれにも当てはまらない場合
    return NavigationState.idle();
  }
}

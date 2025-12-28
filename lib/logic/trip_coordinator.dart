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

    // 1. 既に移動中判定ならそのままナビゲーション
    if (routeState != null && routeState.isMoving) {
      if (routeState.currentStepIndex < routeState.steps.length) {
         return NavigationState.navigating(
           step: routeState.steps[routeState.currentStepIndex],
           stopIndex: routeState.nextStopIndex,
           statusLabel: "移動中",
         );
      }
    }

    // ★重要: スケジュール時刻チェックによる強制開始
    if (routeState != null && routeState.currentStepIndex < routeState.steps.length) {
      final step = routeState.steps[routeState.currentStepIndex];
      // 出発時間が設定されている場合
      if (step.departureTime != null) {
        final departureDt = _parseTime(now, step.departureTime!);
        // 現在時刻が出発予定より1分以上過ぎているなら強制開始
        if (now.isAfter(departureDt.add(const Duration(minutes: 1)))) {
           routeState.isMoving = true; // 状態更新
           return NavigationState.navigating(
             step: step,
             stopIndex: routeState.nextStopIndex,
             statusLabel: "定刻出発",
           );
        }
      }
    }

    // 2. 移動していない場合 -> スケジュールを確認
    final entry = scheduleState.activeEntry;
    if (entry != null) {
      final diff = entry.plannedAt.difference(now);

      // A. 開始前 (20分以上前)
      if (diff.inMinutes > 20) {
          final remainder = "あと ${diff.inHours}時間${diff.inMinutes % 60}分";
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

      // B. 集合 / 出発 / 到着 / ゴール
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

    // 3. 未来の予定チェック (ActiveIndex = -1 fallback)
    if (scheduleState.activeIndex == -1 && scheduleState.window.isNotEmpty) {
      // ... (existing helper logic maintained below, but consolidated here for snippet match)
      // Since specific logic for dates was complex, relying on the Schedule Check block (A.) 
      // above handling future entries if they are set as 'activeEntry' by resolver would be cleaner.
      // But Resolver sets activeEntry mainly for current window.
      // Let's keep the fallback for strictly "Pre-Trip" state if entry is null.
      
       ScheduleEntry? futureEntry;
       for (final e in scheduleState.window) {
         if (e.plannedAt.isAfter(now)) {
           futureEntry = e;
           break;
         }
       }
       if (futureEntry != null) {
          final diff = futureEntry.plannedAt.difference(now);
          final remainder = diff.inHours > 0 ? "あと${diff.inHours}時間${diff.inMinutes%60}分" : "あと${diff.inMinutes}分";
          return NavigationState(
            mainText: futureEntry.label,
            subText: "開始まで $remainder",
            color: Colors.white,
            currentStepIndex: routeState?.currentStepIndex ?? 0,
            nextStopIndex: routeState?.nextStopIndex ?? 0,
            statusLabel: "開始前",
            isMoving: false,
          );
       }
    }

    // 4. どれにも当てはまらない場合
    return NavigationState.idle();
  }
}

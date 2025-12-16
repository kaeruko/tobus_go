import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import 'trip_navigator.dart'; // RouteNavState
import 'schedule_resolver.dart';

class TripCoordinator {
  /// 最終的なナビゲーション状態を構築する
  ///
  /// 優先順位:
  /// 1. TripStatus (completed/cancelled)
  /// 2. 移動中 (routeState.isMoving) -> ナビ表示
  /// 3. 非移動時 -> スケジュール表示 (開始前 / 集合 / 出発)
  /// 4. その他 -> ルート情報 (待機/到着)
  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required ScheduleResolveResult scheduleState,
    required RouteNavState routeState,
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
        statusLabel: "旅は完了",
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

    // 2. 移動中ならルートナビ優先
    // (ただし、RouteNavState が error や arrived の場合は移動中とみなさない判定が必要だが、
    //  TripNavigator側で isMoving=false になっているはず)
    if (routeState.isMoving) {
      // 例外: スケジュールが「到着」「ゴール」でアクティブなら、そちらを優先する
      // (徒歩で移動中判定だが、時間的には到着している場合など)
      final entry = scheduleState.activeEntry;
      if (entry != null && 
         (entry.itemKind == ScheduleEntryKind.arrival || entry.itemKind == ScheduleEntryKind.goal)) {
          // Fall through to Step 3 (Schedule Logic)
      } else {
        // 通常の移動案内
        return NavigationState(
          mainText: routeState.mainText,
          subText: routeState.subText,
          color: routeState.color,
          currentStepIndex: routeState.currentStepIndex,
          nextStopIndex: routeState.nextStopIndex,
          statusLabel: routeState.statusLabel,
          nextStopName: routeState.nextStopName,
          remainingStops: routeState.remainingStops,
          isMoving: true,
        );
      }
    }

    // 3. 移動していない場合 -> スケジュールを確認
    final entry = scheduleState.activeEntry;
    if (entry != null) {
      final diff = entry.plannedAt.difference(now);

      // A. 開始前 (20分以上前)
      if (diff.inMinutes > 20) {
        final dateStr = "${entry.plannedAt.month}月${entry.plannedAt.day}日";
        final timeStr = "${entry.plannedAt.hour.toString().padLeft(2, '0')}:${entry.plannedAt.minute.toString().padLeft(2, '0')}";

        String remainder;
        if (diff.inHours > 0) {
          remainder = "あと ${diff.inHours}時間${diff.inMinutes % 60}分";
        } else {
          remainder = "あと ${diff.inMinutes}分";
        }

        // Use label to clarify WHAT is starting (e.g. "Meeting Start" vs "Trip Start")
        final mainLabel = entry.label.isNotEmpty ? entry.label : "予定";

        return NavigationState(
          mainText: "$mainLabel",
          subText: "開始まで $remainder",
          color: Colors.white,
          currentStepIndex: routeState.currentStepIndex,
          nextStopIndex: routeState.nextStopIndex,
          statusLabel: entry.itemKind == ScheduleEntryKind.meeting ? "集合前" : "開始前",
          isMoving: false,
        );
      }

      // B. 集合 (Meeting)
      if (entry.itemKind == ScheduleEntryKind.meeting) {
        return NavigationState(
          mainText: entry.label,
          subText: entry.description.isNotEmpty ? entry.description : "集合場所へ向かいましょう",
          color: const Color(0xFFC8E6C9), // 薄い緑
          currentStepIndex: routeState.currentStepIndex,
          nextStopIndex: routeState.nextStopIndex,
          statusLabel: "集合",
          isMoving: false,
        );
      }
      
      // C. 出発 (Departure) - まだ移動開始していない（isMoving=false）場合
      if (entry.itemKind == ScheduleEntryKind.departure) {
         return NavigationState(
          mainText: entry.label,
          subText: "出発の準備をしましょう",
          color: const Color(0xFFFFF59D), // 薄い黄色
          currentStepIndex: routeState.currentStepIndex,
          nextStopIndex: routeState.nextStopIndex,
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
          currentStepIndex: routeState.currentStepIndex,
          nextStopIndex: routeState.nextStopIndex,
          statusLabel: "到着",
          isMoving: false,
        );
      }
    }

    // 4. どれにも当てはまらない場合（到着済み、あるいはスケジュール空） -> ルート側の静的ステータス
    return NavigationState(
      mainText: routeState.mainText,
      subText: routeState.subText,
      color: routeState.color,
      currentStepIndex: routeState.currentStepIndex,
      nextStopIndex: routeState.nextStopIndex,
      statusLabel: routeState.statusLabel,
      nextStopName: routeState.nextStopName,
      remainingStops: routeState.remainingStops,
      isMoving: false,
    );
  }
}

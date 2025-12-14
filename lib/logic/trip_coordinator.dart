import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../models/group_models.dart';
import 'trip_navigator.dart';

/// 予定の進捗状況だけを持つクラス
class ScheduleProgress {
  final int activeIndex;
  final ScheduleEntry? activeEntry;
  final List<ScheduleEntry> upcomingEntries;
  final int completedCount;
  final String activeLabel;

  const ScheduleProgress({
    required this.activeIndex,
    required this.activeEntry,
    required this.upcomingEntries,
    required this.completedCount,
    required this.activeLabel,
  });
}



class TripCoordinator {
  /// スケジュールの進捗を計算する
  static ScheduleProgress computeScheduleProgress({
    required List<ScheduleEntry> scheduleSorted,
    required DateTime now,
  }) {
    final activeIndexRaw = scheduleSorted.indexWhere((e) => !e.isCompleted);
    var activeIndex = activeIndexRaw;

    if (activeIndex >= 0 && activeIndex + 1 < scheduleSorted.length) {
      final current = scheduleSorted[activeIndex];
      final next = scheduleSorted[activeIndex + 1];

      // "集合" (meeting) の場合、かつ次の予定（出発など）の時間が過ぎている場合はスキップ
      if (current.itemKind == ScheduleEntryKind.meeting && now.isAfter(next.plannedAt)) {
        activeIndex++;
      }
    }

    final activeEntry = activeIndex >= 0 ? scheduleSorted[activeIndex] : null;

    var activeLabel = 'いま';
    if (activeEntry != null) {
      final diff = activeEntry.plannedAt.difference(now);
      // 20分以上先なら "つぎ"
      if (diff.inMinutes > 20) {
        activeLabel = 'つぎ';
      }
    }

    final upcomingEntries = (activeIndex >= 0 ? scheduleSorted.skip(activeIndex + 1) : scheduleSorted)
        .take(3)
        .toList();
    
    // activeIndexより前はすべて完了扱いとみなす
    final completedCount = activeIndex >= 0 ? activeIndex : scheduleSorted.length;

    return ScheduleProgress(
      activeIndex: activeIndex,
      activeEntry: activeEntry,
      upcomingEntries: upcomingEntries,
      completedCount: completedCount,
      activeLabel: activeLabel,
    );
  }

  /// 最終的なナビゲーション状態を構築する
  static NavigationState buildMemberNavigationState({
    required Trip trip,
    required LatLng currentPos,
    required int lastStepIndex,
    required int lastStopIndex,
    required List<ScheduleEntry> scheduleSorted,
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

    // 2. Schedule Check
    final sched = computeScheduleProgress(
      scheduleSorted: scheduleSorted,
      now: now,
    );

    final entry = sched.activeEntry;
    if (entry != null) {
      final diff = entry.plannedAt.difference(now);

      // 開始時間よりだいぶ前（20分以上）の場合は、開始日時を案内
      if (diff.inMinutes > 20) {
        final dateStr = "${entry.plannedAt.month}月${entry.plannedAt.day}日";
        final timeStr = "${entry.plannedAt.hour.toString().padLeft(2, '0')}:${entry.plannedAt.minute.toString().padLeft(2, '0')}";

        String remainder;
        if (diff.inHours > 0) {
          remainder = "あと ${diff.inHours}時間${diff.inMinutes % 60}分";
        } else {
          remainder = "あと ${diff.inMinutes}分";
        }

        return NavigationState(
          mainText: "$dateStr $timeStr 開始",
          subText: "開始まで $remainder",
          color: Colors.white,
          currentStepIndex: lastStepIndex,
          nextStopIndex: lastStopIndex,
          statusLabel: "開始前",
          isMoving: false,
        );
      }

      // "集合" (meeting) の場合
      if (entry.itemKind == ScheduleEntryKind.meeting) {
        return NavigationState(
          mainText: entry.label, // 例: "行き 集合"
          subText: entry.description.isNotEmpty ? entry.description : "集合場所へ向かいましょう",
          color: const Color(0xFFC8E6C9), // 薄い緑
          currentStepIndex: lastStepIndex,
          nextStopIndex: lastStopIndex,
          statusLabel: "集合",
          isMoving: false,
        );
      }
    }

    // 3. Route Navigation
    final route = TripNavigator.updateRouteOnly(
      trip: trip,
      currentPos: currentPos,
      lastStepIndex: lastStepIndex,
      lastStopIndex: lastStopIndex,
    );

    return NavigationState(
      mainText: route.mainText,
      subText: route.subText,
      color: route.color,
      currentStepIndex: route.currentStepIndex,
      nextStopIndex: route.nextStopIndex,
      statusLabel: route.statusLabel,
      nextStopName: route.nextStopName,
      remainingStops: route.remainingStops,
      isMoving: route.isMoving,
    );
  }
}

import 'package:flutter/material.dart';
import '../models/route_models.dart'; // StepSeg
import '../models/trip_models.dart';
import '../models/group_models.dart';

// ナビゲーションの結果（画面表示用、最終形）
// Coordinatorがこれを組み立てるが、型定義はここにあっても良いし、Coordinatorに移動しても良い。
// MemberModePageが使っているので、既存の場所にあるとimport変更が少なくて済む。
// Mutable state for navigation to ensure stability
class RouteState {
  List<StepSeg> steps;
  int currentStepIndex;
  int nextStopIndex;
  bool isMoving;

  RouteState({
    required this.steps,
    this.currentStepIndex = 0,
    this.nextStopIndex = 0,
    this.isMoving = false,
  });

  // Helper to get current step safely
  StepSeg? get currentStep => (currentStepIndex >= 0 && currentStepIndex < steps.length) ? steps[currentStepIndex] : null;
}

// Result for UI (immutable)
class NavigationState {
  final String mainText; // "あと 3駅"
  final String subText; // "つぎは 〇〇"
  final Color color;
  final bool isMoving;
  final String statusLabel;
  final String? nextStopName;
  final int? remainingStops;
  final int currentStepIndex;
  final int nextStopIndex;
  final StepSeg? step; // ★追加: 現在のステップ情報自体も持たせる

  NavigationState({
    required this.mainText,
    required this.subText,
    required this.color,
    required this.currentStepIndex,
    required this.nextStopIndex,
    required this.statusLabel,
    this.nextStopName,
    this.remainingStops,
    this.isMoving = true,
    this.step,
  });

  // Factory factories for states
  static NavigationState idle() => NavigationState(
    mainText: "", subText: "", color: Colors.grey, currentStepIndex: 0, nextStopIndex: 0, statusLabel: "待機中", isMoving: false,
  );
  
  static NavigationState waitingForDeparture({required DateTime plannedAt}) => NavigationState(
    mainText: "出発前", subText: "${plannedAt.hour}:${plannedAt.minute.toString().padLeft(2, '0')} 出発予定", 
    color: Colors.white, currentStepIndex: 0, nextStopIndex: 0, statusLabel: "開始前", isMoving: false,
  );

  static NavigationState waitingLong({required ScheduleEntry entry, required Duration diff}) {
    final remainder = "あと ${diff.inHours}時間${diff.inMinutes % 60}分";
    return NavigationState(
      mainText: entry.label,
      subText: "開始まで $remainder",
      color: Colors.white,
      currentStepIndex: 0, 
      nextStopIndex: 0,
      statusLabel: "開始前",
      isMoving: false,
    );
  }

  static NavigationState fromEntry({
    required Trip trip,
    required ScheduleEntry entry,
    required StepSeg? step,
    required int stopIndex,
    required int currentStepIndex,
  }) {
    if (entry.itemKind == ScheduleEntryKind.walk && step != null) {
      return NavigationState.navigating(
        step: step,
        stopIndex: stopIndex,
        statusLabel: "移動中",
      );
    }

    if (entry.itemKind == ScheduleEntryKind.ride && step != null) {
      return NavigationState.navigating(
        step: step,
        stopIndex: stopIndex,
        statusLabel: "乗車中",
      );
    }

    if (entry.itemKind == ScheduleEntryKind.meeting) {
      return NavigationState(
        mainText: entry.label,
        subText: entry.description.isNotEmpty ? entry.description : "集合場所へ向かいましょう",
        color: const Color(0xFFC8E6C9),
        currentStepIndex: currentStepIndex,
        nextStopIndex: stopIndex,
        statusLabel: "集合",
        isMoving: false,
      );
    }

    if (entry.itemKind == ScheduleEntryKind.arrival || entry.itemKind == ScheduleEntryKind.goal) {
      return NavigationState(
        mainText: entry.label,
        subText: entry.description.isNotEmpty ? entry.description : "到着しました",
        color: const Color(0xFFFFCC80),
        currentStepIndex: currentStepIndex,
        nextStopIndex: stopIndex,
        statusLabel: "到着",
        isMoving: false,
      );
    }

    return NavigationState(
      mainText: entry.label,
      subText: entry.description.isNotEmpty ? entry.description : "時間まで待機しましょう",
      color: const Color(0xFFE1F5FE),
      currentStepIndex: currentStepIndex,
      nextStopIndex: stopIndex,
      statusLabel: "待機",
      isMoving: false,
    );
  }

  static NavigationState navigating({
    required StepSeg step,
    required int stopIndex,
    String? statusLabel,
  }) {
    // Generate text based on step
    String mainText = "";
    String subText = "";
    Color color = Colors.blue;
    String? nextName;
    int? remaining;

    if (step.kind == 'walk') {
       mainText = "徒歩で移動中";
       subText = "目的地へ";
       color = const Color(0xFF81D4FA);
       nextName = step.to;
    } else {
       // Ride
       color = const Color(0xFF81D4FA);
       remaining = step.stops.length - stopIndex;
       if (stopIndex < step.stops.length) {
         nextName = step.stops[stopIndex].name;
       }
       if (remaining <= 1) {
         mainText = "次降ります";
         subText = nextName ?? "";
         color = const Color(0xFFFFAB91);
       } else {
          mainText = "あと $remaining 回停車";
         // subText = "つぎは $nextName";
         // 要望により現在の停留所を表示
         String currentName = "";
         if (stopIndex > 0 && stopIndex <= step.stops.length) {
           currentName = step.stops[stopIndex - 1].name;
         } else if (stopIndex == 0 && step.stops.isNotEmpty) {
            currentName = step.stops[0].name;
         }
         subText = "現在: $currentName";
       }
    }

    return NavigationState(
      mainText: mainText,
      subText: subText,
      color: color,
      currentStepIndex: 0, // Not vital for UI logic here if using specialized
      nextStopIndex: stopIndex,
      statusLabel: statusLabel ?? "移動中",
      nextStopName: nextName,
      remainingStops: remaining,
      step: step,
    );
  }
}

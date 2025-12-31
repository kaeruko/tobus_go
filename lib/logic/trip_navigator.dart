import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:geolocator/geolocator.dart'; // 距離計算用
import '../core/app_clock.dart';
import '../models/trip_models.dart';
import '../models/route_models.dart'; // StepSeg
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
         mainText = "あと $remaining 駅";
         subText = "つぎは $nextName";
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

class TripNavigator {
  // メインの更新メソッド
  static void updateRouteOnly(
    RouteState state,
    LatLng currentPos, {
    // ★将来的にAPIからとった「現在バス停Index」をここに入れる想定
    int? forceStopIndex, 
  }) {
    if (state.steps.isEmpty) return;
    if (state.currentStepIndex >= state.steps.length) return;

    final currentStep = state.steps[state.currentStepIndex];

    int nextStepIndex = state.currentStepIndex;

    // ============================================================
    // 1. Step更新ロジック (Ride中はGPSジャンプをロックする)
    // ============================================================
    if (currentStep.isRide) {
      // --- 乗車中 (Bus/Rail) ---
      // APIなどから提供される現在の停留所Index(forceStopIndex)を使用して進捗を更新する。
      _updateStopIndex(state, currentPos, forceStopIndex: forceStopIndex);

      // 目的地の停留所Indexに到達したら次のStepへ進む
      if (currentStep.stops.isNotEmpty) {
        final lastStopIndex = currentStep.stops.length - 1;
        if (state.nextStopIndex >= lastStopIndex) {
          nextStepIndex = state.currentStepIndex + 1;
        }
      }
      // ※ここでは _estimateCurrentStepIndexWithDistance は呼ばない！
      // これにより、バス乗車中に近くの駅を通ってもGPSで勝手に切り替わらない。
    } else {
      // --- 徒歩中 (Walk) ---
      // 従来どおり、GPS位置に基づいて最適なStepを探す（リルート的挙動）
      nextStepIndex = _estimateCurrentStepIndexWithDistance(state, currentPos);
    }

    // Stepが変わった場合の処理
    if (nextStepIndex != state.currentStepIndex && nextStepIndex < state.steps.length) {
      state.currentStepIndex = nextStepIndex;
      state.nextStopIndex = 0; // 新しいStepなのでStopIndexはリセット
      // print("Step Changed: ${state.currentStepIndex} (${state.steps[nextStepIndex].title})");
    }

    // ============================================================
    // 2. Stop更新ロジック (Step内の進行)
    // ============================================================
    _updateStopIndex(state, currentPos, forceStopIndex: forceStopIndex);
  }

  static void _updateStopIndex(RouteState state, LatLng currentPos, {int? forceStopIndex}) {
    if (state.currentStepIndex >= state.steps.length) return;
    final step = state.steps[state.currentStepIndex];
    if (step.stops.isEmpty) return;

    if (forceStopIndex != null) {
      state.nextStopIndex = forceStopIndex.clamp(0, step.stops.length - 1);
      return;
    }

    // バス乗車中はGPS距離ではなくリアルタイムの停留所情報に従う
    if (step.isRide) {
      return;
    }

    // 現在のターゲット以降のバス停の中から、最も近いものを探す
    // (通り過ぎたものを戻らないように、検索開始位置を current にする)
    int bestIndex = state.nextStopIndex;
    double minDistance = 999999;

    for (int i = state.nextStopIndex; i < step.stops.length; i++) {
      final dist = _distance(currentPos, step.stops[i].point);
      if (dist < minDistance) {
        minDistance = dist;
        bestIndex = i;
      }
    }

    // 200m以内なら「そのバス停付近にいる」とみなしてIndex更新
    // (バスは速いので、検知範囲は徒歩より広めにとる)
    if (minDistance < 200.0) {
      if (bestIndex > state.nextStopIndex) {
        state.nextStopIndex = bestIndex;
        // print("Stop Updated: $bestIndex (${step.stops[bestIndex].name})");
      }
    }
  }

  static double _distance(LatLng p1, LatLng p2) {
    return Geolocator.distanceBetween(p1.latitude, p1.longitude, p2.latitude, p2.longitude);
  }

  static int _estimateCurrentStepIndexWithDistance(RouteState state, LatLng currentPos) {
    // 簡易実装: 現在のステップの前後を検索
    // Walk中のみ呼ばれる前提なので、単純に最も近いWalkステップなどを探す
    // ここでは単純化して実装
    int bestIndex = state.currentStepIndex;
    double minD = 999999;
    
    for(int i=0; i<state.steps.length; i++) {
      final s = state.steps[i];
      // Walkの場合、Stepの始点（前のStepの終点）や終点との距離を見るべきだが
      // 簡易的に全Stopとの距離を見るか、from/toのpointを使う
      // ここではStepSegにpointリストが無いモデルっぽいので、stopsを使う
      if (s.stops.isNotEmpty) {
        for(final sp in s.stops) {
          final d = _distance(currentPos, sp.point);
          if (d < minD) {
            minD = d;
            bestIndex = i;
          }
        }
      }
    }
    
    // 現在より大幅に進んでいる/戻っている場合は移動
    return bestIndex;
  }
}

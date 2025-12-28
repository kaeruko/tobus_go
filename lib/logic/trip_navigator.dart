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
  // 通過判定の距離（メートル）
  static const double _arrivalRadius = 80.0;

  // メインの更新メソッド
  static void updateRouteOnly(
    RouteState state,
    LatLng currentPos, {
    // ★将来的にAPIからとった「現在バス停Index」をここに入れる想定
    int? forceStopIndex, 
  }) {
    if (state.steps.isEmpty) return;

    if (state.currentStepIndex >= state.steps.length) return;

    // 1. 現在のステップを取得
    final currentStep = state.steps[state.currentStepIndex];

    // 2. ステップ自体の推定 (GPSジャンプ防止ロジック)
    int nextStepIndex = state.currentStepIndex;
    
    if (currentStep.isRide) {
      // ★変更点: Ride中は、GPS距離だけで安易にステップを変えない
      // 現在のRideが終わった（降車した）と判定できた場合のみ、次のStepへ進む
      
      if (state.nextStopIndex >= currentStep.stops.length - 1) {
        // 既に「降りるバス停」をターゲットにしている場合
        // 目的地（降車バス停）に十分近づいたら、降車完了として次のWalkへ
        if (currentStep.stops.isNotEmpty) {
           final distToDest = _distance(currentPos, currentStep.stops.last.point);
           if (distToDest < 50.0) { // 50m以内なら降車判定
             nextStepIndex = state.currentStepIndex + 1;
           }
        }
      }
      
      // Ride中は「前のStepに戻る」や「全然違うStepに飛ぶ」判定は一切しない
    } else {
      // Walk中は従来どおり、GPS位置で最適なStepを探す（リルート的な挙動）
      nextStepIndex = _estimateCurrentStepIndexWithDistance(state, currentPos);
    }

    // ステップが変わる場合の処理
    if (nextStepIndex != state.currentStepIndex && 
        nextStepIndex < state.steps.length) {
      state.currentStepIndex = nextStepIndex;
      state.nextStopIndex = 0; // 新しいStepになったらStopもリセット
    }

    // 3. Step内の進行 (StopIndexの更新)
    // ここはRide中も動かす
    _updateStopIndex(state, currentPos, forceStopIndex: forceStopIndex);
  }

  // StopIndexを進めるロジック
  static void _updateStopIndex(RouteState state, LatLng currentPos, {int? forceStopIndex}) {
    if (state.currentStepIndex >= state.steps.length) return;
    final step = state.steps[state.currentStepIndex];
    if (step.stops.isEmpty) return;

    // API等からの強制指定があればそれを優先（将来用）
    if (forceStopIndex != null) {
      state.nextStopIndex = forceStopIndex;
      return;
    }

    // GPSによる判定: 次のバス停に近づいたか？
    // 単純な距離判定だけでなく、「通過したか」も見るのが理想だが、
    // まずは「一番近いバス停」を現在のバス停とする簡易ロジックで安定させる
    
    int bestIndex = state.nextStopIndex;
    double minDistance = 999999;

    // 検索範囲を「現在地〜最後」に絞る（戻らない）
    for (int i = state.nextStopIndex; i < step.stops.length; i++) {
      final dist = _distance(currentPos, step.stops[i].point);
      if (dist < minDistance) {
        minDistance = dist;
        bestIndex = i;
      }
    }

    // 「近づいた」と判定できる閾値（例: 50m）に入ったらIndex更新
    // ただし、Ride中は「通り過ぎた」判定が難しいので、一番近いものを信じる
    if (minDistance < 200) { // 少し広めに
      state.nextStopIndex = bestIndex;
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

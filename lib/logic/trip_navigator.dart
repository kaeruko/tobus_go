import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:geolocator/geolocator.dart'; // 距離計算用
import '../models/trip_models.dart';
import '../models/route_models.dart';

// ナビゲーションの結果（画面表示用）
class NavigationState {
  final String mainText;    // "あと 3駅"
  final String subText;     // "つぎは 〇〇"
  final Color color;
  final bool isMoving;
  
  // ★追加: 現在の進行状況を保存しておくためのインデックス
  final int currentStepIndex; 
  final int nextStopIndex;

  NavigationState({
    required this.mainText,
    required this.subText,
    required this.color,
    required this.currentStepIndex,
    required this.nextStopIndex,
    this.isMoving = true,
  });
}

class TripNavigator {
  // 通過判定の距離（メートル）
  static const double _arrivalRadius = 80.0; // 少し広めに設定

  /// 前回の状態(lastState)と現在地(gps)を受け取り、新しい状態を返す
  static NavigationState updateState(
    Trip trip, 
    LatLng currentPos, 
    int lastStepIndex, // 前回どこまで進んでいたか
    int lastStopIndex, // 前回どのバス停を目指していたか
  ) {
    
    // 1. 完了チェック
    if (trip.status == TripStatus.completed) {
      return _completedState();
    }
    
    // legsから全てのstepを展開して1つのリストにする
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();

    if (allSteps.isEmpty) {
      return _errorState();
    }

    // 2. 「今のターゲット」の判定更新
    int currentStep = lastStepIndex;
    int nextStop = lastStopIndex;

    // 現在のステップ（区間）を取得
    if (currentStep < allSteps.length) {
      final step = allSteps[currentStep];

      // もし徒歩(walk)なら、シンプルに「区間のゴール」に近づいたかだけで判定
      if (step.kind == 'walk') {
        // 次のステップがあるなら、そのステップの出発地（＝今のステップの目的地）との距離を測る
        if (currentStep + 1 < allSteps.length) {
            final nextStep = allSteps[currentStep + 1];
            // 次のステップの最初のストップ（乗り場）
            if (nextStep.stops.isNotEmpty) {
                final targetStop = nextStep.stops.first;
                final targetLat = targetStop.lat ?? 0;
                final targetLon = targetStop.lon ?? 0;
                 final distance = Geolocator.distanceBetween(
                    currentPos.latitude, currentPos.longitude,
                    targetLat, targetLon
                );
                
                // 次の乗り場に近づいたらステップを進める
                if (distance < _arrivalRadius) {
                    currentStep++;
                    nextStop = 0;
                }
            }
        } else {
             // 最後の徒歩（目的地への移動）
             // ここでは簡易的に現状維持
        }
      } 
      // 乗り物(bus/rail)の場合
      else {
        // ターゲット（次の駅）の座標を取得
        if (nextStop < step.stops.length) {
          final targetStop = step.stops[nextStop];
          final targetLat = targetStop.lat ?? 0;
          final targetLon = targetStop.lon ?? 0;

          // 距離を計測
          final distance = Geolocator.distanceBetween(
            currentPos.latitude, currentPos.longitude,
            targetLat, targetLon
          );

          // ★ここがポイント！
          // 「ターゲットの半径内に入った」＝「到着/通過した」とみなす
          if (distance < _arrivalRadius) {
            // 次の駅へターゲットを更新（経路を潰す）
            nextStop++; 
          }
        } else {
          // この区間の駅を全部消化した＝乗り換え地点に到着！
          // 次のステップへ進む
          currentStep++;
          nextStop = 0; // 次の路線の最初の駅へ
        }
      }
    } else {
      // 全ステップ終了＝目的地到着
      return _arrivedState();
    }

    // 3. 画面表示の生成
    // 更新された currentStep / nextStop を使って文字を作る
    
    // 範囲外チェック
    if (currentStep >= allSteps.length) {
      return _arrivedState();
    }

    final step = allSteps[currentStep];
    
    if (step.kind == 'walk') {
      return NavigationState(
        mainText: "徒歩で移動中",
        subText: "目的地まで歩きましょう",
        color: const Color(0xFF81D4FA),
        currentStepIndex: currentStep,
        nextStopIndex: nextStop,
      );
    } else {
      // バス・電車
      // 残り駅数 = (全駅数) - (次に目指している駅のインデックス)
      // 例: 全5駅、次はindex=0(1駅目) -> 残り5駅
      //     全5駅、次はindex=4(5駅目/最後) -> 残り1駅
      final remainingStops = step.stops.length - nextStop;
      
      // 次のバス停名
      String nextStopName = "";
      if (nextStop < step.stops.length) {
          nextStopName = step.stops[nextStop].name;
      }

      // 残りが0以下または次が最後の駅（降りる駅）の場合
      // バスの降りるボタン等は、最後の駅の一つ前を出た後に押すが、
      // ここでは「最後の駅を目指している」状態になったら「まもなく降車」とする
      if (remainingStops <= 1) {
        final destinationName = step.to ?? (step.stops.isNotEmpty ? step.stops.last.name : "目的地");
        return NavigationState(
          mainText: "まもなく降車",
          subText: "$destinationName で降ります",
          color: const Color(0xFFFFAB91), // 赤
          currentStepIndex: currentStep,
          nextStopIndex: nextStop,
        );
      } else {
        // まだ乗っている
        return NavigationState(
          mainText: "あと $remainingStops 駅",
          subText: "つぎは $nextStopName",
          color: const Color(0xFF81D4FA), // 青
          currentStepIndex: currentStep,
          nextStopIndex: nextStop,
        );
      }
    }
  }

  // --- Helper States ---
  static NavigationState _completedState() => NavigationState(
    mainText: "終了", subText: "お疲れ様でした", color: Colors.grey, 
    currentStepIndex: 999, nextStopIndex: 999
  );
  
  static NavigationState _errorState() => NavigationState(
    mainText: "エラー", subText: "ルートがありません", color: Colors.red, 
    currentStepIndex: 0, nextStopIndex: 0
  );

  static NavigationState _arrivedState() => NavigationState(
    mainText: "到着", subText: "目的地周辺です", color: Colors.orange, 
    currentStepIndex: 999, nextStopIndex: 999
  );
}


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
class NavigationState {
  final String mainText; // "あと 3駅"
  final String subText; // "つぎは 〇〇"
  final Color color;
  final bool isMoving;
  final String statusLabel;
  final String? nextStopName;
  final int? remainingStops;

  // ★追加: 現在の進行状況を保存しておくためのインデックス
  final int currentStepIndex;
  final int nextStopIndex;

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
  });
}

/// 経路ナビの進捗状況だけを持つクラス
class RouteNavState {
  final int currentStepIndex;
  final int nextStopIndex;
  final String statusLabel; // "移動中", "歩行中" etc
  final String mainText;    // "あと 3駅", "徒歩で移動中"
  final String subText;     // "つぎは 〇〇", "目的地まで"
  final Color color;        // 背景色
  final String? nextStopName;
  final int? remainingStops;
  final bool isMoving;

  const RouteNavState({
    required this.currentStepIndex,
    required this.nextStopIndex,
    required this.statusLabel,
    required this.mainText,
    required this.subText,
    required this.color,
    this.nextStopName,
    this.remainingStops,
    this.isMoving = true,
  });
}

class TripNavigator {
  // 通過判定の距離（メートル）
  static const double _arrivalRadius = 80.0; // 少し広めに設定

  /// 前回の状態(lastState)と現在地(gps)を受け取り、新しい経路状態を返す
  ///
  /// ★ここでは「スケジュール(集合など)」は見ない。純粋に「経路上のどこにいるか」だけを返す。
  /// 画面表示用に NavigationState ではなく RouteNavState を返す。
  static RouteNavState updateRouteOnly({
    required Trip trip,
    required LatLng currentPos,
    required int lastStepIndex, // 前回どこまで進んでいたか
    required int lastStopIndex, // 前回どのバス停を目指していたか
  }) {
    // 1. 完了チェック（一応ここでも見るが、基本はNavigatorState側で制御）
    if (trip.status == TripStatus.completed) {
      return _completedRouteState();
    }

    // legsから全てのstepを展開して1つのリストにする
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    debugPrint('[TripNavigator] Update: Legs=${trip.legs.length}, TotalSteps=${allSteps.length}, CurStep=$lastStepIndex');

    if (allSteps.isEmpty) {
      return _errorRouteState();
    }

    // 2. 「今のターゲット」の判定更新
    int currentStep = lastStepIndex;
    int nextStop = lastStopIndex;
    debugPrint('[TripNavigator] Update Route: Pos=$currentPos LastStep=$lastStepIndex LastStop=$lastStopIndex');

    // ★現在アクティブなLegの範囲（開始・終了インデックス）を計算
    final activeLegIndex = trip.activeLegIndex;
    int legStartStepIndex = 0;
    for (int i = 0; i < activeLegIndex; i++) {
      if (i < trip.legs.length) {
        legStartStepIndex += trip.legs[i].candidate.steps.length;
      }
    }
    final currentLegStepCount = activeLegIndex < trip.legs.length
        ? trip.legs[activeLegIndex].candidate.steps.length
        : 0;
    final legEndStepIndex = legStartStepIndex + currentLegStepCount;

    // ★GPSベースのステップ推定
    // 複数のLegがある場合、ユーザーが実際にどのステップにいるかをGPSで推定する
    // 現在アクティブなLegの範囲内に限定する
    final (estimatedStep, estimatedDist) = _estimateCurrentStepIndexWithDistance(
      allSteps: allSteps,
      currentPos: currentPos,
      lastStepIndex: lastStepIndex,
      minSearchIndex: legStartStepIndex,
      maxSearchIndex: legEndStepIndex,
    );
    
    // 推定を採用する条件: 距離が近いときだけ（120m以内）
    // これによりstep推定の揺れを抑える
    if (estimatedStep != currentStep && estimatedDist < 120) {
      debugPrint('[TripNavigator] GPS estimation corrected step: $currentStep -> $estimatedStep (dist: ${estimatedDist.toStringAsFixed(0)}m)');
      currentStep = estimatedStep;

      // ★重要: nextStopを0にリセットせず、現在地から推定する
      if (currentStep < allSteps.length) {
        final step = allSteps[currentStep];
        if (step.kind != 'walk') {
          nextStop = _estimateNextStopIndex(
            step: step,
            currentPos: currentPos,
            lastStopIndex: 0, // 新しいstepなので0から探す
          );
          debugPrint('[TripNavigator] -> Estimated nextStop for new step: $nextStop');
        } else {
          nextStop = 0;
        }
      }
    } else {
      // step変更なし: 既存のstepで停留所インデックスを更新
      if (currentStep < allSteps.length) {
        final step = allSteps[currentStep];
        if (step.kind != 'walk') {
          final estimatedStop = _estimateNextStopIndex(
            step: step,
            currentPos: currentPos,
            lastStopIndex: nextStop,
          );
          if (estimatedStop != nextStop) {
            debugPrint('[TripNavigator] GPS estimation corrected stop: $nextStop -> $estimatedStop');
            nextStop = estimatedStop;
          }
        }
      }
    }

    // ★重要: GPS補正後に step を取り直す
    // これにより、補正後の currentStep を使って RouteNavState が作られる
    if (currentStep >= allSteps.length) {
      return _arrivedRouteState();
    }
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
            currentPos.latitude,
            currentPos.longitude,
            targetLat,
            targetLon,
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
        final targetLat = targetStop.lat;
        final targetLon = targetStop.lon;

        // ★デバッグ強化: step情報とtargetStop座標を詳細出力
        debugPrint(
          '[TripNavigator] Target step=$currentStep kind=${step.kind} from=${step.from} to=${step.to} '
          'stopIndex=$nextStop/${step.stops.length} name=${targetStop.name} lat=$targetLat lon=$targetLon cur=$currentPos'
        );

        if (targetLat != null && targetLon != null) {
          // 距離を計測
          final distance = Geolocator.distanceBetween(
            currentPos.latitude,
            currentPos.longitude,
            targetLat,
            targetLon,
          );
          
          debugPrint('[TripNavigator] DistanceToTarget=${distance.toStringAsFixed(1)}m (Threshold:$_arrivalRadius)');

          // ★ここがポイント！
          // 「ターゲットの半径内に入った」＝「到着/通過した」とみなす
          if (distance < _arrivalRadius) {
            debugPrint('[TripNavigator] -> Arrived at ${targetStop.name}. Next stop.');
            // 次の駅へターゲットを更新（経路を潰す）
            nextStop++;
          }
        }
      } else {
        // この区間の駅を全部消化した＝乗り換え地点に到着！
        // 次のステップへ進む
        debugPrint('[TripNavigator] -> Step$currentStep Completed. Moving to next step.');
        currentStep++;
        nextStop = 0; // 次の路線の最初の駅へ
      }
    }

    // 3. 画面表示の生成
    // 更新された currentStep / nextStop を使って文字を作る

    // 範囲外チェック
    if (currentStep >= allSteps.length) {
      return _arrivedRouteState();
    }

    final stepForDisplay = allSteps[currentStep];

    if (stepForDisplay.kind == 'walk') {
      String? nextName;

      if (currentStep + 1 < allSteps.length) {
        final nextStep = allSteps[currentStep + 1];

        // まず乗車地点名 (from) を優先
        final from = nextStep.from;
        if (from != null && from.isNotEmpty) {
          nextName = from;
        } else if (nextStep.stops.isNotEmpty) {
          nextName = nextStep.stops.first.name;
        }
      }

      nextName ??= stepForDisplay.to;

      debugPrint('[TripNavigator] RETURN curStep=$currentStep nextStop=$nextStop kind=walk nextName=$nextName');
      return RouteNavState(
        mainText: "徒歩で移動中",
        subText: "目的地まで歩きましょう",
        color: const Color(0xFF81D4FA),
        currentStepIndex: currentStep,
        nextStopIndex: nextStop,
        statusLabel: "歩行中",
        nextStopName: nextName,
        isMoving: true, // 徒歩も移動中扱い
      );
    } else {
      // バス・電車
      // 残り駅数 = (全駅数) - (次に目指している駅のインデックス)
      // 例: 全5駅、次はindex=0(1駅目) -> 残り5駅
      //     全5駅、次はindex=4(5駅目/最後) -> 残り1駅
      final remainingStops = stepForDisplay.stops.length - nextStop;

      // 次のバス停名
      String nextStopName = "";
      if (nextStop < stepForDisplay.stops.length) {
        nextStopName = stepForDisplay.stops[nextStop].name;
      }

      // 残りが0以下または次が最後の駅（降りる駅）の場合
      // バスの降りるボタン等は、最後の駅の一つ前を出た後に押すが、
      // ここでは「最後の駅を目指している」状態になったら「まもなく降車」とする
      if (remainingStops <= 1) {
        final destinationName =
            stepForDisplay.to ?? (stepForDisplay.stops.isNotEmpty ? stepForDisplay.stops.last.name : "目的地");
        debugPrint('[TripNavigator] RETURN curStep=$currentStep nextStop=$nextStop kind=${stepForDisplay.kind} remaining=$remainingStops (arriving)');
        return RouteNavState(
          mainText: "まもなく降車",
          subText: "$destinationName で降ります",
          color: const Color(0xFFFFAB91), // 赤
          currentStepIndex: currentStep,
          nextStopIndex: nextStop,
          statusLabel: "到着まもなく",
          nextStopName: destinationName,
          remainingStops: remainingStops,
          isMoving: true,
        );
      } else {
        // まだ乗っている
        debugPrint('[TripNavigator] RETURN curStep=$currentStep nextStop=$nextStop kind=${stepForDisplay.kind} remaining=$remainingStops next=$nextStopName');
        return RouteNavState(
          mainText: "あと $remainingStops 駅",
          subText: "つぎは $nextStopName",
          color: const Color(0xFF81D4FA), // 青
          currentStepIndex: currentStep,
          nextStopIndex: nextStop,
          statusLabel: "移動中",
          nextStopName: nextStopName,
          remainingStops: remainingStops,
          isMoving: true,
        );
      }
    }
  }

  // --- Helper States ---
  static RouteNavState _completedRouteState() => const RouteNavState(
        mainText: "終了",
        subText: "お疲れ様でした",
        color: Colors.grey,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "旅は完了",
      );

  static RouteNavState _errorRouteState() => const RouteNavState(
        mainText: "エラー",
        subText: "ルートがありません",
        color: Colors.red,
        currentStepIndex: 0,
        nextStopIndex: 0,
        statusLabel: "案内できません",
      );

  static RouteNavState _arrivedRouteState() => const RouteNavState(
        mainText: "到着",
        subText: "目的地周辺です",
        color: Colors.orange,
        currentStepIndex: 999,
        nextStopIndex: 999,
        statusLabel: "到着",
        nextStopName: "目的地",
        remainingStops: 0,
      );

  /// GPSに基づいて、ユーザーが実際にいるステップを推定する
  /// 各ステップの停留所との距離を計算し、最も近いステップと距離を返す
  static (int, double) _estimateCurrentStepIndexWithDistance({
    required List<StepSeg> allSteps,
    required LatLng currentPos,
    required int lastStepIndex,
    int minSearchIndex = 0,
    int? maxSearchIndex,
  }) {
    if (allSteps.isEmpty) return (lastStepIndex, double.infinity);

    int bestStepIndex = lastStepIndex;
    double minDistance = double.infinity;

    final end = maxSearchIndex ?? allSteps.length;

    for (int i = minSearchIndex; i < end; i++) {
      final step = allSteps[i];
      
      // 徒歩ステップの場合、次のステップの最初の停留所を目標とする
      if (step.kind == 'walk') {
        // 次のステップがあれば、その最初の停留所との距離を計算
        if (i + 1 < allSteps.length) {
          final nextStep = allSteps[i + 1];
          if (nextStep.stops.isNotEmpty) {
            final target = nextStep.stops.first;
            final lat = target.lat;
            final lon = target.lon;
            if (lat != null && lon != null) {
              final d = Geolocator.distanceBetween(
                currentPos.latitude, currentPos.longitude,
                lat, lon,
              );
              if (d < minDistance) {
                minDistance = d;
                bestStepIndex = i;
              }
            }
          }
        }
      }
      // バス・電車ステップの場合、全停留所との距離を計算
      else if (step.stops.isNotEmpty) {
        for (final stop in step.stops) {
          final lat = stop.lat;
          final lon = stop.lon;
          if (lat == null || lon == null) continue;
          final d = Geolocator.distanceBetween(
            currentPos.latitude, currentPos.longitude,
            lat, lon,
          );
          if (d < minDistance) {
            minDistance = d;
            bestStepIndex = i;
          }
        }
      }
    }

    // 推定されたステップが前に戻る（巻き戻り）場合、
    // 距離がかなり近い（500m以内）場合のみ許可する
    // それ以外は前回値を維持（GPSブレ対策）
    if (bestStepIndex < lastStepIndex && minDistance > 500) {
      debugPrint('[TripNavigator] Estimate rejected (far backward): best=$bestStepIndex last=$lastStepIndex dist=${minDistance.toStringAsFixed(0)}m');
      return (lastStepIndex, double.infinity);
    }

    debugPrint('[TripNavigator] Estimated step: $bestStepIndex (dist: ${minDistance.toStringAsFixed(0)}m)');
    return (bestStepIndex, minDistance);
  }

  /// バス・電車ステップ内の「次に目指すべき停留所インデックス」をGPSで推定する
  static int _estimateNextStopIndex({
    required StepSeg step,
    required LatLng currentPos,
    required int lastStopIndex,
  }) {
    if (step.stops.isEmpty) return lastStopIndex;

    int bestIndex = lastStopIndex;
    double minDist = double.infinity;

    for (int i = 0; i < step.stops.length; i++) {
      final stop = step.stops[i];
      final lat = stop.lat;
      final lon = stop.lon;
      if (lat == null || lon == null) continue;

      final d = Geolocator.distanceBetween(
        currentPos.latitude,
        currentPos.longitude,
        lat,
        lon,
      );

      if (d < minDist) {
        minDist = d;
        bestIndex = i;
      }
    }

    // 到着判定: 近い停留所に80m以内にいる場合、その次を目標にする
    if (minDist < _arrivalRadius) {
      final next = (bestIndex + 1).clamp(0, step.stops.length);
      debugPrint('[TripNavigator] Near stop $bestIndex (${minDist.toStringAsFixed(0)}m), targeting next: $next');
      return next;
    }

    // 巻き戻り防止: 後ろに戻らない
    if (bestIndex < lastStopIndex) return lastStopIndex;

    debugPrint('[TripNavigator] Estimated next stop: $bestIndex (dist: ${minDist.toStringAsFixed(0)}m)');
    return bestIndex;
  }
}

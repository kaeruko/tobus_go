import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/group_models.dart';
import '../models/trip_models.dart';

/// メンバーモードにおける現在の進行状況（どのステップのどの停留所にいるか）を保持するクラス
class MemberNavState {
  /// 現在進行中のステップのインデックス (legs.steps 全体の中での通し番号)
  final int currentStepIndex;
  /// 現在のステップ内での次の停留所インデックス (0始まり。0なら始発待ち、NならN番目の停留所へ向かっている)
  final int nextStopIndex;

  const MemberNavState({
    required this.currentStepIndex,
    required this.nextStopIndex,
  });

  factory MemberNavState.initial() => const MemberNavState(currentStepIndex: 0, nextStopIndex: 0);

  MemberNavState copyWith({int? currentStepIndex, int? nextStopIndex}) {
    return MemberNavState(
      currentStepIndex: currentStepIndex ?? this.currentStepIndex,
      nextStopIndex: nextStopIndex ?? this.nextStopIndex,
    );
  }
}

/// メンバーの進行状況を管理するNotifier
/// 主に `MemberModeController` から、時間経過やAPIの結果に基づいて更新される。
class MemberNavProgressNotifier extends StateNotifier<MemberNavState> {
  MemberNavProgressNotifier() : super(MemberNavState.initial());

  /// スケジュール(`activeEntry`)に基づいて、現在のステップ位置を更新する。
  /// 
  /// **注意:** このメソッド自体は「現在どのステップにいるか（時間の推定）」は行いません。
  /// それは呼び出し元の `ScheduleResolver` が計算し、その結果が引数の `activeEntry` として渡されてきます。
  /// このメソッドは、渡された `activeEntry` の情報（routeStepIndex）を、
  /// アプリ内の状態管理クラス(`MemberNavState`)に反映させる役割を持ちます。
  /// 
  /// - [trip]: 現在の旅程データ
  /// - [activeEntry]: 現在時刻におけるアクティブなスケジュール項目 (ここで推定済みのステップ番号が入っている)
  /// - [forceStopIndex]: APIから取得した「現在のバス停位置」がある場合に指定する
  void updateFromSchedule(Trip trip, ScheduleEntry activeEntry, {int? forceStopIndex}) {
    // -------------------------------------------------------------
    // Tripデータの構造変換 (階層データ -> フラットなリスト)
    // -------------------------------------------------------------
    // 元のTripデータは [Trip] -> [Leg(区間)] -> [Step(移動手段)] という3階層構造ですが、
    // activeEntry.routeStepIndex は「旅全体を通して前から何番目のステップか」という
    // "通し番号" で管理されています。
    // そのため、階層構造のままでは「N番目のステップ」を直接取得できないので、
    // 一旦すべてのStepを一本のリスト(allSteps)に平坦化(expand)して並べ直しています。
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    final targetStepIndex = activeEntry.routeStepIndex!;

    // 通し番号が有効範囲内かチェック
    if (targetStepIndex < 0 || targetStepIndex >= allSteps.length) return;

    // 通し番号を使って、実際のStepデータを取り出す
    final step = allSteps[targetStepIndex];
    // そのStepに含まれる停留所の最大インデックス（例: 停留所が5つあれば、インデックスの最大は4）
    // これを使って、nextStopIndex が範囲外にならないように計算に使います。
    final maxStopIndex = step.stops.isNotEmpty ? step.stops.length - 1 : 0;

    // ここでの `state` は、更新前の「現在の StateNotifier が保持している MemberNavState」です。
    // MemberNavState は `currentStepIndex` と `nextStopIndex` の両方を持っています。
    // ここでは、新しい状態を作るためのベースとして、一旦現在の nextStopIndex を取得しています。
    int nextStopIndex = state.nextStopIndex;
    
    // StopIndexの決定ロジック
    // 1. API等からの強制指定(APIでバスの現在地が分かった時)があれば優先採用
    if (forceStopIndex != null) {
      nextStopIndex = forceStopIndex.clamp(0, maxStopIndex).toInt();
    } 
    // 2. ステップ自体が変わった場合は StopIndex を 0 (最初) にリセット
    else if (targetStepIndex != state.currentStepIndex) {
      nextStopIndex = 0;
    } 
    // 3. 同じステップで継続中の場合は、範囲内に収まるようにだけ補正して維持
    else {
      nextStopIndex = nextStopIndex.clamp(0, maxStopIndex).toInt();
    }

    if (state.currentStepIndex != targetStepIndex || state.nextStopIndex != nextStopIndex) {
      state = MemberNavState(
        currentStepIndex: targetStepIndex,
        nextStopIndex: nextStopIndex,
      );
    }
  }

  /// 強制的にインデックスを指定する場合（デバッグや特定イベント用）
  void setIndices({required int stepIndex, required int stopIndex}) {
    if (stepIndex != state.currentStepIndex || stopIndex != state.nextStopIndex) {
      state = MemberNavState(
        currentStepIndex: stepIndex,
        nextStopIndex: stopIndex,
      );
    }
  }
  
  /// 状態を初期値に戻す
  void reset() {
    state = MemberNavState.initial();
  }
}

final memberNavProgressProvider = StateNotifierProvider<MemberNavProgressNotifier, MemberNavState>((ref) {
  return MemberNavProgressNotifier();
});

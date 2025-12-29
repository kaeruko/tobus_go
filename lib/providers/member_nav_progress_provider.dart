import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import '../models/trip_models.dart';
import '../logic/trip_navigator.dart';

class MemberNavState {
  final int currentStepIndex;
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

class MemberNavProgressNotifier extends StateNotifier<MemberNavState> {
  MemberNavProgressNotifier() : super(MemberNavState.initial());

  /// GPS位置と、必要に応じてAPIからの強制補正(forceStopIndex)を用いて進捗を更新する
  void updateProgress(Trip trip, LatLng? currentPos, {int? forceStopIndex}) {
    if (currentPos == null) return;
    
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    
    // 計算用の可変Stateを作成
    final routeState = RouteState(
      steps: allSteps,
      currentStepIndex: state.currentStepIndex,
      nextStopIndex: state.nextStopIndex,
      isMoving: true,
    );

    // TripNavigatorで計算（API補正値があればそれも考慮）
    TripNavigator.updateRouteOnly(
       routeState,
       currentPos,
       forceStopIndex: forceStopIndex,
    );
    
    // 変更があればStateを更新
    if (routeState.currentStepIndex != state.currentStepIndex || 
        routeState.nextStopIndex != state.nextStopIndex) {
      state = MemberNavState(
        currentStepIndex: routeState.currentStepIndex,
        nextStopIndex: routeState.nextStopIndex,
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
  
  void reset() {
    state = MemberNavState.initial();
  }
}

final memberNavProgressProvider = StateNotifierProvider<MemberNavProgressNotifier, MemberNavState>((ref) {
  return MemberNavProgressNotifier();
});
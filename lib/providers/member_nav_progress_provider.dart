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

  void updateProgress(Trip trip, LatLng? currentPos) {
    if (currentPos == null) return;
    
    // Construct mutable RouteState from current immutable state
    // legsから全てのstepを展開して1つのリストにする
    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    
    final routeState = RouteState(
      steps: allSteps,
      currentStepIndex: state.currentStepIndex,
      nextStopIndex: state.nextStopIndex,
      isMoving: true, // Defaulting to true for active update
    );

    // Call mutable update
    TripNavigator.updateRouteOnly(
       routeState,
       currentPos,
    );
    
    // Only update if indices changed, to avoid unnecessary rebuilds downstream if used elsewhere
    if (routeState.currentStepIndex != state.currentStepIndex || 
        routeState.nextStopIndex != state.nextStopIndex) {
      state = MemberNavState(
        currentStepIndex: routeState.currentStepIndex,
        nextStopIndex: routeState.nextStopIndex,
      );
    }
  }

  /// GPS補正後のインデックスを直接設定する
  /// MemberModePageでrouteStateの補正結果を反映するために使用
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

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/group_models.dart';
import '../models/trip_models.dart';

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

  /// スケジュールのアクティブ項目からインデックスを更新する
  void updateFromSchedule(Trip trip, ScheduleEntry? activeEntry, {int? forceStopIndex}) {
    if (activeEntry?.routeStepIndex == null) return;

    final allSteps = trip.legs.expand((leg) => leg.candidate.steps).toList();
    final targetStepIndex = activeEntry!.routeStepIndex!;

    if (targetStepIndex < 0 || targetStepIndex >= allSteps.length) return;

    final step = allSteps[targetStepIndex];
    final maxStopIndex = step.stops.isNotEmpty ? step.stops.length - 1 : 0;

    int nextStopIndex = state.nextStopIndex;
    if (forceStopIndex != null) {
      nextStopIndex = forceStopIndex.clamp(0, maxStopIndex).toInt();
    } else if (targetStepIndex != state.currentStepIndex) {
      nextStopIndex = 0;
    } else {
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
  
  void reset() {
    state = MemberNavState.initial();
  }
}

final memberNavProgressProvider = StateNotifierProvider<MemberNavProgressNotifier, MemberNavState>((ref) {
  return MemberNavProgressNotifier();
});
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/trip_models.dart';

class MemberNavState {
  final String? currentStepId;
  final BusProgress? busProgress;

  const MemberNavState({
    required this.currentStepId,
    required this.busProgress,
  });

  const MemberNavState.initial() : currentStepId = null, busProgress = null;
}

class MemberNavProgressNotifier extends StateNotifier<MemberNavState> {
  MemberNavProgressNotifier() : super(const MemberNavState.initial());

  void updateFromSchedule(
    Trip trip,
    ScheduleEntry? activeEntry, {
    BusProgress? busProgress,
  }) {
    final stepId = activeEntry?.routeStepId;
    if (stepId == null) {
      if (state.currentStepId != null || state.busProgress != null) {
        state = const MemberNavState.initial();
      }
      return;
    }

    final step = trip.stepsById[stepId];
    if (step == null) {
      throw StateError('予定が存在しないrouteStepIdを参照しています: $stepId');
    }
    if (busProgress != null && busProgress.stepId != stepId) {
      throw StateError(
        'BusProgressが別のstepを参照しています: '
        '${busProgress.stepId} != $stepId',
      );
    }

    final nextProgress = step.isRide ? busProgress : null;
    if (state.currentStepId != stepId || state.busProgress != nextProgress) {
      state = MemberNavState(currentStepId: stepId, busProgress: nextProgress);
    }
  }

  void setProgress({required String stepId, BusProgress? busProgress}) {
    if (busProgress != null && busProgress.stepId != stepId) {
      throw ArgumentError('stepId and BusProgress.stepId must match');
    }
    state = MemberNavState(currentStepId: stepId, busProgress: busProgress);
  }

  void reset() {
    state = const MemberNavState.initial();
  }
}

final memberNavProgressProvider =
    StateNotifierProvider<MemberNavProgressNotifier, MemberNavState>((ref) {
      return MemberNavProgressNotifier();
    });

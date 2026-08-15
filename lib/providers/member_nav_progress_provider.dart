import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/rail_progress.dart';
import '../models/trip_models.dart';

class MemberNavState {
  final String? currentStepId;
  final BusProgress? busProgress;
  final RailProgress? railProgress;

  const MemberNavState({
    required this.currentStepId,
    required this.busProgress,
    required this.railProgress,
  });

  const MemberNavState.initial()
    : currentStepId = null,
      busProgress = null,
      railProgress = null;
}

class MemberNavProgressNotifier extends StateNotifier<MemberNavState> {
  MemberNavProgressNotifier() : super(const MemberNavState.initial());

  void updateFromSchedule(
    Trip trip,
    ScheduleEntry? activeEntry, {
    BusProgress? busProgress,
    RailProgress? railProgress,
  }) {
    if (busProgress != null && railProgress != null) {
      throw ArgumentError('busProgress and railProgress cannot both be set');
    }

    final stepId = activeEntry?.routeStepId;
    if (stepId == null) {
      if (state.currentStepId != null ||
          state.busProgress != null ||
          state.railProgress != null) {
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
    if (railProgress != null && railProgress.stepId != stepId) {
      throw StateError(
        'RailProgressが別のstepを参照しています: '
        '${railProgress.stepId} != $stepId',
      );
    }
    if (busProgress != null && step.kind != 'bus') {
      throw StateError(
        'BusProgressがbus以外のstepを参照しています: '
        'stepId=$stepId kind=${step.kind}',
      );
    }
    if (railProgress != null && step.kind != 'rail') {
      throw StateError(
        'RailProgressがrail以外のstepを参照しています: '
        'stepId=$stepId kind=${step.kind}',
      );
    }

    final nextBusProgress = step.kind == 'bus' ? busProgress : null;
    final nextRailProgress = step.kind == 'rail' ? railProgress : null;
    if (state.currentStepId != stepId ||
        state.busProgress != nextBusProgress ||
        state.railProgress != nextRailProgress) {
      state = MemberNavState(
        currentStepId: stepId,
        busProgress: nextBusProgress,
        railProgress: nextRailProgress,
      );
    }
  }

  void setProgress({
    required String stepId,
    BusProgress? busProgress,
    RailProgress? railProgress,
  }) {
    if (busProgress != null && railProgress != null) {
      throw ArgumentError('busProgress and railProgress cannot both be set');
    }
    if (busProgress != null && busProgress.stepId != stepId) {
      throw ArgumentError('stepId and BusProgress.stepId must match');
    }
    if (railProgress != null && railProgress.stepId != stepId) {
      throw ArgumentError('stepId and RailProgress.stepId must match');
    }
    state = MemberNavState(
      currentStepId: stepId,
      busProgress: busProgress,
      railProgress: railProgress,
    );
  }

  void reset() {
    state = const MemberNavState.initial();
  }
}

final memberNavProgressProvider =
    StateNotifierProvider<MemberNavProgressNotifier, MemberNavState>((ref) {
      return MemberNavProgressNotifier();
    });

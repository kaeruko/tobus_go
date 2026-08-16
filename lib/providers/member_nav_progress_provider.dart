import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/bus_progress.dart';
import '../models/group_models.dart';
import '../models/rail_progress.dart';
import '../models/trip_models.dart';

class MemberNavState {
  final String? currentStepId;
  final BusProgress? busProgress;
  final RailProgress? railProgress;
  final bool rideRealtimeUnavailable;

  const MemberNavState({
    required this.currentStepId,
    required this.busProgress,
    required this.railProgress,
    this.rideRealtimeUnavailable = false,
  });

  const MemberNavState.initial()
    : currentStepId = null,
      busProgress = null,
      railProgress = null,
      rideRealtimeUnavailable = false;
}

class MemberNavProgressNotifier extends StateNotifier<MemberNavState> {
  MemberNavProgressNotifier() : super(const MemberNavState.initial());

  void updateFromSchedule(
    Trip trip,
    ScheduleEntry? activeEntry, {
    BusProgress? busProgress,
    RailProgress? railProgress,
    bool rideRealtimeUnavailable = false,
  }) {
    if (busProgress != null && railProgress != null) {
      throw ArgumentError('busProgress and railProgress cannot both be set');
    }

    final stepId = activeEntry?.routeStepId;
    if (stepId == null) {
      if (state.currentStepId != null ||
          state.busProgress != null ||
          state.railProgress != null ||
          state.rideRealtimeUnavailable) {
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
    if (rideRealtimeUnavailable && !step.isRide) {
      throw StateError(
        'Realtime一時欠落フラグが乗車step以外に設定されました: '
        'stepId=$stepId kind=${step.kind}',
      );
    }
    if (rideRealtimeUnavailable &&
        (busProgress != null || railProgress != null)) {
      throw StateError(
        'Realtime一時欠落中なのに新しい乗車進捗が同時に渡されました: stepId=$stepId',
      );
    }

    BusProgress? nextBusProgress = step.kind == 'bus' ? busProgress : null;
    RailProgress? nextRailProgress = step.kind == 'rail' ? railProgress : null;

    // Once actual boarding has been confirmed, a temporary realtime gap must
    // not turn the navigation UI back into a pre-boarding "waiting" state.
    // Keep only the last already-displayed riding progress as historical UI
    // context; replan/delay logic still uses ReplanTransitMemory and remains
    // blocked until fresh realtime returns.
    if (rideRealtimeUnavailable && state.currentStepId == stepId) {
      if (step.kind == 'bus' &&
          state.busProgress?.phase == BusProgressPhase.riding) {
        nextBusProgress = state.busProgress;
      } else if (step.kind == 'rail' &&
          state.railProgress?.phase == RailProgressPhase.riding) {
        nextRailProgress = state.railProgress;
      }
    }

    if (state.currentStepId != stepId ||
        state.busProgress != nextBusProgress ||
        state.railProgress != nextRailProgress ||
        state.rideRealtimeUnavailable != rideRealtimeUnavailable) {
      state = MemberNavState(
        currentStepId: stepId,
        busProgress: nextBusProgress,
        railProgress: nextRailProgress,
        rideRealtimeUnavailable: rideRealtimeUnavailable,
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

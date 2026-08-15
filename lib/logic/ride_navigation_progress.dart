import '../models/bus_progress.dart';
import '../models/rail_progress.dart';
import '../models/route_models.dart';

enum RideNavigationPhase { approaching, riding, arrived }

/// バス・鉄道それぞれのリアルタイム進捗を、ナビ表示で共通に扱うための値へ正規化する。
///
/// 交通機関固有のIDやGTFS解釈は各Progress側に残し、ここでは
/// 「現在地・次の停車地・残り停車数・乗車地点までの残り」だけを扱う。
class RideNavigationProgress {
  final String stepId;
  final RideNavigationPhase phase;
  final String? currentPlaceName;
  final String? nextPlaceName;
  final int? remainingStops;
  final int? stopsUntilBoarding;
  final double? vehicleAgeSeconds;

  const RideNavigationProgress({
    required this.stepId,
    required this.phase,
    this.currentPlaceName,
    this.nextPlaceName,
    this.remainingStops,
    this.stopsUntilBoarding,
    this.vehicleAgeSeconds,
  });

  factory RideNavigationProgress.fromBus({
    required StepSeg step,
    required BusProgress progress,
  }) {
    if (step.kind != 'bus') {
      throw StateError(
        'BusProgressをbus以外のstepへ正規化できません: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }
    if (progress.stepId != step.stepId) {
      throw StateError(
        'BusProgressのstepIdが一致しません: '
        '${progress.stepId} != ${step.stepId}',
      );
    }
    if (step.stops.isEmpty) {
      throw StateError('停留所のないバスStepです: stepId=${step.stepId}');
    }

    if (progress.phase == BusProgressPhase.approaching) {
      final stopsUntilBoarding = progress.stopsUntilBoarding;
      if (stopsUntilBoarding == null || stopsUntilBoarding <= 0) {
        throw StateError(
          '接近中のバスに乗車停留所までの停留所数がありません: '
          'stepId=${step.stepId}, stopsUntilBoarding=$stopsUntilBoarding',
        );
      }
      return RideNavigationProgress(
        stepId: step.stepId,
        phase: RideNavigationPhase.approaching,
        currentPlaceName: progress.observedStopName,
        nextPlaceName: step.stops.first.name,
        stopsUntilBoarding: stopsUntilBoarding,
        vehicleAgeSeconds: progress.vehicleAgeSeconds,
      );
    }

    final fromIndex = progress.fromStopIndex;
    if (fromIndex == null || fromIndex < 0 || fromIndex >= step.stops.length) {
      throw StateError('BusProgressのfromStopIndexが範囲外です: $fromIndex');
    }

    final destinationIndex = step.stops.length - 1;
    final remaining = destinationIndex - fromIndex;
    final currentName = step.stops[fromIndex].name;
    final nextIndex = progress.nextStopIndex;
    final nextName = nextIndex != null && nextIndex < step.stops.length
        ? step.stops[nextIndex].name
        : null;

    if (progress.phase == BusProgressPhase.arrived || remaining <= 0) {
      return RideNavigationProgress(
        stepId: step.stepId,
        phase: RideNavigationPhase.arrived,
        currentPlaceName: currentName,
        remainingStops: 0,
        vehicleAgeSeconds: progress.vehicleAgeSeconds,
      );
    }

    return RideNavigationProgress(
      stepId: step.stepId,
      phase: RideNavigationPhase.riding,
      currentPlaceName: currentName,
      nextPlaceName: nextName,
      remainingStops: remaining,
      vehicleAgeSeconds: progress.vehicleAgeSeconds,
    );
  }

  factory RideNavigationProgress.fromRail({
    required StepSeg step,
    required RailProgress progress,
  }) {
    if (step.kind != 'rail') {
      throw StateError(
        'RailProgressをrail以外のstepへ正規化できません: '
        'stepId=${step.stepId}, kind=${step.kind}',
      );
    }
    if (progress.stepId != step.stepId) {
      throw StateError(
        'RailProgressのstepIdが一致しません: '
        '${progress.stepId} != ${step.stepId}',
      );
    }

    switch (progress.phase) {
      case RailProgressPhase.approaching:
        final stopsUntilBoarding = progress.stopsUntilBoarding;
        if (stopsUntilBoarding == null || stopsUntilBoarding <= 0) {
          throw StateError(
            '接近中の列車に乗車駅までの駅数がありません: '
            'stepId=${step.stepId}, stopsUntilBoarding=$stopsUntilBoarding',
          );
        }
        return RideNavigationProgress(
          stepId: step.stepId,
          phase: RideNavigationPhase.approaching,
          currentPlaceName: progress.currentStopName,
          nextPlaceName: progress.nextStopName,
          stopsUntilBoarding: stopsUntilBoarding,
          vehicleAgeSeconds: progress.vehicleAgeSeconds,
        );
      case RailProgressPhase.riding:
        if (progress.remainingStops <= 0) {
          throw StateError(
            '乗車中の列車のremainingStopsが不正です: '
            'stepId=${step.stepId}, remainingStops=${progress.remainingStops}',
          );
        }
        return RideNavigationProgress(
          stepId: step.stepId,
          phase: RideNavigationPhase.riding,
          currentPlaceName: progress.currentStopName,
          nextPlaceName: progress.nextStopName,
          remainingStops: progress.remainingStops,
          vehicleAgeSeconds: progress.vehicleAgeSeconds,
        );
      case RailProgressPhase.arrived:
        return RideNavigationProgress(
          stepId: step.stepId,
          phase: RideNavigationPhase.arrived,
          currentPlaceName: progress.currentStopName,
          remainingStops: 0,
          vehicleAgeSeconds: progress.vehicleAgeSeconds,
        );
    }
  }
}

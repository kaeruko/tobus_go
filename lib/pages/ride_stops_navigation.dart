import 'package:flutter/material.dart';

import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import 'segment_stops_page.dart';

void openRideStops({
  required BuildContext context,
  required Trip trip,
  required ScheduleEntry entry,
}) {
  if (entry.itemKind != ScheduleEntryKind.ride) {
    throw StateError(
      '乗車以外の予定から停留所一覧を開こうとしました: '
      'entryId=${entry.id}, kind=${entry.itemKind}',
    );
  }

  final stepId = entry.routeStepId;
  if (stepId == null || stepId.isEmpty) {
    throw StateError(
      '乗車予定にrouteStepIdがありません: '
      'entryId=${entry.id}, label=${entry.label}',
    );
  }

  final step = trip.stepsById[stepId];
  if (step == null) {
    throw StateError(
      '乗車予定が存在しないrouteStepIdを参照しています: '
      'entryId=${entry.id}, routeStepId=$stepId',
    );
  }
  if (!step.isRide) {
    throw StateError(
      '乗車予定のrouteStepIdが乗車ステップではありません: '
      'entryId=${entry.id}, routeStepId=$stepId, kind=${step.kind}',
    );
  }
  if (step.stops.isEmpty) {
    throw StateError(
      '乗車ステップに停留所情報がありません: '
      'entryId=${entry.id}, routeStepId=$stepId',
    );
  }

  _openRideStepStops(context: context, step: step);
}

/// 現在のナビ step が停留所・駅一覧を開ける乗車区間なら返す。
///
/// 徒歩・待機中や currentStepId 未確定は「開く対象がない」ため null。
/// 一方、存在しない stepId は状態不整合なので fail-fast する。
StepSeg? resolveCurrentRideStep({
  required Trip trip,
  required String? currentStepId,
}) {
  if (currentStepId == null || currentStepId.isEmpty) return null;

  final step = trip.stepsById[currentStepId];
  if (step == null) {
    throw StateError(
      '現在のナビが存在しないrouteStepIdを参照しています: $currentStepId',
    );
  }
  if (!step.isRide || step.stops.isEmpty) return null;
  return step;
}

void openCurrentRideStops({
  required BuildContext context,
  required Trip trip,
  required String? currentStepId,
}) {
  final step = resolveCurrentRideStep(
    trip: trip,
    currentStepId: currentStepId,
  );
  if (step == null) return;

  _openRideStepStops(context: context, step: step);
}

void _openRideStepStops({
  required BuildContext context,
  required StepSeg step,
}) {
  Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => SegmentStopsPage(segment: step),
    ),
  );
}

import 'package:flutter/material.dart';

import '../models/group_models.dart';
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

  Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => SegmentStopsPage(segment: step),
    ),
  );
}

import 'package:flutter/material.dart';

import '../logic/transfer_walk_details.dart';
import '../models/group_models.dart';
import '../models/route_models.dart';
import '../models/trip_models.dart';
import '../widgets/route_detail_widgets.dart';
import '../widgets/transfer_walk_sheet.dart';
import 'segment_stops_page.dart';

enum _ScheduleEntryDetailsKind { stops, transfer }

class _ScheduleEntryDetailsTarget {
  final _ScheduleEntryDetailsKind kind;
  final Candidate candidate;
  final StepSeg step;
  final TransferWalkDetails? transfer;

  const _ScheduleEntryDetailsTarget({
    required this.kind,
    required this.candidate,
    required this.step,
    this.transfer,
  });
}

/// 「経路全体を見る」の各ステップと同じ詳細を開ける予定行か判定する。
bool canOpenScheduleEntryDetails({
  required Trip trip,
  required ScheduleEntry entry,
}) {
  return _scheduleEntryDetailsTarget(trip: trip, entry: entry) != null;
}

/// 予定行から、経路全体画面と同じ停留所一覧または乗換案内を開く。
void openScheduleEntryDetails({
  required BuildContext context,
  required Trip trip,
  required ScheduleEntry entry,
}) {
  final target = _scheduleEntryDetailsTarget(trip: trip, entry: entry);
  if (target == null) return;

  switch (target.kind) {
    case _ScheduleEntryDetailsKind.stops:
      _openRideStepStops(
        context: context,
        step: target.step,
        referenceTime: target.step.kind == 'bus'
            ? routeStepTimetableReferenceTime(target.candidate, target.step)
            : null,
      );
      return;
    case _ScheduleEntryDetailsKind.transfer:
      showTransferWalkSheet(context, target.transfer!);
      return;
  }
}

_ScheduleEntryDetailsTarget? _scheduleEntryDetailsTarget({
  required Trip trip,
  required ScheduleEntry entry,
}) {
  if (entry.generatedBy != ScheduleEntrySource.route) return null;

  final stepId = entry.routeStepId?.trim();
  if (stepId == null || stepId.isEmpty) return null;

  final step = trip.stepsById[stepId];
  final candidate = trip.candidatesByStepId[stepId];
  if (step == null || candidate == null) {
    throw StateError(
      '予定行が存在しないrouteStepIdを参照しています: '
      'entryId=${entry.id}, routeStepId=$stepId',
    );
  }

  if (step.isRide) {
    if (step.stops.isEmpty) return null;
    return _ScheduleEntryDetailsTarget(
      kind: _ScheduleEntryDetailsKind.stops,
      candidate: candidate,
      step: step,
    );
  }

  if (step.kind != 'walk' && step.kind != 'wait') return null;
  final stepIndex = candidate.steps.indexWhere(
    (candidateStep) => candidateStep.stepId == stepId,
  );
  if (stepIndex < 0) {
    throw StateError(
      '予定行のrouteStepIdがCandidateにありません: '
      'entryId=${entry.id}, routeStepId=$stepId, '
      'candidateId=${candidate.id}',
    );
  }
  final transfer = TransferWalkDetails.forStep(candidate.steps, stepIndex);
  if (transfer == null) return null;
  return _ScheduleEntryDetailsTarget(
    kind: _ScheduleEntryDetailsKind.transfer,
    candidate: candidate,
    step: step,
    transfer: transfer,
  );
}

void openRideStops({
  required BuildContext context,
  required Trip trip,
  required ScheduleEntry entry,
}) {
  final step = _rideStepForEntry(trip: trip, entry: entry);
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

StepSeg? resolveNavigationRideStep({
  required Trip trip,
  required ScheduleEntry? resolvedEntry,
  required String? currentStepId,
}) {
  if (resolvedEntry != null) {
    if (resolvedEntry.itemKind == ScheduleEntryKind.ride) {
      return _rideStepForEntry(trip: trip, entry: resolvedEntry);
    }

    if (resolvedEntry.routeRole == 'wait_start' ||
        resolvedEntry.itemKind == ScheduleEntryKind.walk) {
      return _nextRideStepAfterEntry(
        trip: trip,
        entry: resolvedEntry,
      );
    }
  }

  return resolveCurrentRideStep(
    trip: trip,
    currentStepId: currentStepId,
  );
}

void openNavigationRideStops({
  required BuildContext context,
  required Trip trip,
  required ScheduleEntry? resolvedEntry,
  required String? currentStepId,
}) {
  final step = resolveNavigationRideStep(
    trip: trip,
    resolvedEntry: resolvedEntry,
    currentStepId: currentStepId,
  );
  if (step == null) return;
  _openRideStepStops(context: context, step: step);
}

StepSeg _rideStepForEntry({
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
  return step;
}

StepSeg _nextRideStepAfterEntry({
  required Trip trip,
  required ScheduleEntry entry,
}) {
  final legIndex = entry.legIndex;
  if (legIndex < 0 || legIndex >= trip.legs.length) {
    throw StateError(
      '次の乗車を探す予定のlegIndexが不正です: '
      'entryId=${entry.id}, legIndex=$legIndex, legs=${trip.legs.length}',
    );
  }

  final stepId = entry.routeStepId;
  if (stepId == null || stepId.isEmpty) {
    throw StateError(
      '次の乗車を探す現在予定にrouteStepIdがありません: '
      'entryId=${entry.id}, role=${entry.routeRole}',
    );
  }

  final candidate = trip.legs[legIndex].candidate;
  final stepIndex = candidate.steps.indexWhere((step) => step.stepId == stepId);
  if (stepIndex < 0) {
    throw StateError(
      '次の乗車を探す現在stepが対象legのCandidateにありません: '
      'entryId=${entry.id}, stepId=$stepId, candidateId=${candidate.id}',
    );
  }

  final currentStep = candidate.steps[stepIndex];
  if (entry.routeRole == 'wait_start' && currentStep.kind != 'wait') {
    throw StateError(
      'wait_start予定がwait stepを参照していません: '
      'entryId=${entry.id}, stepId=$stepId, kind=${currentStep.kind}',
    );
  }
  if (entry.itemKind == ScheduleEntryKind.walk && currentStep.kind != 'walk') {
    throw StateError(
      'walk予定がwalk stepを参照していません: '
      'entryId=${entry.id}, stepId=$stepId, kind=${currentStep.kind}',
    );
  }

  for (var index = stepIndex + 1; index < candidate.steps.length; index++) {
    final step = candidate.steps[index];
    if (!step.isRide) continue;
    if (step.stops.isEmpty) {
      throw StateError(
        '次の乗車stepに停留所情報がありません: '
        'entryId=${entry.id}, stepId=${step.stepId}',
      );
    }
    return step;
  }

  throw StateError(
    '現在の案内に対応する次の乗車stepがCandidateにありません: '
    'entryId=${entry.id}, stepId=$stepId, candidateId=${candidate.id}',
  );
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
  DateTime? referenceTime,
}) {
  Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => SegmentStopsPage(
        segment: step,
        referenceTime: referenceTime,
      ),
    ),
  );
}

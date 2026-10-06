import 'package:flutter/foundation.dart';

import '../models/group_models.dart';
import '../models/leg_models.dart';
import '../models/trip_models.dart';

Leg resolveGroupActiveLeg(Trip trip) {
  if (trip.tripType != TripType.group) {
    throw StateError(
      'Group active leg resolverにGroup以外のtripが渡されました: '
      'tripId=${trip.id}, type=${trip.tripType.name}',
    );
  }

  final activeLegIndex = trip.activeLegIndex;
  if (activeLegIndex < 0 || activeLegIndex >= trip.legs.length) {
    throw StateError(
      'Groupのactive legを特定できません: '
      'tripId=${trip.id}, activeLegIndex=$activeLegIndex, '
      'legs=${trip.legs.length}, completedLegIndex=${trip.completedLegIndex}',
    );
  }
  return trip.legs[activeLegIndex];
}

ScheduleEntry navigationEntryWithFixedTransitClock(
  Trip trip,
  ScheduleEntry entry,
) {
  if (entry.itemKind != ScheduleEntryKind.ride &&
      entry.itemKind != ScheduleEntryKind.arrival) {
    return entry;
  }

  final stepId = entry.routeStepId;
  if (stepId == null || stepId.isEmpty) {
    throw StateError(
      '乗車系予定にrouteStepIdがありません: '
      'tripId=${trip.id}, entryId=${entry.id}, kind=${entry.itemKind.name}',
    );
  }
  final step = trip.stepsById[stepId];
  if (step == null) {
    throw StateError(
      '乗車系予定が存在しないrouteStepIdを参照しています: '
      'tripId=${trip.id}, entryId=${entry.id}, routeStepId=$stepId',
    );
  }
  if (!step.isRide) {
    throw StateError(
      '乗車系予定のrouteStepIdが乗車stepではありません: '
      'tripId=${trip.id}, entryId=${entry.id}, '
      'routeStepId=$stepId, stepKind=${step.kind}',
    );
  }

  final fixed = entry.itemKind == ScheduleEntryKind.ride
      ? trip.routeStepDepartureAt(stepId)
      : trip.routeStepArrivalAt(stepId);
  if (entry.plannedAt == fixed) return entry;

  debugPrint(
    '[ScheduleIntegrity] navigation uses fixed transit clock: '
    'entryId=${entry.id} stepId=$stepId kind=${entry.itemKind.name} '
    'stored=${entry.plannedAt.toIso8601String()} '
    'fixed=${fixed.toIso8601String()}',
  );
  return ScheduleEntry(
    id: entry.id,
    plannedAt: fixed,
    label: entry.label,
    description: entry.description,
    itemKind: entry.itemKind,
    legIndex: entry.legIndex,
    generatedBy: entry.generatedBy,
    routeStepId: entry.routeStepId,
    routeRole: entry.routeRole,
  );
}

List<ScheduleEntry> navigationScheduleForTrip(Trip trip) {
  Iterable<ScheduleEntry> canonicalize(Iterable<ScheduleEntry> entries) =>
      entries.map((entry) => navigationEntryWithFixedTransitClock(trip, entry));

  if (trip.isSolo) {
    if (trip.legs.length != 1) {
      throw StateError(
        'Solo navigationは1 legを前提とします: '
        'tripId=${trip.id}, legs=${trip.legs.length}',
      );
    }
    return canonicalize(trip.schedule).toList(growable: false);
  }

  resolveGroupActiveLeg(trip);
  final activeLegIndex = trip.activeLegIndex;
  final entries = canonicalize(
    trip.schedule.where((entry) => entry.legIndex == activeLegIndex),
  ).toList(growable: false);
  if (entries.isEmpty) {
    throw StateError(
      'Groupのactive legに予定がありません: '
      'tripId=${trip.id}, activeLegIndex=$activeLegIndex',
    );
  }
  return entries;
}

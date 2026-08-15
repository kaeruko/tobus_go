import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/rail_progress.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/services/train_location_source.dart';

void main() {
  const tripStops = <TrainTripStop>[
    TrainTripStop(sequence: 9, stopId: '115', stopName: '東日本橋'),
    TrainTripStop(sequence: 10, stopId: '116', stopName: '浅草橋'),
    TrainTripStop(sequence: 11, stopId: '117', stopName: '蔵前'),
  ];

  TrainLocation location({
    required int sequence,
    required String status,
    required String currentName,
  }) {
    final currentStop = tripStops.firstWhere(
      (stop) => stop.sequence == sequence,
    );
    return TrainLocation(
      tripId: '121603T0',
      routeId: '1',
      vehicleId: '121603T0',
      currentStopSequence: sequence,
      currentStatus: status,
      currentStopId: currentStop.stopId,
      currentStopName: currentName,
      boardingSequence: 9,
      destinationSequence: 11,
      vehicleAgeSeconds: 5,
      tripStops: tripStops,
    );
  }

  StepSeg railStep() => StepSeg(
    stepId: 'rail-1',
    kind: 'rail',
    title: '浅草線',
    fromName: '東日本橋',
    toName: '蔵前',
    arrivalTime: '16:24',
  );

  test('IN_TRANSIT_TO counts the approached station as still remaining', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 10,
        status: 'IN_TRANSIT_TO',
        currentName: '浅草橋',
      ),
    );

    expect(progress.phase, RailProgressPhase.riding);
    expect(progress.lastReachedSequence, 9);
    expect(progress.remainingStops, 2);
    expect(progress.currentStopName, '東日本橋');
    expect(progress.nextStopName, '浅草橋');
  });

  test('STOPPED_AT reduces remaining stations immediately', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 10,
        status: 'STOPPED_AT',
        currentName: '浅草橋',
      ),
    );

    expect(progress.phase, RailProgressPhase.riding);
    expect(progress.lastReachedSequence, 10);
    expect(progress.remainingStops, 1);
    expect(progress.currentStopName, '浅草橋');
    expect(progress.nextStopName, '蔵前');
  });

  test('destination STOPPED_AT marks the rail ride arrived', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 11,
        status: 'STOPPED_AT',
        currentName: '蔵前',
      ),
    );

    expect(progress.phase, RailProgressPhase.arrived);
    expect(progress.remainingStops, 0);
  });

  test('rail navigation uses the same route/place and arrival layout as bus', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 10,
        status: 'IN_TRANSIT_TO',
        currentName: '浅草橋',
      ),
    );

    final navigation = NavigationState.navigating(
      step: railStep(),
      busProgress: null,
      railProgress: progress,
    );

    expect(navigation.mainText, '浅草線 東日本橋');
    expect(navigation.subText, '16:24 浅草線 蔵前到着予定');
    expect(navigation.remainingStops, 2);
    expect(navigation.nextStopName, '浅草橋');
    expect(navigation.step?.kind, 'rail');
  });

  test('one station remaining keeps route and current station in the headline', () {
    final progress = RailProgress.forLocation(
      stepId: 'rail-1',
      location: location(
        sequence: 10,
        status: 'STOPPED_AT',
        currentName: '浅草橋',
      ),
    );

    final navigation = NavigationState.navigating(
      step: railStep(),
      busProgress: null,
      railProgress: progress,
    );

    expect(navigation.mainText, '浅草線 浅草橋');
    expect(navigation.subText, '16:24 浅草線 蔵前到着予定');
    expect(navigation.remainingStops, 1);
  });

  test('late rail ride remains authoritative after scheduled arrival', () {
    final step = railStep();
    final progress = RailProgress.forLocation(
      stepId: step.stepId,
      location: location(
        sequence: 10,
        status: 'STOPPED_AT',
        currentName: '浅草橋',
      ),
    );
    final ride = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 15, 16, 20),
      label: '浅草線に乗る',
      itemKind: ScheduleEntryKind.ride,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: step.stepId,
      legIndex: 1,
    );
    final arrival = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 15, 16, 24),
      label: '蔵前に着く',
      itemKind: ScheduleEntryKind.arrival,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: step.stepId,
      legIndex: 1,
    );
    final walk = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 15, 16, 24),
      label: '目的地まで歩く',
      itemKind: ScheduleEntryKind.walk,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'walk-2',
      legIndex: 2,
    );

    final resolved = TripCoordinator.resolveScheduleState(
      scheduleEntries: [ride, arrival, walk],
      routeState: RouteState(
        stepsById: {step.stepId: step},
        currentStepId: step.stepId,
        railProgress: progress,
      ),
      now: DateTime(2026, 8, 15, 16, 25),
    );

    expect(resolved.resolvedEntry?.id, ride.id);
    expect(
      resolved.resolutionReason,
      contains('realtime_incomplete_ride_revert_step_id'),
    );
  });

  test('rail realtime arrival advances to the arrival row', () {
    final step = railStep();
    final progress = RailProgress.forLocation(
      stepId: step.stepId,
      location: location(
        sequence: 11,
        status: 'STOPPED_AT',
        currentName: '蔵前',
      ),
    );
    final ride = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 15, 16, 20),
      label: '浅草線に乗る',
      itemKind: ScheduleEntryKind.ride,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: step.stepId,
      legIndex: 1,
    );
    final arrival = ScheduleEntry(
      plannedAt: DateTime(2026, 8, 15, 16, 24),
      label: '蔵前に着く',
      itemKind: ScheduleEntryKind.arrival,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: step.stepId,
      legIndex: 1,
    );

    final resolved = TripCoordinator.resolveScheduleState(
      scheduleEntries: [ride, arrival],
      routeState: RouteState(
        stepsById: {step.stepId: step},
        currentStepId: step.stepId,
        railProgress: progress,
      ),
      now: DateTime(2026, 8, 15, 16, 23),
    );

    expect(resolved.resolvedEntry?.id, arrival.id);
    expect(
      resolved.resolutionReason,
      contains('realtime_arrival_advance_step_id'),
    );
  });
}

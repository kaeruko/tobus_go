import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/providers/member_nav_progress_provider.dart';

void main() {
  StepSeg busStep(String stepId) => StepSeg(
        stepId: stepId,
        kind: 'bus',
        title: '上23 上野松坂屋前行',
        fromName: '東墨田一丁目',
        toName: '十間橋通り',
        routeId: '094',
        tripId: 'trip-1',
      );

  Candidate candidate(List<StepSeg> steps) => Candidate(
        id: 'candidate-1',
        lines: const ['上23'],
        rides: steps.where((step) => step.isRide).length,
        boards: 1,
        transfers: 0,
        total: 10,
        totalTime: 10,
        steps: steps,
        points: const [],
        destinationName: '目的地',
      );

  Trip tripWith(StepSeg step, ScheduleEntry entry) => Trip(
        id: 'trip-1',
        joinCode: '',
        leaderId: 'leader',
        title: 'test',
        travelPhase: TravelPhase.active,
        date: DateTime(2026, 8, 16),
        plannedDepartureAt: null,
        actualDepartureAt: null,
        legs: [
          Leg(
            direction: LegDirection.outbound,
            status: LegStatus.confirmed,
            candidate: candidate([step]),
          ),
        ],
        schedule: [entry],
        participants: const [],
        memberIds: const [],
      );

  ScheduleEntry rideEntry(String stepId) => ScheduleEntry(
        id: 'ride-entry',
        plannedAt: DateTime(2026, 8, 16, 11, 20),
        label: '上23に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: stepId,
        routeRole: 'ride',
      );

  BusProgress ridingProgress(String stepId, {String fromStopId = 'stop-a'}) =>
      BusProgress(
        stepId: stepId,
        fromStopId: fromStopId,
        fromStopIndex: 1,
        nextStopId: 'stop-b',
        nextStopIndex: 2,
        phase: BusProgressPhase.riding,
        observedStopId: 'stop-b',
        observedStopName: '東墨田二丁目',
        currentStatus: 'IN_TRANSIT_TO',
        vehicleAgeSeconds: 20,
      );

  test('confirmed onboard ride keeps last displayed progress during realtime gap', () {
    const stepId = 'bus-1';
    final step = busStep(stepId);
    final entry = rideEntry(stepId);
    final trip = tripWith(step, entry);
    final notifier = MemberNavProgressNotifier();
    final fresh = ridingProgress(stepId);

    notifier.updateFromSchedule(trip, entry, busProgress: fresh);
    expect(notifier.state.busProgress, same(fresh));
    expect(notifier.state.rideRealtimeUnavailable, isFalse);

    notifier.updateFromSchedule(
      trip,
      entry,
      rideRealtimeUnavailable: true,
    );

    expect(notifier.state.currentStepId, stepId);
    expect(notifier.state.busProgress, same(fresh));
    expect(notifier.state.railProgress, isNull);
    expect(notifier.state.rideRealtimeUnavailable, isTrue);
  });

  test('fresh realtime replaces retained progress and clears unavailable flag', () {
    const stepId = 'bus-1';
    final step = busStep(stepId);
    final entry = rideEntry(stepId);
    final trip = tripWith(step, entry);
    final notifier = MemberNavProgressNotifier();
    final oldProgress = ridingProgress(stepId);
    final freshProgress = ridingProgress(stepId, fromStopId: 'stop-b');

    notifier.updateFromSchedule(trip, entry, busProgress: oldProgress);
    notifier.updateFromSchedule(
      trip,
      entry,
      rideRealtimeUnavailable: true,
    );
    notifier.updateFromSchedule(trip, entry, busProgress: freshProgress);

    expect(notifier.state.busProgress, same(freshProgress));
    expect(notifier.state.rideRealtimeUnavailable, isFalse);
  });
}

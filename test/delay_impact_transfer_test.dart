import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/delay_impact_analyzer.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

void main() {
  final ride1 = StepSeg(
    stepId: 'rail-1',
    kind: 'rail',
    title: '浅草線 青砥行',
    fromName: '浅草橋',
    toName: '東日本橋',
    departureTime: '18:00',
    arrivalTime: '18:10',
    minutes: 10,
    stops: [
      StopPoint(
        name: '浅草橋',
        point: const LatLng(35.697, 139.785),
        stopId: 'asakusabashi',
      ),
      StopPoint(
        name: '東日本橋',
        point: const LatLng(35.692, 139.785),
        stopId: 'higashi-nihombashi',
      ),
    ],
  );
  final walk = StepSeg(
    stepId: 'walk-transfer',
    kind: 'walk',
    title: '徒歩',
    fromName: '東日本橋',
    toName: '馬喰横山',
    departureTime: '18:10',
    arrivalTime: '18:14',
    minutes: 4,
  );
  final ride2 = StepSeg(
    stepId: 'rail-2',
    kind: 'rail',
    title: '新宿線 本八幡行',
    fromName: '馬喰横山',
    toName: '目的地最寄り',
    departureTime: '18:16',
    arrivalTime: '18:25',
    minutes: 9,
    stops: [
      StopPoint(
        name: '馬喰横山',
        point: const LatLng(35.692, 139.782),
        stopId: 'bakuro-yokoyama',
      ),
      StopPoint(
        name: '目的地最寄り',
        point: const LatLng(35.691, 139.781),
        stopId: 'goal-nearest',
      ),
    ],
  );

  Trip trip() => Trip(
    tripType: TripType.group,
    id: 'group-delay',
    joinCode: '123456',
    leaderId: 'leader',
    title: 'test',
    travelPhase: TravelPhase.active,
    date: DateTime(2026, 8, 15),
    plannedDepartureAt: null,
    actualDepartureAt: null,
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: Candidate(
          id: 'candidate',
          lines: const ['浅草線', '新宿線'],
          rides: 2,
          boards: 2,
          transfers: 1,
          total: 25,
          totalTime: 25,
          steps: [ride1, walk, ride2],
          points: const [],
          originName: '出発地',
          destinationName: '目的地',
          originCoords: const LatLng(35.697, 139.785),
          destinationCoords: const LatLng(35.691, 139.781),
        ),
      ),
    ],
    schedule: [
      ScheduleEntry(
        id: 'ride-1',
        plannedAt: DateTime(2026, 8, 15, 18, 0),
        label: '浅草線に乗る',
        itemKind: ScheduleEntryKind.ride,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'rail-1',
        routeRole: 'ride',
      ),
      ScheduleEntry(
        id: 'arrival-1',
        plannedAt: DateTime(2026, 8, 15, 18, 10),
        label: '東日本橋に着く',
        itemKind: ScheduleEntryKind.arrival,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'rail-1',
        routeRole: 'arrival',
      ),
      ScheduleEntry(
        id: 'walk-transfer',
        plannedAt: DateTime(2026, 8, 15, 18, 10),
        label: '馬喰横山まで歩く',
        itemKind: ScheduleEntryKind.walk,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'walk-transfer',
        routeRole: 'walk',
      ),
      ScheduleEntry(
        id: 'ride-2',
        plannedAt: DateTime(2026, 8, 15, 18, 16),
        label: '新宿線に乗る',
        itemKind: ScheduleEntryKind.ride,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: 'rail-2',
        routeRole: 'ride',
      ),
    ],
    participants: const [],
    memberIds: const ['leader', 'member'],
  );

  final confirmed = ReplanTransitPlace(
    name: '東日本橋',
    stopId: 'higashi-nihombashi',
    point: const LatLng(35.692, 139.785),
  );

  test('transfer walk keeps warning from last confirmed transit place', () {
    final activeWalk = trip().schedule.firstWhere(
      (entry) => entry.id == 'walk-transfer',
    );

    final impact = DelayImpactAnalyzer.analyzeFromConfirmedTransferPlace(
      trip: trip(),
      activeEntry: activeWalk,
      confirmedPlace: confirmed,
      availableAt: DateTime(2026, 8, 15, 18, 13),
    );

    expect(impact, isNotNull);
    expect(impact!.basis, DelayImpactBasis.confirmedTransferPlace);
    expect(impact.transferWalkMinutes, 4);
    expect(impact.earliestTransferReadyAt, DateTime(2026, 8, 15, 18, 17));
    expect(impact.nextDepartureAt, DateTime(2026, 8, 15, 18, 16));
    expect(impact.missedBy, const Duration(minutes: 1));
    expect(impact.requiresReplan, isTrue);
  });

  test('approaching next ride can still be evaluated from previous confirmed stop', () {
    final nextRideEntry = trip().schedule.firstWhere(
      (entry) => entry.id == 'ride-2',
    );

    final impact = DelayImpactAnalyzer.analyzeFromConfirmedTransferPlace(
      trip: trip(),
      activeEntry: nextRideEntry,
      confirmedPlace: confirmed,
      availableAt: DateTime(2026, 8, 15, 18, 13),
    );

    expect(impact, isNotNull);
    expect(impact!.currentStepId, 'rail-1');
    expect(impact.nextRideStepId, 'rail-2');
    expect(impact.requiresReplan, isTrue);
  });

  test('confirmed place mismatch fails instead of guessing transfer progress', () {
    final activeWalk = trip().schedule.firstWhere(
      (entry) => entry.id == 'walk-transfer',
    );
    final wrongPlace = ReplanTransitPlace(
      name: '蔵前',
      point: const LatLng(35.703, 139.790),
    );

    expect(
      () => DelayImpactAnalyzer.analyzeFromConfirmedTransferPlace(
        trip: trip(),
        activeEntry: activeWalk,
        confirmedPlace: wrongPlace,
        availableAt: DateTime(2026, 8, 15, 18, 13),
      ),
      throwsStateError,
    );
  });
}

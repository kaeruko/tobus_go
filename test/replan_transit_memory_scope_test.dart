import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/logic/replan_transit_memory.dart';
import 'package:toeigo/logic/replan_transit_memory_scope.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

Trip _trip({
  int completedLegIndex = -1,
  TravelPhase phase = TravelPhase.active,
}) {
  Leg leg(String id, LegDirection direction, {bool includeWalk = false}) {
    return Leg(
      direction: direction,
      status: LegStatus.confirmed,
      candidate: Candidate(
        id: id,
        lines: const [],
        rides: 1,
        boards: 1,
        transfers: 0,
        total: 0,
        totalTime: 10,
        steps: [
          if (includeWalk)
            StepSeg(stepId: 'walk-outbound', kind: 'walk', title: 'Walk'),
          StepSeg(stepId: id, kind: 'bus', title: 'Bus'),
        ],
        points: const [],
      ),
    );
  }

  return Trip(
    id: 'trip-1',
    joinCode: '123456',
    leaderId: 'leader-1',
    title: 'Round trip',
    travelPhase: phase,
    date: DateTime(2026, 10, 5),
    plannedDepartureAt: null,
    actualDepartureAt: DateTime(2026, 10, 5, 15),
    legs: [
      leg('bus-outbound', LegDirection.outbound, includeWalk: true),
      leg('bus-inbound', LegDirection.inbound),
    ],
    schedule: const [],
    participants: const [],
    memberIds: const [],
    completedLegIndex: completedLegIndex,
  );
}

void main() {
  final place = ReplanTransitPlace(
    name: 'Last confirmed stop',
    stopId: 'last-stop',
    point: const LatLng(35.66, 139.70),
  );
  final confirmedAt = DateTime(2026, 10, 5, 17);

  ReplanTransitMemory memory(String stepId, {bool riding = false}) {
    return ReplanTransitMemory(
      knownOnboardStepId: stepId,
      ridingTransit: riding
          ? RidingTransitObservation(
              stepId: stepId,
              motion: RidingTransitMotion.stopped,
              currentPlace: place,
            )
          : null,
      lastConfirmedTransitPlace: place,
      lastConfirmedTransitAt: confirmedAt,
    );
  }

  void expectHistoricalOnly(ReplanTransitMemory result) {
    expect(result.knownOnboardStepId, isNull);
    expect(result.ridingTransit, isNull);
    expect(result.lastConfirmedTransitPlace, same(place));
    expect(result.lastConfirmedTransitAt, confirmedAt);
  }

  test('onboard marker stays authoritative within the active outbound leg', () {
    final original = memory('bus-outbound');
    final result = scopeReplanTransitMemoryToTrip(
      trip: _trip(),
      memory: original,
    );
    expect(result, same(original));
    expect(result.knownOnboardStepId, 'bus-outbound');
  });

  test(
    'fresh active inbound ride remains available after outbound completes',
    () {
      final original = memory('bus-inbound', riding: true);
      final result = scopeReplanTransitMemoryToTrip(
        trip: _trip(completedLegIndex: 0),
        memory: original,
      );
      expect(result, same(original));
      expect(result.ridingTransit, same(original.ridingTransit));
    },
  );

  test('outbound marker is excluded after manual outbound completion', () {
    expectHistoricalOnly(
      scopeReplanTransitMemoryToTrip(
        trip: _trip(completedLegIndex: 0),
        memory: memory('bus-outbound'),
      ),
    );
  });

  test('previous leg realtime and marker are both excluded', () {
    expectHistoricalOnly(
      scopeReplanTransitMemoryToTrip(
        trip: _trip(completedLegIndex: 0),
        memory: memory('bus-outbound', riding: true),
      ),
    );
  });

  test('future leg marker cannot override the active outbound leg', () {
    expectHistoricalOnly(
      scopeReplanTransitMemoryToTrip(
        trip: _trip(),
        memory: memory('bus-inbound'),
      ),
    );
  });

  for (final phase in [
    TravelPhase.planning,
    TravelPhase.completed,
    TravelPhase.cancelled,
  ]) {
    test('$phase excludes active rides while keeping confirmed history', () {
      expectHistoricalOnly(
        scopeReplanTransitMemoryToTrip(
          trip: _trip(phase: phase),
          memory: memory('bus-outbound', riding: true),
        ),
      );
    });
  }

  test('history without an active ride remains unchanged across legs', () {
    final original = ReplanTransitMemory(
      lastConfirmedTransitPlace: place,
      lastConfirmedTransitAt: confirmedAt,
    );
    expect(
      scopeReplanTransitMemoryToTrip(
        trip: _trip(completedLegIndex: 0),
        memory: original,
      ),
      same(original),
    );
  });

  test('an observation without a marker still follows leg ownership', () {
    final original = ReplanTransitMemory(
      ridingTransit: RidingTransitObservation(
        stepId: 'bus-outbound',
        motion: RidingTransitMotion.stopped,
        currentPlace: place,
      ),
      lastConfirmedTransitPlace: place,
      lastConfirmedTransitAt: confirmedAt,
    );
    expectHistoricalOnly(
      scopeReplanTransitMemoryToTrip(
        trip: _trip(completedLegIndex: 0),
        memory: original,
      ),
    );
  });

  for (final phase in [TravelPhase.active, TravelPhase.completed]) {
    test('$phase missing onboard step still fails fast', () {
      expect(
        () => scopeReplanTransitMemoryToTrip(
          trip: _trip(phase: phase),
          memory: memory('missing-step'),
        ),
        throwsStateError,
      );
    });

    test('$phase non-ride onboard step still fails fast', () {
      expect(
        () => scopeReplanTransitMemoryToTrip(
          trip: _trip(phase: phase),
          memory: memory('walk-outbound'),
        ),
        throwsStateError,
      );
    });
  }
}

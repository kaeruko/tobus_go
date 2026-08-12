import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/solo_trip_factory.dart';
import 'package:toeigo/logic/solo_trip_lifecycle.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/trip_models.dart';

import 'fixtures/navigation_v2_fixture.dart';

void main() {
  group('solo Trip factory', () {
    test(
      'builds the existing Trip model without group-only schedule entries',
      () {
        final trip = buildSoloTrip(
          id: 'solo-1',
          userId: 'user-1',
          userName: 'ゲスト',
          candidate: navigationV2Candidate(),
          now: DateTime(2025, 1, 1, 10),
        );

        expect(trip.tripType, TripType.solo);
        expect(trip.travelPhase, TravelPhase.active);
        expect(trip.legs, hasLength(1));
        expect(trip.joinCode, isEmpty);
        expect(trip.memberIds, ['user-1']);
        expect(trip.participants, hasLength(1));
        expect(
          trip.schedule.any(
            (entry) => entry.itemKind == ScheduleEntryKind.meeting,
          ),
          isFalse,
        );
        expect(trip.schedule.last.itemKind, ScheduleEntryKind.goal);
        expect(trip.toFirestore()['tripType'], 'solo');
        expect(trip.displayTitle, '自宅 → 目的地');
      },
    );

    test('existing Trip constructors remain group trips by default', () {
      expect(navigationV2Trip().tripType, TripType.group);
    });
  });

  group('solo automatic completion', () {
    test('completes at the final goal', () {
      final trip = buildSoloTrip(
        id: 'solo-1',
        userId: 'user-1',
        userName: 'ゲスト',
        candidate: navigationV2Candidate(),
        now: DateTime(2025, 1, 1, 10),
      );

      expect(
        shouldAutoCompleteSoloTrip(
          trip: trip,
          resolvedEntry: trip.schedule.last,
        ),
        isTrue,
      );
    });

    test('does not complete at an arrival followed by a walking segment', () {
      final trip = buildSoloTrip(
        id: 'solo-1',
        userId: 'user-1',
        userName: 'ゲスト',
        candidate: navigationV2Candidate(),
        now: DateTime(2025, 1, 1, 10),
      );
      final busArrival = trip.schedule.singleWhere(
        (entry) =>
            entry.itemKind == ScheduleEntryKind.arrival &&
            entry.routeStepId == 'bus-C',
      );

      expect(
        shouldAutoCompleteSoloTrip(trip: trip, resolvedEntry: busArrival),
        isFalse,
      );
    });

    test('completes on a final realtime arrival before the goal row', () {
      final baseTrip = buildSoloTrip(
        id: 'solo-1',
        userId: 'user-1',
        userName: 'ゲスト',
        candidate: navigationV2Candidate(),
        now: DateTime(2025, 1, 1, 10),
      );
      final finalArrival = baseTrip.schedule.singleWhere(
        (entry) =>
            entry.itemKind == ScheduleEntryKind.arrival &&
            entry.routeStepId == 'bus-C',
      );
      final goal = baseTrip.schedule.last;
      final finalRideTrip = Trip(
        tripType: TripType.solo,
        id: baseTrip.id,
        joinCode: '',
        leaderId: baseTrip.leaderId,
        title: baseTrip.title,
        travelPhase: TravelPhase.active,
        date: baseTrip.date,
        plannedDepartureAt: null,
        actualDepartureAt: baseTrip.actualDepartureAt,
        legs: baseTrip.legs,
        schedule: [finalArrival, goal],
        participants: baseTrip.participants,
        memberIds: baseTrip.memberIds,
      );

      expect(
        shouldAutoCompleteSoloTrip(
          trip: finalRideTrip,
          resolvedEntry: finalArrival,
        ),
        isTrue,
      );
    });

    test('never completes a group Trip automatically', () {
      final trip = navigationV2Trip();
      final goal = ScheduleEntry(
        plannedAt: DateTime(2025, 1, 1, 10),
        label: '到着',
        itemKind: ScheduleEntryKind.goal,
      );

      expect(
        shouldAutoCompleteSoloTrip(trip: trip, resolvedEntry: goal),
        isFalse,
      );
    });
  });
}

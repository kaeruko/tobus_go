import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/core/app_clock.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
// import 'package:toeigo/models/route_models.dart'; // Candidate not strictly needed if we mock or strictly test schedule

void main() {
  group('TripCoordinator', () {
    // Utility to create a dummy Trip
    Trip createDummyTrip({
      required List<ScheduleEntry> schedule,
    }) {
      return Trip(
        id: 't1',
        joinCode: '123456',
        leaderId: 'user1',
        title: 'Test Trip',
        travelPhase: TravelPhase.active,
        date: DateTime(2025, 12, 15),
        plannedDepartureAt: DateTime(2025, 12, 15, 10, 0),
        actualDepartureAt: null,
        legs: [], // Legs empty for schedule test
        schedule: schedule,
        participants: [],
        memberIds: ['user1'],
      );
    }

    test('computeScheduleProgress should shift active index if meeting is stale', () {
      // 12:48 Meeting, 12:58 Departure
      // Current: 13:07 (> Departure time)
      final meetingTime = DateTime(2025, 12, 15, 12, 48);
      final departureTime = DateTime(2025, 12, 15, 12, 58);
      final currentTime = DateTime(2025, 12, 15, 13, 07);

      final schedule = [
        ScheduleEntry(
          plannedAt: meetingTime,
          label: 'Meeting',
          itemKind: ScheduleEntryKind.meeting,
          isCompleted: false,
        ),
        ScheduleEntry(
          plannedAt: departureTime,
          label: 'Departure',
          itemKind: ScheduleEntryKind.departure,
          isCompleted: false,
        ),
      ];

      // Mock time to 13:07
      final now = DateTime.now();
      appClock.setOffset(currentTime.difference(now));

      final progress = TripCoordinator.computeScheduleProgress(
        scheduleSorted: schedule,
        now: appClock.now(),
      );

      // Should skip meeting (index 0) and point to Departure (index 1) or later?
      // Since Departure is NOT completed, activeIndex should be 1.
      expect(progress.activeIndex, 1);
      expect(progress.activeEntry?.label, 'Departure');
      expect(progress.completedCount, 1); // Meeting effectively computed as completed

      appClock.resetOffset();
    });

    test('computeScheduleProgress should stay on meeting if not stale', () {
       // 12:48 Meeting, 12:58 Departure
      // Current: 12:50 (< Departure time)
      final meetingTime = DateTime(2025, 12, 15, 12, 48);
      final departureTime = DateTime(2025, 12, 15, 12, 58);
      final currentTime = DateTime(2025, 12, 15, 12, 50);

      final schedule = [
        ScheduleEntry(
          plannedAt: meetingTime,
          label: 'Meeting',
          itemKind: ScheduleEntryKind.meeting,
          isCompleted: false,
        ),
        ScheduleEntry(
          plannedAt: departureTime,
          label: 'Departure',
          itemKind: ScheduleEntryKind.departure,
          isCompleted: false,
        ),
      ];

      // Mock time
      final now = DateTime.now();
      appClock.setOffset(currentTime.difference(now));

      final progress = TripCoordinator.computeScheduleProgress(
        scheduleSorted: schedule,
        now: appClock.now(),
      );

      // Should be Meeting (index 0)
      expect(progress.activeIndex, 0);
      expect(progress.activeEntry?.label, 'Meeting');
      expect(progress.completedCount, 0);

      appClock.resetOffset();
    });
  });
}

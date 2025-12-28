import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/core/app_clock.dart';
import 'package:toeigo/logic/schedule_resolver.dart';
import 'package:toeigo/models/group_models.dart';

void main() {
  group('ScheduleResolver', () {
    test('resolve should shift active index if meeting is stale', () {
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
        ),
        ScheduleEntry(
          plannedAt: departureTime,
          label: 'Departure',
          itemKind: ScheduleEntryKind.departure,
        ),
      ];

      // Mock time is NOT set globally for resolver unless resolver uses AppClock. 
      // The provided resolver code accepted `now` as argument. So use it directly.

      final result = ScheduleResolver.resolve(
        scheduleSorted: schedule,
        now: currentTime,
      );

      // Should skip meeting (index 0) and point to Departure (index 1) which is now effective start
      expect(result.activeIndex, 1);
      expect(result.activeEntry?.label, 'Departure');
      // Completed count logic: if activeIndex is 1, it means index 0 is completed (visually)
      expect(result.completedCount, 1); 
    });

    test('resolve should stay on meeting if not stale', () {
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
        ),
        ScheduleEntry(
          plannedAt: departureTime,
          label: 'Departure',
          itemKind: ScheduleEntryKind.departure,
        ),
      ];

      final result = ScheduleResolver.resolve(
        scheduleSorted: schedule,
        now: currentTime,
      );

      // Should be Meeting (index 0)
      expect(result.activeIndex, 0);
      expect(result.activeEntry?.label, 'Meeting');
      expect(result.completedCount, 0);
    });
  });
}

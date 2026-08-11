import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/logic/trip_coordinator.dart';
import 'package:toeigo/models/group_models.dart';

void main() {
  group('schedule time resolution', () {
    test('selects the latest entry that has started', () {
      final entries = [
        ScheduleEntry(
          plannedAt: DateTime(2025, 12, 15, 12, 48),
          label: 'Meeting',
          itemKind: ScheduleEntryKind.meeting,
        ),
        ScheduleEntry(
          plannedAt: DateTime(2025, 12, 15, 12, 58),
          label: 'Departure',
          itemKind: ScheduleEntryKind.departure,
        ),
      ];

      final result = TripCoordinator.resolveScheduleState(
        scheduleEntries: entries,
        now: DateTime(2025, 12, 15, 13, 7),
      );

      expect(result.resolvedEntry?.label, 'Departure');
      expect(result.completedCount, 1);
    });

    test('keeps meeting active before departure', () {
      final entries = [
        ScheduleEntry(
          plannedAt: DateTime(2025, 12, 15, 12, 48),
          label: 'Meeting',
          itemKind: ScheduleEntryKind.meeting,
        ),
        ScheduleEntry(
          plannedAt: DateTime(2025, 12, 15, 12, 58),
          label: 'Departure',
          itemKind: ScheduleEntryKind.departure,
        ),
      ];

      final result = TripCoordinator.resolveScheduleState(
        scheduleEntries: entries,
        now: DateTime(2025, 12, 15, 12, 50),
      );

      expect(result.resolvedEntry?.label, 'Meeting');
      expect(result.completedCount, 0);
    });
  });
}

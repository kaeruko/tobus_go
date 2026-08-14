import '../models/group_models.dart';
import '../models/trip_models.dart';

bool shouldOfferSoloTripCompletion({
  required Trip trip,
  required ScheduleEntry? resolvedEntry,
}) {
  if (!trip.isSolo ||
      trip.travelPhase != TravelPhase.active ||
      resolvedEntry == null) {
    return false;
  }
  if (resolvedEntry.itemKind == ScheduleEntryKind.goal) return true;
  if (resolvedEntry.itemKind != ScheduleEntryKind.arrival) return false;

  final schedule = [...trip.schedule];
  sortScheduleEntries(schedule);
  final currentIndex = schedule.indexWhere(
    (entry) => entry.id == resolvedEntry.id,
  );
  if (currentIndex == -1) return false;

  return schedule
      .skip(currentIndex + 1)
      .every((entry) => entry.itemKind == ScheduleEntryKind.goal);
}

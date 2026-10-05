import '../providers/member_mode_provider.dart';
import 'replan_transit_memory.dart';

extension ReplanTransitMemoryRestore on MemberModeController {
  /// Restores historical places, an active ride, or an already finished ride.
  /// Realtime positions and forecasts are deliberately not persisted.
  void restoreReplanTransitMemory(ReplanTransitMemory restored) {
    restoreHistoricalTransitMemory(restored);
  }
}

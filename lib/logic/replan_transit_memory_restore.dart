import '../providers/member_mode_provider.dart';
import 'replan_transit_memory.dart';

extension ReplanTransitMemoryRestore on MemberModeController {
  /// Restores only historical route-derived facts after a cold start.
  ///
  /// Fresh realtime state always wins. The restored onboard marker deliberately
  /// carries no vehicle ETA/progress, so the existing controller will keep the
  /// exact ride step authoritative and poll it again before replanning resumes.
  void restoreReplanTransitMemory(ReplanTransitMemory restored) {
    final current = state.replanTransitMemory;
    final hasFreshFacts = current.ridingTransit != null ||
        current.lastConfirmedTransitPlace != null ||
        current.knownOnboardStepId != null;
    if (hasFreshFacts) return;

    final hasRestoredFacts = restored.lastConfirmedTransitPlace != null ||
        restored.knownOnboardStepId != null;
    if (!hasRestoredFacts) return;

    state = RealtimeTransitState(
      trackedStepId: restored.knownOnboardStepId,
      replanTransitMemory: restored,
    );
  }
}

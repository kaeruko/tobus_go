import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/replan_transit_memory.dart';
import '../logic/replan_transit_memory_restore.dart';
import '../logic/replan_transit_memory_scope.dart';
import '../services/replan_transit_memory_store.dart';
import '../services/user_service.dart';
import 'member_mode_provider.dart';
import 'trip_provider.dart';

final replanTransitMemoryStoreProvider = Provider<ReplanTransitMemoryStore>((
  ref,
) {
  return ReplanTransitMemoryStore();
});

final restoredReplanTransitMemoryProvider =
    FutureProvider.autoDispose<PersistedReplanTransitMemory?>((ref) async {
      var disposed = false;
      ref.onDispose(() => disposed = true);
      final tripAsync = ref.watch(tripStreamProvider);
      if (!tripAsync.hasValue) return null;
      final trip = tripAsync.value;
      if (trip == null) return null;

      final userId = UserService().currentUserId;
      if (userId == null || userId.trim().isEmpty) {
        throw StateError('再探索履歴を復元するユーザーIDを取得できません');
      }

      final restored = await ref
          .read(replanTransitMemoryStoreProvider)
          .load(tripId: trip.id, userId: userId);
      if (disposed || restored == null) return null;

      // Reading a dirty dependency can dispose this generation synchronously.
      // Never apply an older load to the controller for a later Trip or leg.
      final currentTrip = ref.read(tripStreamProvider).valueOrNull;
      if (disposed || !identical(currentTrip, trip)) return null;

      final memory = scopeReplanTransitMemoryToTrip(
        trip: trip,
        memory: restored.toMemory(),
      );
      _validateRestoredMemory(trip, memory);
      final controller = ref.read(memberModeControllerProvider.notifier);
      if (disposed || !controller.mounted) return null;
      controller.restoreReplanTransitMemory(memory);
      return restored;
    }, dependencies: [tripStreamProvider, memberModeControllerProvider]);

/// Writes only fresh route-derived historical facts. An empty in-memory state
/// during cold start does not delete disk history before restoration completes.
final persistCurrentReplanTransitMemoryProvider =
    FutureProvider.autoDispose<void>((ref) async {
      final tripAsync = ref.watch(tripStreamProvider);
      final realtime = ref.watch(memberModeControllerProvider);
      if (!tripAsync.hasValue) return;
      final trip = tripAsync.value;
      if (trip == null) return;

      if (!_hasPersistableFacts(realtime.replanTransitMemory)) return;
      final memory = scopeReplanTransitMemoryToTrip(
        trip: trip,
        memory: realtime.replanTransitMemory,
      );
      _validateRestoredMemory(trip, memory);

      final userId = UserService().currentUserId;
      if (userId == null || userId.trim().isEmpty) {
        throw StateError('再探索履歴を保存するユーザーIDを取得できません');
      }
      await ref
          .read(replanTransitMemoryStoreProvider)
          .save(tripId: trip.id, userId: userId, memory: memory);
    }, dependencies: [tripStreamProvider, memberModeControllerProvider]);

class EffectiveReplanTransitMemory {
  final ReplanTransitMemory? memory;
  final bool restoring;
  final Object? restoreError;
  final Object? persistenceError;
  final bool restoredFromDisk;

  const EffectiveReplanTransitMemory({
    required this.memory,
    this.restoring = false,
    this.restoreError,
    this.persistenceError,
    this.restoredFromDisk = false,
  });
}

/// Combines fresh in-memory realtime facts with restart-safe historical facts.
///
/// Fresh realtime always wins. Persisted data never restores a stale ETA or
/// predicted next station: only the last confirmed transit place and an onboard
/// marker survive a restart.
final effectiveReplanTransitMemoryProvider =
    Provider.autoDispose<EffectiveReplanTransitMemory>(
      (ref) {
        final tripAsync = ref.watch(tripStreamProvider);
        final realtime = ref.watch(memberModeControllerProvider);
        final restoredAsync = ref.watch(restoredReplanTransitMemoryProvider);
        final persistAsync = ref.watch(
          persistCurrentReplanTransitMemoryProvider,
        );
        final trip = tripAsync.valueOrNull;
        final live = trip == null
            ? realtime.replanTransitMemory
            : scopeReplanTransitMemoryToTrip(
                trip: trip,
                memory: realtime.replanTransitMemory,
              );

        final persistenceError = persistAsync.hasError
            ? persistAsync.error
            : null;
        if (_hasPersistableFacts(live)) {
          if (trip != null) {
            _validateRestoredMemory(trip, live);
          }
          return EffectiveReplanTransitMemory(
            memory: live,
            persistenceError: persistenceError,
          );
        }

        return restoredAsync.when(
          loading: () => EffectiveReplanTransitMemory(
            memory: null,
            restoring: true,
            persistenceError: persistenceError,
          ),
          error: (error, stack) => EffectiveReplanTransitMemory(
            memory: null,
            restoreError: error,
            persistenceError: persistenceError,
          ),
          data: (restored) {
            if (restored == null) {
              return EffectiveReplanTransitMemory(
                memory: live,
                persistenceError: persistenceError,
              );
            }
            if (trip == null) {
              return EffectiveReplanTransitMemory(
                memory: null,
                restoring: true,
                persistenceError: persistenceError,
              );
            }
            final memory = scopeReplanTransitMemoryToTrip(
              trip: trip,
              memory: restored.toMemory(),
            );
            _validateRestoredMemory(trip, memory);
            return EffectiveReplanTransitMemory(
              memory: memory,
              persistenceError: persistenceError,
              restoredFromDisk: true,
            );
          },
        );
      },
      dependencies: [
        tripStreamProvider,
        memberModeControllerProvider,
        restoredReplanTransitMemoryProvider,
        persistCurrentReplanTransitMemoryProvider,
      ],
    );

bool _hasPersistableFacts(ReplanTransitMemory memory) {
  return memory.lastConfirmedTransitPlace != null ||
      memory.knownOnboardStepId != null ||
      memory.completedRideStepId != null;
}

void _validateRestoredMemory(Trip trip, ReplanTransitMemory memory) {
  final onboardStepId = memory.knownOnboardStepId;
  if (onboardStepId != null) {
    final step = trip.stepsById[onboardStepId];
    if (step == null) {
      throw StateError('保存済み乗車stepが現在のTripにありません: $onboardStepId');
    }
    if (!step.isRide) {
      throw StateError(
        '保存済み乗車stepが乗車stepではありません: '
        'stepId=$onboardStepId, kind=${step.kind}',
      );
    }
  }

  final place = memory.lastConfirmedTransitPlace;
  if (place == null) return;

  final stopId = place.stopId?.trim();
  if (stopId == null || stopId.isEmpty) {
    throw StateError('保存済み最終確定地点にstopIdがありません: ${place.name}');
  }

  var matches = 0;
  for (final step in trip.stepsById.values) {
    if (!step.isRide) continue;
    for (final stop in step.stops) {
      if (stop.stopId?.trim() == stopId) {
        matches += 1;
      }
    }
  }
  if (matches == 0) {
    throw StateError(
      '保存済み最終確定地点IDが現在のTripの駅・停留所にありません: '
      'stopId=$stopId',
    );
  }
}

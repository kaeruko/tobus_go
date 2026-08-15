import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/replan_transit_memory.dart';
import '../logic/replan_transit_memory_restore.dart';
import '../models/trip_models.dart';
import '../services/replan_transit_memory_store.dart';
import '../services/user_service.dart';
import 'member_mode_provider.dart';
import 'trip_provider.dart';

final replanTransitMemoryStoreProvider = Provider<ReplanTransitMemoryStore>((ref) {
  return ReplanTransitMemoryStore();
});

final restoredReplanTransitMemoryProvider =
    FutureProvider.autoDispose<PersistedReplanTransitMemory?>((ref) async {
      final tripAsync = ref.watch(tripStreamProvider);
      if (!tripAsync.hasValue) return null;
      final trip = tripAsync.value;
      if (trip == null) return null;

      final userId = UserService().currentUserId;
      if (userId == null || userId.trim().isEmpty) {
        throw StateError('再探索履歴を復元するユーザーIDを取得できません');
      }

      final restored = await ref.read(replanTransitMemoryStoreProvider).load(
        tripId: trip.id,
        userId: userId,
      );
      if (restored == null) return null;

      final memory = restored.toMemory();
      _validateRestoredMemory(trip, memory);
      ref
          .read(memberModeControllerProvider.notifier)
          .restoreReplanTransitMemory(memory);
      return restored;
    }, dependencies: [
      tripStreamProvider,
      memberModeControllerProvider,
    ]);

class EffectiveReplanTransitMemory {
  final ReplanTransitMemory? memory;
  final bool restoring;
  final Object? restoreError;
  final bool restoredFromDisk;

  const EffectiveReplanTransitMemory({
    required this.memory,
    this.restoring = false,
    this.restoreError,
    this.restoredFromDisk = false,
  });
}

/// Combines fresh in-memory realtime facts with restart-safe historical facts.
///
/// Fresh realtime always wins. Persisted data never restores a stale ETA or
/// predicted next station: only the last confirmed transit place and an onboard
/// marker survive a restart.
final effectiveReplanTransitMemoryProvider =
    Provider.autoDispose<EffectiveReplanTransitMemory>((ref) {
      final tripAsync = ref.watch(tripStreamProvider);
      final realtime = ref.watch(memberModeControllerProvider);
      final restoredAsync = ref.watch(restoredReplanTransitMemoryProvider);
      final live = realtime.replanTransitMemory;

      final trip = tripAsync.value;
      final userId = UserService().currentUserId;
      if (trip != null &&
          userId != null &&
          userId.trim().isNotEmpty &&
          _hasPersistableFacts(live)) {
        _validateRestoredMemory(trip, live);
        unawaited(
          ref.read(replanTransitMemoryStoreProvider).save(
                tripId: trip.id,
                userId: userId,
                memory: live,
              ),
        );
        return EffectiveReplanTransitMemory(memory: live);
      }

      return restoredAsync.when(
        loading: () => const EffectiveReplanTransitMemory(
          memory: null,
          restoring: true,
        ),
        error: (error, stack) => EffectiveReplanTransitMemory(
          memory: null,
          restoreError: error,
        ),
        data: (restored) {
          if (restored == null) {
            return EffectiveReplanTransitMemory(memory: live);
          }
          final memory = restored.toMemory();
          if (trip == null) {
            return const EffectiveReplanTransitMemory(
              memory: null,
              restoring: true,
            );
          }
          _validateRestoredMemory(trip, memory);
          return EffectiveReplanTransitMemory(
            memory: memory,
            restoredFromDisk: true,
          );
        },
      );
    }, dependencies: [
      tripStreamProvider,
      memberModeControllerProvider,
      restoredReplanTransitMemoryProvider,
    ]);

bool _hasPersistableFacts(ReplanTransitMemory memory) {
  return memory.lastConfirmedTransitPlace != null ||
      memory.knownOnboardStepId != null;
}

void _validateRestoredMemory(Trip trip, ReplanTransitMemory memory) {
  final onboardStepId = memory.knownOnboardStepId;
  if (onboardStepId != null) {
    final step = trip.stepsById[onboardStepId];
    if (step == null) {
      throw StateError(
        '保存済み乗車stepが現在のTripにありません: $onboardStepId',
      );
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

  var matches = 0;
  for (final step in trip.stepsById.values) {
    if (!step.isRide) continue;
    for (final stop in step.stops) {
      final stopIdMatches = place.stopId == null || stop.stopId == place.stopId;
      if (stopIdMatches &&
          stop.name == place.name &&
          stop.point.latitude == place.point.latitude &&
          stop.point.longitude == place.point.longitude) {
        matches += 1;
      }
    }
  }
  if (matches == 0) {
    throw StateError(
      '保存済み最終確定地点が現在のTripの駅・停留所にありません: ${place.name}',
    );
  }
}

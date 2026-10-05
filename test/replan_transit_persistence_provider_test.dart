import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:toeigo/logic/replan_transit_memory.dart';
import 'package:toeigo/logic/replan_transit_memory_restore.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/providers/member_mode_provider.dart';
import 'package:toeigo/providers/member_nav_progress_provider.dart';
import 'package:toeigo/providers/replan_transit_persistence_provider.dart';
import 'package:toeigo/providers/trip_provider.dart';
import 'package:toeigo/services/bus_location_source.dart';
import 'package:toeigo/services/replan_transit_memory_store.dart';
import 'package:toeigo/services/train_location_source.dart';
import 'package:toeigo/services/user_service.dart';

Trip _trip({
  String id = 'trip-1',
  int completedLegIndex = -1,
  TravelPhase phase = TravelPhase.active,
}) {
  Leg leg(String stepId, LegDirection direction) => Leg(
    direction: direction,
    status: LegStatus.confirmed,
    candidate: Candidate(
      id: stepId,
      lines: const [],
      rides: 1,
      boards: 1,
      transfers: 0,
      total: 0,
      totalTime: 10,
      steps: [StepSeg(stepId: stepId, kind: 'bus', title: 'Bus')],
      points: const [],
    ),
  );
  return Trip(
    id: id,
    joinCode: '123456',
    leaderId: 'user-1',
    title: 'Round trip',
    travelPhase: phase,
    date: DateTime(2026, 10, 5),
    plannedDepartureAt: null,
    actualDepartureAt: DateTime(2026, 10, 5, 15),
    legs: [
      leg('bus-outbound', LegDirection.outbound),
      leg('bus-inbound', LegDirection.inbound),
    ],
    schedule: const [],
    participants: const [],
    memberIds: const ['user-1'],
    completedLegIndex: completedLegIndex,
  );
}

PersistedReplanTransitMemory _saved({
  String tripId = 'trip-1',
  String? completedRideStepId,
}) => PersistedReplanTransitMemory(
  tripId: tripId,
  userId: 'user-1',
  knownOnboardStepId: completedRideStepId == null ? 'bus-outbound' : null,
  completedRideStepId: completedRideStepId,
);

class _PendingLoad {
  final String tripId;
  final Completer<PersistedReplanTransitMemory?> completer = Completer();

  _PendingLoad(this.tripId);
}

class _MemoryStore extends ReplanTransitMemoryStore {
  final loads = <_PendingLoad>[];
  final saves = <ReplanTransitMemory>[];

  @override
  Future<PersistedReplanTransitMemory?> load({
    required String tripId,
    required String userId,
  }) {
    final pending = _PendingLoad(tripId);
    loads.add(pending);
    return pending.completer.future;
  }

  @override
  Future<void> save({
    required String tripId,
    required String userId,
    required ReplanTransitMemory memory,
  }) async {
    saves.add(memory);
  }
}

class _Harness {
  final trips = StreamController<Trip?>();
  final store = _MemoryStore();
  late final ProviderContainer container;

  _Harness({bool effective = false}) {
    container = ProviderContainer(
      overrides: [
        tripStreamProvider.overrideWith((ref) => trips.stream),
        replanTransitMemoryStoreProvider.overrideWithValue(store),
        memberModeControllerProvider.overrideWith((ref) {
          ref.watch(memberNavProgressProvider.notifier);
          // Restoration tests do not start realtime polling.
          return MemberModeController(
            ref,
            const RealtimeBusLocationSource(),
            const RealtimeTrainLocationSource(),
          );
        }),
      ],
    );
    container.listen(memberModeControllerProvider, (_, _) {});
    container.listen(restoredReplanTransitMemoryProvider, (_, _) {});
    if (effective) {
      container.listen(effectiveReplanTransitMemoryProvider, (_, _) {});
    }
  }

  Future<void> flush() async {
    for (var i = 0; i < 3; i++) {
      await Future<void>.delayed(Duration.zero);
      await container.pump();
    }
  }

  Future<void> dispose() async {
    container.dispose();
    await trips.close();
  }
}

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'user_uid': 'user-1',
      'user_provisioned_v1': true,
    });
    await UserService().initialize();
  });

  test('same active leg restores its onboard marker', () async {
    final harness = _Harness();
    addTearDown(harness.dispose);
    harness.trips.add(_trip());
    await harness.flush();
    expect(harness.store.loads, hasLength(1));

    harness.store.loads.single.completer.complete(_saved());
    await harness.flush();
    expect(
      harness.container
          .read(memberModeControllerProvider)
          .replanTransitMemory
          .knownOnboardStepId,
      'bus-outbound',
    );
  });

  test('leg advance during load cannot commit to the new controller', () async {
    final harness = _Harness();
    addTearDown(harness.dispose);
    harness.trips.add(_trip());
    await harness.flush();
    final oldController = harness.container.read(
      memberModeControllerProvider.notifier,
    );

    harness.trips.add(_trip(completedLegIndex: 0));
    await harness.flush();
    expect(harness.store.loads, hasLength(2));
    final currentController = harness.container.read(
      memberModeControllerProvider.notifier,
    );
    expect(currentController, isNot(same(oldController)));

    harness.store.loads.first.completer.complete(_saved());
    await harness.flush();
    expect(
      harness.container
          .read(memberModeControllerProvider)
          .replanTransitMemory
          .knownOnboardStepId,
      isNull,
    );

    harness.store.loads.last.completer.complete(_saved());
    await harness.flush();
    expect(
      harness.container
          .read(memberModeControllerProvider)
          .replanTransitMemory
          .knownOnboardStepId,
      isNull,
    );
  });

  test('Trip change during load cannot restore another Trip history', () async {
    final harness = _Harness();
    addTearDown(harness.dispose);
    harness.trips.add(_trip());
    await harness.flush();
    harness.trips.add(_trip(id: 'trip-2'));
    await harness.flush();
    expect(harness.store.loads, hasLength(2));

    harness.store.loads.first.completer.complete(_saved());
    await harness.flush();
    expect(
      harness.container
          .read(memberModeControllerProvider)
          .replanTransitMemory
          .knownOnboardStepId,
      isNull,
    );

    harness.store.loads.last.completer.complete(null);
    await harness.flush();
  });

  test(
    'disposing a pending restoration prevents later controller access',
    () async {
      final harness = _Harness();
      harness.trips.add(_trip());
      await harness.flush();
      final controller = harness.container.read(
        memberModeControllerProvider.notifier,
      );
      final load = harness.store.loads.single;
      await harness.dispose();
      expect(controller.mounted, isFalse);

      load.completer.complete(_saved());
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
    },
  );

  test('completion during load excludes the old active ride', () async {
    final harness = _Harness();
    addTearDown(harness.dispose);
    harness.trips.add(_trip());
    await harness.flush();
    harness.trips.add(_trip(phase: TravelPhase.completed));
    await harness.flush();
    expect(harness.store.loads, hasLength(2));

    harness.store.loads.first.completer.complete(_saved());
    harness.store.loads.last.completer.complete(_saved());
    await harness.flush();
    expect(
      harness.container
          .read(memberModeControllerProvider)
          .replanTransitMemory
          .knownOnboardStepId,
      isNull,
    );
  });

  test('effective disk fallback also excludes an older leg marker', () async {
    final harness = _Harness(effective: true);
    addTearDown(harness.dispose);
    harness.trips.add(_trip(completedLegIndex: 0));
    await harness.flush();
    harness.store.loads.single.completer.complete(_saved());
    await harness.flush();

    final effective = harness.container.read(
      effectiveReplanTransitMemoryProvider,
    );
    expect(effective.restoredFromDisk, isTrue);
    expect(effective.restoreError, isNull);
    expect(effective.memory?.knownOnboardStepId, isNull);
    expect(effective.memory?.ridingTransit, isNull);
  });

  test(
    'early completion restores and persists on restart in the same leg',
    () async {
      final harness = _Harness(effective: true);
      addTearDown(harness.dispose);
      harness.trips.add(_trip());
      await harness.flush();
      harness.store.loads.single.completer.complete(
        _saved(completedRideStepId: 'bus-outbound'),
      );
      await harness.flush();

      final realtime = harness.container.read(memberModeControllerProvider);
      expect(realtime.trackedStepId, 'bus-outbound');
      expect(realtime.replanTransitMemory.completedRideStepId, 'bus-outbound');
      expect(realtime.replanTransitMemory.knownOnboardStepId, isNull);
      expect(realtime.busProgress, isNull);
      expect(
        harness.container
            .read(effectiveReplanTransitMemoryProvider)
            .memory
            ?.completedRideStepId,
        'bus-outbound',
      );
      expect(
        harness.store.saves.any(
          (memory) => memory.completedRideStepId == 'bus-outbound',
        ),
        isTrue,
      );
    },
  );

  test(
    'fresh completion cannot be replaced by older persisted onboard state',
    () async {
      final harness = _Harness();
      addTearDown(harness.dispose);
      harness.trips.add(_trip());
      await harness.flush();
      harness.container
          .read(memberModeControllerProvider.notifier)
          .restoreReplanTransitMemory(
            const ReplanTransitMemory(completedRideStepId: 'bus-outbound'),
          );
      harness.store.loads.single.completer.complete(_saved());
      await harness.flush();

      final memory = harness.container
          .read(memberModeControllerProvider)
          .replanTransitMemory;
      expect(memory.completedRideStepId, 'bus-outbound');
      expect(memory.knownOnboardStepId, isNull);
    },
  );

  test(
    'effective disk fallback excludes completion from the previous leg',
    () async {
      final harness = _Harness(effective: true);
      addTearDown(harness.dispose);
      harness.trips.add(_trip(completedLegIndex: 0));
      await harness.flush();
      harness.store.loads.single.completer.complete(
        _saved(completedRideStepId: 'bus-outbound'),
      );
      await harness.flush();

      final effective = harness.container.read(
        effectiveReplanTransitMemoryProvider,
      );
      expect(effective.restoreError, isNull);
      expect(effective.memory?.completedRideStepId, isNull);
      expect(
        harness.container
            .read(memberModeControllerProvider)
            .replanTransitMemory
            .completedRideStepId,
        isNull,
      );
    },
  );
}

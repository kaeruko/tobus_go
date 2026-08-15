import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/logic/replan_transit_memory.dart';
import 'package:toeigo/services/replan_transit_memory_store.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  test('confirmed place and onboard marker survive restart without stale realtime', () async {
    final store = ReplanTransitMemoryStore();
    final current = ReplanTransitPlace(
      name: '浅草橋',
      stopId: 'stop-asakusabashi',
      point: const LatLng(35.697, 139.785),
    );
    final next = ReplanTransitPlace(
      name: '蔵前',
      stopId: 'stop-kuramae',
      point: const LatLng(35.703, 139.790),
    );
    final observation = RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.inTransit,
      currentPlace: current,
      nextPlace: next,
      predictedNextAvailableAt: DateTime(2026, 8, 15, 18, 6),
      predictedDestinationAvailableAt: DateTime(2026, 8, 15, 18, 12),
    );
    final memory = const ReplanTransitMemory().observeRide(observation);

    await store.save(
      tripId: 'trip-1',
      userId: 'user-1',
      memory: memory,
    );
    final restored = await store.load(
      tripId: 'trip-1',
      userId: 'user-1',
    );

    expect(restored, isNotNull);
    final restoredMemory = restored!.toMemory();
    expect(restoredMemory.ridingTransit, isNull);
    expect(restoredMemory.knownOnboardStepId, 'rail-1');
    expect(restoredMemory.lastConfirmedTransitPlace?.name, '浅草橋');
    expect(
      restoredMemory.lastConfirmedTransitPlace?.point,
      const LatLng(35.697, 139.785),
    );
  });

  test('memory is isolated by trip and user', () async {
    final store = ReplanTransitMemoryStore();
    final memory = ReplanTransitMemory(
      lastConfirmedTransitPlace: ReplanTransitPlace(
        name: '東日本橋',
        point: const LatLng(35.692, 139.785),
      ),
    );

    await store.save(
      tripId: 'trip-1',
      userId: 'user-1',
      memory: memory,
    );

    expect(
      await store.load(tripId: 'trip-2', userId: 'user-1'),
      isNull,
    );
    expect(
      await store.load(tripId: 'trip-1', userId: 'user-2'),
      isNull,
    );
  });

  test('empty memory removes persisted history', () async {
    final store = ReplanTransitMemoryStore();
    final memory = ReplanTransitMemory(
      lastConfirmedTransitPlace: ReplanTransitPlace(
        name: '東日本橋',
        point: const LatLng(35.692, 139.785),
      ),
    );

    await store.save(
      tripId: 'trip-1',
      userId: 'user-1',
      memory: memory,
    );
    await store.save(
      tripId: 'trip-1',
      userId: 'user-1',
      memory: const ReplanTransitMemory(),
    );

    expect(
      await store.load(tripId: 'trip-1', userId: 'user-1'),
      isNull,
    );
  });

  test('malformed persisted coordinates fail fast', () async {
    SharedPreferences.setMockInitialValues(<String, Object>{
      'replan_transit_memory_v1::user-1::trip-1':
          '{"schemaVersion":1,"tripId":"trip-1","userId":"user-1",'
          '"knownOnboardStepId":null,'
          '"lastConfirmedTransitPlace":{"name":"浅草橋",'
          '"stopId":null,"latitude":"bad","longitude":139.785}}',
    });
    final store = ReplanTransitMemoryStore();

    expect(
      () => store.load(tripId: 'trip-1', userId: 'user-1'),
      throwsStateError,
    );
  });
}

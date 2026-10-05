import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/core/app_clock.dart';
import 'package:toeigo/logic/replan_transit_memory.dart';
import 'package:toeigo/logic/replan_transit_memory_restore.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/providers/member_mode_provider.dart';
import 'package:toeigo/providers/member_nav_progress_provider.dart';
import 'package:toeigo/providers/minute_ticker_provider.dart';
import 'package:toeigo/providers/trip_provider.dart';
import 'package:toeigo/services/bus_location_source.dart';

const _busStepId = 'bus-policy-step';
const _walkStepId = 'walk-policy-step';

class _Request {
  final String routeId;
  final String tripId;
  final String? vehicleId;

  const _Request(this.routeId, this.tripId, this.vehicleId);
}

class _BusSource implements BusLocationSource {
  final Future<BusLocation> Function(_Request) responder;
  final requests = <_Request>[];

  _BusSource(this.responder);

  @override
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? boardingStopId,
    DateTime? scheduledDepartureAt,
    String? vehicleId,
    bool forceRefresh = false,
  }) {
    final request = _Request(routeId, tripId, vehicleId);
    requests.add(request);
    return responder(request);
  }
}

Future<BusLocation> _notFound(_Request _) async {
  throw const BusLocationNotAvailableException(code: 'bus_trip_not_found');
}

String _clock(DateTime time) =>
    '${time.hour.toString().padLeft(2, '0')}:'
    '${time.minute.toString().padLeft(2, '0')}';

Trip _trip(DateTime now, {required DateTime arrivalAt}) {
  final departureAt = arrivalAt.subtract(const Duration(minutes: 10));
  final goalAt = arrivalAt.add(const Duration(minutes: 2));
  final bus = StepSeg(
    stepId: _busStepId,
    kind: 'bus',
    title: 'テスト路線',
    fromName: '出発停留所',
    toName: '降車停留所',
    routeId: 'route-policy',
    tripId: 'service-policy',
    departureStopId: 'stop-a',
    arrivalPoleId: 'stop-c',
    departureTime: _clock(departureAt),
    arrivalTime: _clock(arrivalAt),
    minutes: 10,
    stops: [
      StopPoint(
        name: '出発停留所',
        stopId: 'stop-a',
        point: const LatLng(35.1, 139.1),
        isOrigin: true,
      ),
      StopPoint(
        name: '中間停留所',
        stopId: 'stop-b',
        point: const LatLng(35.2, 139.2),
      ),
      StopPoint(
        name: '降車停留所',
        stopId: 'stop-c',
        point: const LatLng(35.3, 139.3),
        isDestination: true,
      ),
    ],
  );
  final walk = StepSeg(
    stepId: _walkStepId,
    kind: 'walk',
    title: '徒歩',
    fromName: '降車停留所',
    toName: '目的地',
    departureTime: _clock(arrivalAt),
    arrivalTime: _clock(goalAt),
    minutes: 2,
    meters: 120,
  );
  final candidate = Candidate(
    id: 'candidate-policy',
    lines: const ['テスト路線'],
    rides: 1,
    boards: 1,
    transfers: 0,
    total: 12,
    totalTime: 12,
    departureDate: departureAt,
    originName: '出発停留所',
    destinationName: '目的地',
    steps: [bus, walk],
    points: const [],
  );
  return Trip(
    id: 'trip-policy',
    joinCode: '123456',
    leaderId: 'user-policy',
    title: '時刻表の進行テスト',
    travelPhase: TravelPhase.active,
    date: now,
    plannedDepartureAt: departureAt,
    actualDepartureAt: departureAt,
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: candidate,
      ),
    ],
    schedule: [
      ScheduleEntry(
        id: 'ride-policy',
        plannedAt: departureAt,
        label: 'テスト路線に乗る',
        itemKind: ScheduleEntryKind.ride,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: _busStepId,
        routeRole: 'ride',
      ),
      ScheduleEntry(
        id: 'arrival-policy',
        plannedAt: arrivalAt,
        label: '降車停留所に着く',
        itemKind: ScheduleEntryKind.arrival,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: _busStepId,
        routeRole: 'arrival',
      ),
      ScheduleEntry(
        id: 'walk-policy',
        plannedAt: arrivalAt,
        label: '目的地まで歩く',
        itemKind: ScheduleEntryKind.walk,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: _walkStepId,
        routeRole: 'walk',
      ),
      ScheduleEntry(
        id: 'goal-policy',
        plannedAt: goalAt,
        label: '目的地 到着',
        itemKind: ScheduleEntryKind.goal,
        generatedBy: ScheduleEntrySource.route,
      ),
    ],
    participants: const [],
    memberIds: const ['user-policy'],
  );
}

BusLocation _movingLocation(
  _Request request, {
  required DateTime now,
  required DateTime arrivalAt,
  double ageSeconds = 0,
}) {
  final departureAt = arrivalAt.subtract(const Duration(minutes: 10));
  final serviceDay = DateTime(
    departureAt.year,
    departureAt.month,
    departureAt.day,
  );
  BusStopSchedule stop(int sequence, String id, String name, DateTime at) {
    final minute = at.difference(serviceDay).inMinutes;
    final clock =
        '${(minute ~/ 60).toString().padLeft(2, '0')}:'
        '${(minute % 60).toString().padLeft(2, '0')}';
    return BusStopSchedule(
      sequence: sequence,
      stopId: id,
      stopName: name,
      arrivalMinute: minute,
      departureMinute: minute,
      arrivalTime: clock,
      departureTime: clock,
    );
  }

  final vehicleAt = now.subtract(Duration(seconds: ageSeconds.toInt()));
  return BusLocation(
    vehicleId: 'vehicle-policy',
    routeId: request.routeId,
    tripId: request.tripId,
    fromStopId: 'stop-a',
    fromStopSequence: 1,
    observedStopSequence: 2,
    tripStopIds: const ['stop-a', 'stop-b', 'stop-c'],
    rawStopId: 'stop-b',
    rawStopName: '中間停留所',
    currentStatus: 'IN_TRANSIT_TO',
    vehicleTimestamp: vehicleAt.millisecondsSinceEpoch ~/ 1000,
    vehicleAgeSeconds: ageSeconds,
    tripStopSchedule: [
      stop(1, 'stop-a', '出発停留所', departureAt),
      stop(2, 'stop-b', '中間停留所', departureAt.add(const Duration(minutes: 5))),
      stop(3, 'stop-c', '降車停留所', arrivalAt),
    ],
  );
}

class _Navigation extends ConsumerWidget {
  const _Navigation();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ui = ref.watch(memberUiStateProvider);
    return Text(ui.valueOrNull?.navState.statusLabel ?? 'loading');
  }
}

Future<void> _flush(WidgetTester tester) async {
  // Container reads before mounting use Riverpod's zero-delay scheduler.
  await tester.pump(Duration.zero);
  await tester.pump();
}

class _Harness {
  late final ProviderContainer container;
  final StreamController<DateTime> ticks;
  final _BusSource source;
  bool _disposed = false;

  _Harness({required Trip trip, required DateTime now, required this.source})
    : ticks = StreamController<DateTime>() {
    container = ProviderContainer(
      overrides: [
        tripStreamProvider.overrideWith((ref) => Stream.value(trip)),
        busLocationSourceProvider.overrideWithValue(source),
        minuteTickerProvider.overrideWith((ref) => ticks.stream),
      ],
    );
    ticks.add(now);
    addTearDown(dispose);
  }

  MemberModeController get controller =>
      container.read(memberModeControllerProvider.notifier);

  MemberUiState get ui => container.read(memberUiStateProvider).requireValue;

  Future<void> mount(
    WidgetTester tester, {
    ReplanTransitMemory? restored,
  }) async {
    ProviderSubscription<AsyncValue<Trip?>>? subscription;
    if (restored != null) {
      subscription = container.listen(tripStreamProvider, (_, _) {});
      await _flush(tester);
      expect(container.read(tripStreamProvider).requireValue, isNotNull);
      controller.restoreReplanTransitMemory(restored);
    }
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const Directionality(
          textDirection: TextDirection.ltr,
          child: _Navigation(),
        ),
      ),
    );
    await _flush(tester);
    subscription?.close();
  }

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    container.dispose();
    // A cancelled single-subscription stream may leave close() pending in the
    // widget test's fake async zone. Disposal must not wait for another frame.
    unawaited(ticks.close());
  }

  Future<void> unmount(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox.shrink());
    await _flush(tester);
    dispose();
    await _flush(tester);
  }
}

Future<void> _advance(
  WidgetTester tester,
  _Harness harness,
  DateTime baseNow,
  Duration offset,
) async {
  appClock.setOffset(offset);
  harness.ticks.add(baseNow.add(offset));
  await _flush(tester);
}

void _expectCompleted(_Harness harness) {
  final memory = harness.container
      .read(memberModeControllerProvider)
      .replanTransitMemory;
  expect(memory.completedRideStepId, _busStepId);
  expect(memory.knownOnboardStepId, isNull);
  expect(memory.ridingTransit, isNull);
  expect(harness.ui.resolvedEntry, isNotNull);
  expect(
    harness.ui.resolvedEntry!.itemKind,
    anyOf(
      ScheduleEntryKind.arrival,
      ScheduleEntryKind.walk,
      ScheduleEntryKind.goal,
    ),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    appClock.resetOffset();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (_) async => null);
  });
  tearDown(() {
    appClock.resetOffset();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  testWidgets('cold start after the goal does not query the finished bus', (
    tester,
  ) async {
    final now = appClock.now();
    final source = _BusSource(_notFound);
    final harness = _Harness(
      trip: _trip(now, arrivalAt: now.subtract(const Duration(minutes: 3))),
      now: now,
      source: source,
    );
    await harness.mount(tester);
    expect(harness.ui.resolvedEntry?.itemKind, ScheduleEntryKind.goal);
    expect(harness.ui.resolvedEntry?.routeStepId, isNull);
    expect(source.requests, isEmpty);
    await harness.controller.pollNow();
    await _flush(tester);
    expect(source.requests, isEmpty);
    expect(harness.ui.resolvedEntry?.itemKind, ScheduleEntryKind.goal);
    expect(tester.takeException(), isNull);
    await harness.unmount(tester);
  });

  testWidgets(
    'an initial realtime 404 follows the scheduled ride without inventing completion',
    (tester) async {
      final now = appClock.now();
      final source = _BusSource(_notFound);
      final harness = _Harness(
        trip: _trip(now, arrivalAt: now.add(const Duration(minutes: 5))),
        now: now,
        source: source,
      );
      await harness.mount(tester);
      expect(source.requests, hasLength(1));
      expect(harness.ui.resolvedEntry?.itemKind, ScheduleEntryKind.ride);
      expect(harness.ui.resolvedEntry?.routeStepId, _busStepId);
      final realtime = harness.container.read(memberModeControllerProvider);
      expect(realtime.busProgress, isNull);
      expect(realtime.replanTransitMemory.knownOnboardStepId, isNull);
      expect(realtime.replanTransitMemory.completedRideStepId, isNull);

      await _advance(tester, harness, now, const Duration(minutes: 6));
      await harness.controller.pollNow();
      await _flush(tester);
      expect(source.requests, hasLength(1));
      expect(harness.ui.resolvedEntry?.itemKind, ScheduleEntryKind.walk);
      expect(harness.ui.resolvedEntry?.routeStepId, _walkStepId);
      expect(tester.takeException(), isNull);
      await harness.unmount(tester);
    },
  );

  for (final age in [0.0, 180.0]) {
    testWidgets(
      '${age == 0 ? "fresh" : "stale"} bus positions cannot hold navigation after planned arrival',
      (tester) async {
        final now = appClock.now();
        final arrivalAt = now.add(const Duration(minutes: 5));
        final source = _BusSource(
          (request) async => _movingLocation(
            request,
            now: now,
            arrivalAt: arrivalAt,
            ageSeconds: age,
          ),
        );
        final harness = _Harness(
          trip: _trip(now, arrivalAt: arrivalAt),
          now: now,
          source: source,
        );
        await harness.mount(tester);
        expect(source.requests, hasLength(1));
        expect(
          harness.container.read(memberNavProgressProvider).busProgress?.phase,
          BusProgressPhase.riding,
        );
        expect(
          harness.container
              .read(memberModeControllerProvider)
              .replanTransitMemory
              .knownOnboardStepId,
          _busStepId,
        );

        await _advance(
          tester,
          harness,
          now,
          Duration(minutes: age == 0 ? 6 : 8),
        );
        expect(
          harness.ui.resolvedEntry?.itemKind,
          age == 0 ? ScheduleEntryKind.walk : ScheduleEntryKind.goal,
        );
        expect(harness.ui.resolvedEntry?.routeStepId, isNot(_busStepId));
        await harness.controller.pollNow();
        await _flush(tester);
        _expectCompleted(harness);
        expect(source.requests, hasLength(1));
        await harness.controller.pollNow();
        await _flush(tester);
        _expectCompleted(harness);
        expect(source.requests, hasLength(1));
        expect(tester.takeException(), isNull);
        await harness.unmount(tester);
      },
    );
  }

  testWidgets(
    'a tracked bus disappearing before arrival ends the ride and cannot be resurrected',
    (tester) async {
      final now = appClock.now();
      final arrivalAt = now.add(const Duration(minutes: 5));
      var calls = 0;
      final source = _BusSource((request) async {
        calls++;
        if (calls == 2) return _notFound(request);
        return _movingLocation(request, now: now, arrivalAt: arrivalAt);
      });
      final trip = _trip(now, arrivalAt: arrivalAt);
      final harness = _Harness(trip: trip, now: now, source: source);
      await harness.mount(tester);
      expect(source.requests, hasLength(1));
      expect(
        harness.container.read(memberNavProgressProvider).busProgress?.phase,
        BusProgressPhase.riding,
      );

      await _advance(tester, harness, now, const Duration(minutes: 1));
      await harness.controller.pollNow();
      await _flush(tester);
      expect(source.requests, hasLength(2));
      expect(
        harness.container.read(memberNavProgressProvider).busProgress?.phase,
        BusProgressPhase.arrived,
      );
      _expectCompleted(harness);
      await harness.controller.pollNow();
      await harness.controller.pollNow();
      await _flush(tester);
      expect(source.requests, hasLength(2));
      _expectCompleted(harness);
      await harness.unmount(tester);

      final restartedSource = _BusSource(
        (request) async =>
            _movingLocation(request, now: now, arrivalAt: arrivalAt),
      );
      final restarted = _Harness(
        trip: trip,
        now: now.add(const Duration(minutes: 1)),
        source: restartedSource,
      );
      await restarted.mount(
        tester,
        restored: const ReplanTransitMemory(completedRideStepId: _busStepId),
      );
      _expectCompleted(restarted);
      expect(restartedSource.requests, isEmpty);
      await restarted.controller.pollNow();
      await _flush(tester);
      _expectCompleted(restarted);
      expect(restartedSource.requests, isEmpty);
      expect(tester.takeException(), isNull);
      await restarted.unmount(tester);
    },
  );

  testWidgets(
    'a restored onboard marker treats an early 404 as the end of service',
    (tester) async {
      final now = appClock.now();
      final source = _BusSource(_notFound);
      final harness = _Harness(
        trip: _trip(now, arrivalAt: now.add(const Duration(minutes: 5))),
        now: now,
        source: source,
      );
      await harness.mount(
        tester,
        restored: const ReplanTransitMemory(knownOnboardStepId: _busStepId),
      );
      expect(source.requests, hasLength(1));
      expect(
        harness.container.read(memberNavProgressProvider).busProgress?.phase,
        BusProgressPhase.arrived,
      );
      _expectCompleted(harness);
      await harness.controller.pollNow();
      await harness.controller.pollNow();
      await _flush(tester);
      expect(source.requests, hasLength(1));
      _expectCompleted(harness);
      expect(tester.takeException(), isNull);
      await harness.unmount(tester);
    },
  );

  testWidgets(
    'completion restored during a pending bus request advances the UI and ignores its late position',
    (tester) async {
      final now = appClock.now();
      final arrivalAt = now.add(const Duration(minutes: 5));
      final pending = Completer<BusLocation>();
      var calls = 0;
      final source = _BusSource((request) {
        calls++;
        if (calls == 1) return pending.future;
        return Future.value(
          _movingLocation(request, now: now, arrivalAt: arrivalAt),
        );
      });
      final harness = _Harness(
        trip: _trip(now, arrivalAt: arrivalAt),
        now: now,
        source: source,
      );
      addTearDown(() {
        if (!pending.isCompleted) {
          pending.complete(
            _movingLocation(
              const _Request('route-policy', 'service-policy', null),
              now: now,
              arrivalAt: arrivalAt,
            ),
          );
        }
      });

      await harness.mount(tester);
      expect(source.requests, hasLength(1));
      expect(pending.isCompleted, isFalse);
      expect(harness.ui.resolvedEntry?.itemKind, ScheduleEntryKind.ride);
      harness.controller.restoreReplanTransitMemory(
        const ReplanTransitMemory(completedRideStepId: _busStepId),
      );
      await _flush(tester);
      _expectCompleted(harness);
      expect(pending.isCompleted, isFalse);

      pending.complete(
        _movingLocation(source.requests.single, now: now, arrivalAt: arrivalAt),
      );
      await _flush(tester);
      _expectCompleted(harness);
      expect(
        harness.container.read(memberNavProgressProvider).busProgress?.phase,
        BusProgressPhase.arrived,
      );
      expect(source.requests, hasLength(1));
      await harness.controller.pollNow();
      await _flush(tester);
      _expectCompleted(harness);
      expect(source.requests, hasLength(1));
      expect(tester.takeException(), isNull);
      await harness.unmount(tester);
    },
  );
}

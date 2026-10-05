import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/constants.dart';
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

class _LocationRequest {
  final String routeId;
  final String tripId;
  final String? boardingStopId;
  final DateTime? scheduledDepartureAt;
  final String? vehicleId;
  final bool forceRefresh;

  const _LocationRequest({
    required this.routeId,
    required this.tripId,
    required this.boardingStopId,
    required this.scheduledDepartureAt,
    required this.vehicleId,
    required this.forceRefresh,
  });
}

class _PendingLocation {
  final _LocationRequest request;
  final Completer<BusLocation> completer;

  const _PendingLocation(this.request, this.completer);
}

class _RecordingBusLocationSource implements BusLocationSource {
  final requests = <_LocationRequest>[];
  final pending = <_PendingLocation>[];
  bool holdRequests = false;
  void Function(_LocationRequest request)? onFetch;
  Future<BusLocation> Function(_LocationRequest request)? responder;

  @override
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? boardingStopId,
    DateTime? scheduledDepartureAt,
    String? vehicleId,
    bool forceRefresh = false,
  }) {
    final request = _LocationRequest(
      routeId: routeId,
      tripId: tripId,
      boardingStopId: boardingStopId,
      scheduledDepartureAt: scheduledDepartureAt,
      vehicleId: vehicleId,
      forceRefresh: forceRefresh,
    );
    requests.add(request);
    onFetch?.call(request);
    final customResponder = responder;
    if (customResponder != null) {
      return customResponder(request);
    }
    if (holdRequests) {
      final completer = Completer<BusLocation>();
      pending.add(_PendingLocation(request, completer));
      return completer.future;
    }
    return Future.value(_location(request));
  }

  BusLocation _location(_LocationRequest request) => BusLocation(
    vehicleId: 'vehicle-${request.tripId}',
    fromStopId: null,
    routeId: request.routeId,
    tripId: request.tripId,
    beforeFirstStop: true,
    tripStopIds: const ['stop-a', 'stop-b', 'stop-c'],
    rawStopId: 'stop-a',
    rawStopName: '出発停留所',
    observedStopSequence: 1,
    currentStatus: 'IN_TRANSIT_TO',
    vehicleAgeSeconds: 0,
  );

  void completePending() {
    final requestsToComplete = List<_PendingLocation>.of(pending);
    pending.clear();
    for (final request in requestsToComplete) {
      request.completer.complete(_location(request.request));
    }
  }
}

BusLocation _ridingLocation(
  _LocationRequest request, {
  required DateTime observedAt,
  required DateTime arrivalAt,
}) {
  final departureAt = request.scheduledDepartureAt!;
  final serviceDay = DateTime(
    departureAt.year,
    departureAt.month,
    departureAt.day,
  );
  BusStopSchedule stopSchedule(
    int sequence,
    String stopId,
    String stopName,
    DateTime at,
  ) {
    final minute = at.difference(serviceDay).inMinutes;
    final clock =
        '${(minute ~/ 60).toString().padLeft(2, '0')}:'
        '${(minute % 60).toString().padLeft(2, '0')}';
    return BusStopSchedule(
      sequence: sequence,
      stopId: stopId,
      stopName: stopName,
      arrivalMinute: minute,
      departureMinute: minute,
      arrivalTime: clock,
      departureTime: clock,
    );
  }

  return BusLocation(
    vehicleId: 'vehicle-${request.tripId}',
    fromStopId: 'stop-a',
    routeId: request.routeId,
    tripId: request.tripId,
    tripStopIds: const ['stop-a', 'stop-b', 'stop-c'],
    rawStopId: 'stop-b',
    rawStopName: '中間停留所',
    fromStopSequence: 1,
    observedStopSequence: 2,
    currentStatus: 'IN_TRANSIT_TO',
    vehicleTimestamp: observedAt.millisecondsSinceEpoch ~/ 1000,
    vehicleAgeSeconds: 0,
    tripStopSchedule: [
      stopSchedule(1, 'stop-a', '出発停留所', departureAt),
      stopSchedule(2, 'stop-b', '中間停留所', observedAt),
      stopSchedule(3, 'stop-c', '到着停留所', arrivalAt),
    ],
  );
}

class _NavigationConsumer extends ConsumerWidget {
  final int rebuildMarker;

  const _NavigationConsumer({this.rebuildMarker = 0});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ui = ref.watch(memberUiStateProvider);
    return Text(
      '$rebuildMarker:${ui.value?.navState.statusLabel ?? "loading"}',
    );
  }
}

Widget _host(
  ProviderContainer container, {
  bool showNavigation = true,
  int rebuildMarker = 0,
}) => UncontrolledProviderScope(
  container: container,
  child: Directionality(
    textDirection: TextDirection.ltr,
    child: showNavigation
        ? _NavigationConsumer(rebuildMarker: rebuildMarker)
        : const SizedBox.shrink(),
  ),
);

Future<void> _flushNavigation(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
}

Trip _trip({
  required DateTime now,
  required String id,
  TripType tripType = TripType.group,
  String title = 'Realtime test',
  DateTime? departureAt,
  DateTime? arrivalAt,
}) {
  final departure = departureAt ?? now.subtract(const Duration(minutes: 1));
  final arrival = arrivalAt ?? now.add(const Duration(minutes: 20));
  final rideMinutes = arrival.difference(departure).inMinutes;
  final stepId = 'bus-$id';
  String clockTime(DateTime time) =>
      '${time.hour.toString().padLeft(2, '0')}:'
      '${time.minute.toString().padLeft(2, '0')}';
  final step = StepSeg(
    stepId: stepId,
    kind: 'bus',
    title: 'テスト路線',
    fromName: '出発停留所',
    toName: '到着停留所',
    minutes: rideMinutes,
    routeId: 'route-$id',
    tripId: 'service-$id',
    departureStopId: 'stop-a',
    arrivalPoleId: 'stop-c',
    departureTime: clockTime(departure),
    arrivalTime: clockTime(arrival),
    stops: [
      StopPoint(
        name: '出発停留所',
        point: const LatLng(35.1, 139.1),
        stopId: 'stop-a',
        isOrigin: true,
      ),
      StopPoint(
        name: '中間停留所',
        point: const LatLng(35.2, 139.2),
        stopId: 'stop-b',
      ),
      StopPoint(
        name: '到着停留所',
        point: const LatLng(35.3, 139.3),
        stopId: 'stop-c',
        isDestination: true,
      ),
    ],
  );
  final candidate = Candidate(
    id: 'candidate-$id',
    lines: const ['テスト路線'],
    rides: 1,
    boards: 1,
    transfers: 0,
    total: rideMinutes,
    totalTime: rideMinutes,
    points: const [],
    steps: [step],
    originName: '出発停留所',
    destinationName: '到着停留所',
    departureDate: departure,
  );
  return Trip(
    tripType: tripType,
    id: id,
    joinCode: tripType == TripType.group ? '123456' : '',
    leaderId: 'user-1',
    title: title,
    travelPhase: TravelPhase.active,
    date: now,
    plannedDepartureAt: departure,
    actualDepartureAt: departure,
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: candidate,
      ),
    ],
    schedule: [
      ScheduleEntry(
        id: 'ride-$id',
        plannedAt: departure,
        label: 'テスト路線に乗る',
        itemKind: ScheduleEntryKind.ride,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: stepId,
        routeRole: 'ride',
      ),
      ScheduleEntry(
        id: 'arrival-$id',
        plannedAt: arrival,
        label: '到着停留所に着く',
        itemKind: ScheduleEntryKind.arrival,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: stepId,
        routeRole: 'arrival',
      ),
      ScheduleEntry(
        id: 'goal-$id',
        plannedAt: arrival.add(const Duration(minutes: 1)),
        label: '目的地 到着',
        itemKind: ScheduleEntryKind.goal,
        legIndex: 0,
        generatedBy: ScheduleEntrySource.route,
      ),
    ],
    participants: const [],
    memberIds: const ['user-1'],
  );
}

Trip _withSecondLeg(Trip first, {required int completedLegIndex}) {
  if (first.tripType != TripType.group || first.legs.length != 1) {
    throw StateError('test helper requires a one-leg group trip');
  }

  final latestFirstLegTime = first.schedule
      .map((entry) => entry.plannedAt)
      .reduce((left, right) => left.isAfter(right) ? left : right);
  final secondStart = latestFirstLegTime.add(const Duration(minutes: 10));
  final secondStep = StepSeg(
    stepId: 'walk-${first.id}-second',
    kind: 'walk',
    title: '徒歩',
    fromName: '到着停留所',
    toName: '次の目的地',
    minutes: 1,
    meters: 80,
    departureTime:
        '${secondStart.hour.toString().padLeft(2, '0')}:'
        '${secondStart.minute.toString().padLeft(2, '0')}',
    arrivalTime:
        '${secondStart.add(const Duration(minutes: 1)).hour.toString().padLeft(2, '0')}:'
        '${secondStart.add(const Duration(minutes: 1)).minute.toString().padLeft(2, '0')}',
  );
  final secondCandidate = Candidate(
    id: 'candidate-${first.id}-second',
    lines: const [],
    rides: 0,
    boards: 0,
    transfers: 0,
    total: 1,
    totalTime: 1,
    steps: [secondStep],
    points: const [],
    originName: '到着停留所',
    destinationName: '次の目的地',
    departureDate: secondStart,
  );

  return Trip(
    schemaVersion: first.schemaVersion,
    tripType: first.tripType,
    id: first.id,
    joinCode: first.joinCode,
    leaderId: first.leaderId,
    title: first.title,
    travelPhase: first.travelPhase,
    date: first.date,
    plannedDepartureAt: first.plannedDepartureAt,
    actualDepartureAt: first.actualDepartureAt,
    legs: [
      first.legs.single,
      Leg(
        direction: LegDirection.inbound,
        status: LegStatus.confirmed,
        candidate: secondCandidate,
      ),
    ],
    schedule: [
      ...first.schedule,
      ScheduleEntry(
        id: 'walk-${first.id}-second-entry',
        plannedAt: secondStart,
        label: '次の目的地まで歩く',
        itemKind: ScheduleEntryKind.walk,
        legIndex: 1,
        generatedBy: ScheduleEntrySource.route,
        routeStepId: secondStep.stepId,
        routeRole: 'walk',
      ),
      ScheduleEntry(
        id: 'goal-${first.id}-second',
        plannedAt: secondStart.add(const Duration(minutes: 1)),
        label: '次の目的地 到着',
        itemKind: ScheduleEntryKind.goal,
        legIndex: 1,
        generatedBy: ScheduleEntrySource.route,
      ),
    ],
    participants: first.participants,
    memberIds: first.memberIds,
    completedLegIndex: completedLegIndex,
  );
}

ProviderContainer _container({
  required Stream<Trip?> trips,
  required DateTime now,
  required _RecordingBusLocationSource source,
  Stream<DateTime>? ticks,
}) => ProviderContainer(
  overrides: [
    tripStreamProvider.overrideWith((ref) => trips),
    minuteTickerProvider.overrideWith((ref) => ticks ?? Stream.value(now)),
    busLocationSourceProvider.overrideWithValue(source),
  ],
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    appClock.resetOffset();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
          expect(call.method, 'HapticFeedback.vibrate');
          return null;
        });
  });
  tearDown(() {
    appClock.resetOffset();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  for (final tripType in TripType.values) {
    testWidgets(
      '${tripType.name} navigation starts realtime without a screen initializer',
      (tester) async {
        final now = appClock.now();
        final trip = _trip(now: now, id: tripType.name, tripType: tripType);
        final source = _RecordingBusLocationSource();
        final container = _container(
          trips: Stream.value(trip),
          now: now,
          source: source,
        );
        addTearDown(container.dispose);
        final progressAtFetch = <MemberNavState>[];
        source.onFetch = (_) {
          progressAtFetch.add(container.read(memberNavProgressProvider));
        };

        await tester.pumpWidget(_host(container));
        await _flushNavigation(tester);

        expect(source.requests, hasLength(1));
        final request = source.requests.single;
        expect(request.routeId, 'route-${tripType.name}');
        expect(request.tripId, 'service-${tripType.name}');
        expect(request.boardingStopId, 'stop-a');
        expect(request.scheduledDepartureAt, trip.plannedDepartureAt);
        expect(request.vehicleId, isNull);
        expect(request.forceRefresh, isTrue);
        expect(progressAtFetch.single.currentStepId, isNull);
        expect(progressAtFetch.single.busProgress, isNull);
        final progress = container.read(memberNavProgressProvider);
        expect(progress.currentStepId, 'bus-${tripType.name}');
        expect(progress.busProgress?.phase, BusProgressPhase.approaching);
        expect(container.read(memberUiStateProvider).hasValue, isTrue);
        expect(tester.takeException(), isNull);

        await tester.pumpWidget(_host(container, showNavigation: false));
        await _flushNavigation(tester);
      },
    );
  }

  testWidgets(
    'rebuilding a navigation consumer does not start another poller',
    (tester) async {
      final now = appClock.now();
      final source = _RecordingBusLocationSource();
      final container = _container(
        trips: Stream.value(_trip(now: now, id: 'rebuild')),
        now: now,
        source: source,
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_host(container));
      await _flushNavigation(tester);
      final controller = container.read(memberModeControllerProvider.notifier);
      expect(source.requests, hasLength(1));

      await tester.pumpWidget(_host(container, rebuildMarker: 1));
      await _flushNavigation(tester);
      await tester.pumpWidget(_host(container, rebuildMarker: 2));
      await _flushNavigation(tester);

      expect(source.requests, hasLength(1));
      expect(
        container.read(memberModeControllerProvider.notifier),
        same(controller),
      );
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
    },
  );

  testWidgets(
    'planned arrival advances a boarded bus without polling its old realtime trip',
    (tester) async {
      final baseNow = appClock.now();
      final ticks = StreamController<DateTime>()..add(baseNow);
      final source = _RecordingBusLocationSource();
      var fetchCount = 0;
      source.responder = (request) async {
        fetchCount += 1;
        if (fetchCount == 1) {
          return _ridingLocation(
            request,
            observedAt: baseNow,
            arrivalAt: baseNow.add(const Duration(minutes: 1)),
          );
        }
        throw const BusLocationNotAvailableException(
          code: 'bus_trip_not_found',
        );
      };
      final trip = _trip(
        now: baseNow,
        id: 'feed-end',
        arrivalAt: baseNow.add(const Duration(minutes: 1)),
      );
      final container = _container(
        trips: Stream.value(trip),
        now: baseNow,
        source: source,
        ticks: ticks.stream,
      );
      addTearDown(() async {
        container.dispose();
        await ticks.close();
      });

      await tester.pumpWidget(_host(container));
      await _flushNavigation(tester);

      expect(source.requests, hasLength(1));
      expect(
        container.read(memberNavProgressProvider).busProgress?.phase,
        BusProgressPhase.riding,
      );
      expect(
        container
            .read(memberModeControllerProvider)
            .replanTransitMemory
            .knownOnboardStepId,
        'bus-feed-end',
      );

      appClock.setOffset(const Duration(minutes: 3));
      ticks.add(baseNow.add(const Duration(minutes: 3)));
      await container.read(memberModeControllerProvider.notifier).pollNow();
      await _flushNavigation(tester);

      expect(source.requests, hasLength(1));
      final realtimeState = container.read(memberModeControllerProvider);
      expect(trip.completedLegIndex, -1);
      expect(trip.activeLegIndex, 0);
      expect(realtimeState.busProgress, isNull);
      expect(realtimeState.replanTransitMemory.knownOnboardStepId, isNull);
      expect(
        realtimeState.replanTransitMemory.completedRideStepId,
        'bus-feed-end',
      );
      expect(
        realtimeState.replanTransitMemory.lastConfirmedTransitPlace?.name,
        '到着停留所',
      );
      final nav = container.read(memberNavProgressProvider);
      expect(nav.busProgress, isNull);
      expect(nav.rideRealtimeUnavailable, isFalse);
      final ui = container.read(memberUiStateProvider).requireValue;
      expect(ui.resolvedEntry?.itemKind, ScheduleEntryKind.goal);
      expect(ui.resolvedEntry?.routeStepId, isNot('bus-feed-end'));
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
    },
  );

  testWidgets(
    'advancing the active leg starts fresh return navigation without polling the old ride',
    (tester) async {
      final baseNow = appClock.now();
      final firstLeg = _trip(
        now: baseNow,
        id: 'cross-leg',
        tripType: TripType.group,
        arrivalAt: baseNow.add(const Duration(minutes: 2)),
      );
      final firstLegActive = _withSecondLeg(firstLeg, completedLegIndex: -1);
      final secondLegActive = _withSecondLeg(firstLeg, completedLegIndex: 0);
      final trips = StreamController<Trip?>();
      final source = _RecordingBusLocationSource();
      var fetchCount = 0;
      source.responder = (request) async {
        fetchCount += 1;
        if (fetchCount == 1) {
          return _ridingLocation(
            request,
            observedAt: baseNow,
            arrivalAt: baseNow.add(const Duration(minutes: 2)),
          );
        }
        throw const BusLocationNotAvailableException(
          code: 'bus_trip_not_found',
        );
      };
      final container = _container(
        trips: trips.stream,
        now: baseNow,
        source: source,
      );
      addTearDown(() async {
        container.dispose();
        await trips.close();
      });

      await tester.pumpWidget(_host(container));
      trips.add(firstLegActive);
      await _flushNavigation(tester);
      expect(source.requests, hasLength(1));
      expect(
        container.read(memberNavProgressProvider).busProgress?.phase,
        BusProgressPhase.riding,
      );

      appClock.setOffset(const Duration(minutes: 1));
      await container.read(memberModeControllerProvider.notifier).pollNow();
      await _flushNavigation(tester);
      expect(source.requests, hasLength(2));
      expect(
        container
            .read(memberModeControllerProvider)
            .replanTransitMemory
            .knownOnboardStepId,
        isNull,
      );
      expect(
        container
            .read(memberModeControllerProvider)
            .replanTransitMemory
            .completedRideStepId,
        'bus-cross-leg',
      );
      expect(
        container.read(memberNavProgressProvider).busProgress?.phase,
        BusProgressPhase.arrived,
      );
      expect(
        container.read(memberNavProgressProvider).rideRealtimeUnavailable,
        isFalse,
      );
      expect(
        container
            .read(memberModeControllerProvider)
            .replanTransitMemory
            .ridingTransit,
        isNull,
      );

      final outboundController = container.read(
        memberModeControllerProvider.notifier,
      );
      final outboundNotifier = container.read(
        memberNavProgressProvider.notifier,
      );

      trips.add(secondLegActive);
      await _flushNavigation(tester);

      expect(outboundController.mounted, isFalse);
      expect(outboundNotifier.mounted, isFalse);
      expect(
        container.read(memberModeControllerProvider.notifier),
        isNot(same(outboundController)),
      );
      expect(
        container.read(memberNavProgressProvider.notifier),
        isNot(same(outboundNotifier)),
      );
      final realtime = container.read(memberModeControllerProvider);
      expect(realtime.trackedStepId, isNull);
      expect(realtime.trackedVehicleId, isNull);
      expect(realtime.busProgress, isNull);
      expect(realtime.replanTransitMemory.knownOnboardStepId, isNull);
      final nav = container.read(memberNavProgressProvider);
      expect(nav.currentStepId, isNull);
      expect(nav.busProgress, isNull);
      expect(nav.rideRealtimeUnavailable, isFalse);
      final ui = container.read(memberUiStateProvider).requireValue;
      expect(ui.resolvedEntry, isNull);
      expect(ui.windowEntries, isNotEmpty);
      expect(ui.windowEntries.every((entry) => entry.legIndex == 1), isTrue);
      expect(source.requests, hasLength(2));

      await tester.pump(kRealtimePollInterval * 2);
      await _flushNavigation(tester);
      expect(source.requests, hasLength(2));
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
    },
  );

  testWidgets('an old bus response is ignored after the active leg advances', (
    tester,
  ) async {
    final now = appClock.now();
    final firstLeg = _trip(now: now, id: 'leg-in-flight');
    final trips = StreamController<Trip?>();
    final source = _RecordingBusLocationSource()..holdRequests = true;
    final container = _container(trips: trips.stream, now: now, source: source);
    addTearDown(() async {
      container.dispose();
      await trips.close();
    });

    await tester.pumpWidget(_host(container));
    trips.add(_withSecondLeg(firstLeg, completedLegIndex: -1));
    await _flushNavigation(tester);
    expect(source.requests, hasLength(1));
    expect(source.pending, hasLength(1));
    final outboundController = container.read(
      memberModeControllerProvider.notifier,
    );
    final outboundNotifier = container.read(memberNavProgressProvider.notifier);

    trips.add(_withSecondLeg(firstLeg, completedLegIndex: 0));
    await _flushNavigation(tester);
    final returnController = container.read(
      memberModeControllerProvider.notifier,
    );
    final returnNotifier = container.read(memberNavProgressProvider.notifier);
    expect(outboundController.mounted, isFalse);
    expect(outboundNotifier.mounted, isFalse);
    expect(returnController, isNot(same(outboundController)));
    expect(returnNotifier, isNot(same(outboundNotifier)));
    expect(source.requests, hasLength(1));

    source.completePending();
    await _flushNavigation(tester);
    expect(
      container.read(memberModeControllerProvider.notifier),
      same(returnController),
    );
    expect(
      container.read(memberNavProgressProvider.notifier),
      same(returnNotifier),
    );
    final realtime = container.read(memberModeControllerProvider);
    expect(realtime.trackedStepId, isNull);
    expect(realtime.trackedVehicleId, isNull);
    expect(realtime.busProgress, isNull);
    expect(realtime.replanTransitMemory.knownOnboardStepId, isNull);
    final nav = container.read(memberNavProgressProvider);
    expect(nav.currentStepId, isNull);
    expect(nav.busProgress, isNull);
    expect(nav.rideRealtimeUnavailable, isFalse);
    expect(
      container
          .read(memberUiStateProvider)
          .requireValue
          .windowEntries
          .every((entry) => entry.legIndex == 1),
      isTrue,
    );

    await tester.pump(kRealtimePollInterval * 2);
    await _flushNavigation(tester);
    expect(source.requests, hasLength(1));
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(_host(container, showNavigation: false));
    await _flushNavigation(tester);
  });

  testWidgets(
    'a restored onboard marker completes after planned arrival without a realtime request',
    (tester) async {
      final now = appClock.now();
      final trip = _trip(
        now: now,
        id: 'restored-feed-end',
        departureAt: now.subtract(const Duration(minutes: 4)),
        arrivalAt: now.subtract(const Duration(minutes: 2)),
      );
      final source = _RecordingBusLocationSource();
      source.responder = (_) async {
        throw const BusLocationNotAvailableException(
          code: 'bus_trip_not_found',
        );
      };
      final container = _container(
        trips: Stream.value(trip),
        now: now,
        source: source,
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_host(container));
      await _flushNavigation(tester);
      expect(source.requests, isEmpty);
      expect(trip.activeLegIndex, 0);
      expect(
        container
            .read(memberUiStateProvider)
            .requireValue
            .resolvedEntry
            ?.itemKind,
        ScheduleEntryKind.goal,
      );
      final controller = container.read(memberModeControllerProvider.notifier);
      controller.restoreReplanTransitMemory(
        const ReplanTransitMemory(knownOnboardStepId: 'bus-restored-feed-end'),
      );
      expect(container.read(memberModeControllerProvider).busProgress, isNull);
      expect(container.read(memberNavProgressProvider).busProgress, isNull);

      await controller.pollNow();
      await _flushNavigation(tester);

      expect(source.requests, isEmpty);
      final realtime = container.read(memberModeControllerProvider);
      expect(realtime.busProgress, isNull);
      expect(realtime.replanTransitMemory.knownOnboardStepId, isNull);
      expect(
        realtime.replanTransitMemory.completedRideStepId,
        'bus-restored-feed-end',
      );
      expect(
        realtime.replanTransitMemory.lastConfirmedTransitPlace?.name,
        '到着停留所',
      );
      expect(container.read(memberNavProgressProvider).busProgress, isNull);
      expect(
        container.read(memberNavProgressProvider).rideRealtimeUnavailable,
        isFalse,
      );
      final ui = container.read(memberUiStateProvider).requireValue;
      expect(ui.resolvedEntry?.itemKind, ScheduleEntryKind.goal);
      expect(ui.resolvedEntry?.routeStepId, isNot('bus-restored-feed-end'));
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
    },
  );

  testWidgets(
    'periodic polling uses the configured interval and tracked vehicle',
    (tester) async {
      final now = appClock.now();
      final source = _RecordingBusLocationSource();
      final container = _container(
        trips: Stream.value(_trip(now: now, id: 'periodic')),
        now: now,
        source: source,
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_host(container));
      await _flushNavigation(tester);
      expect(source.requests, hasLength(1));

      await tester.pump(
        kRealtimePollInterval - const Duration(milliseconds: 1),
      );
      expect(source.requests, hasLength(1));
      await tester.pump(const Duration(milliseconds: 1));
      await _flushNavigation(tester);

      expect(source.requests, hasLength(2));
      expect(source.requests.last.forceRefresh, isFalse);
      expect(source.requests.last.vehicleId, 'vehicle-service-periodic');
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
    },
  );

  testWidgets(
    'removing the final consumer disposes realtime and stops polling',
    (tester) async {
      final now = appClock.now();
      final source = _RecordingBusLocationSource();
      final container = _container(
        trips: Stream.value(_trip(now: now, id: 'dispose')),
        now: now,
        source: source,
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_host(container));
      await _flushNavigation(tester);
      expect(source.requests, hasLength(1));
      expect(container.exists(memberModeControllerProvider), isTrue);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
      expect(container.exists(memberModeControllerProvider), isFalse);
      expect(container.exists(memberNavProgressProvider), isFalse);
      await tester.pump(kRealtimePollInterval * 2);

      expect(source.requests, hasLength(1));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'a delayed trip stream starts its first poll as soon as the trip is ready',
    (tester) async {
      final now = appClock.now();
      final trips = StreamController<Trip?>();
      final source = _RecordingBusLocationSource();
      final container = _container(
        trips: trips.stream,
        now: now,
        source: source,
      );
      addTearDown(() async {
        container.dispose();
        await trips.close();
      });

      await tester.pumpWidget(_host(container));
      await _flushNavigation(tester);
      expect(source.requests, isEmpty);

      trips.add(_trip(now: now, id: 'delayed'));
      await _flushNavigation(tester);

      expect(source.requests, hasLength(1));
      expect(source.requests.single.tripId, 'service-delayed');
      expect(source.requests.single.forceRefresh, isTrue);
      expect(
        container.read(memberNavProgressProvider).currentStepId,
        'bus-delayed',
      );
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
    },
  );

  testWidgets(
    'trip edits retain progress while a new trip ID gets fresh progress',
    (tester) async {
      final now = appClock.now();
      final trips = StreamController<Trip?>();
      final source = _RecordingBusLocationSource();
      final container = _container(
        trips: trips.stream,
        now: now,
        source: source,
      );
      addTearDown(() async {
        container.dispose();
        await trips.close();
      });

      await tester.pumpWidget(_host(container));
      trips.add(_trip(now: now, id: 'first'));
      await _flushNavigation(tester);
      final firstNotifier = container.read(memberNavProgressProvider.notifier);
      final firstController = container.read(
        memberModeControllerProvider.notifier,
      );
      final firstProgress = container.read(memberNavProgressProvider);
      expect(
        container.read(memberNavProgressProvider).currentStepId,
        'bus-first',
      );
      expect(source.requests, hasLength(1));

      trips.add(
        _trip(
          now: now,
          id: 'first',
          title: 'Edited title',
          arrivalAt: now.add(const Duration(minutes: 25)),
        ),
      );
      await _flushNavigation(tester);
      expect(
        container.read(memberNavProgressProvider.notifier),
        same(firstNotifier),
      );
      expect(
        container.read(memberModeControllerProvider.notifier),
        same(firstController),
      );
      expect(
        container.read(memberNavProgressProvider).currentStepId,
        'bus-first',
      );
      expect(container.read(memberNavProgressProvider), same(firstProgress));
      expect(
        container
            .read(tripStreamProvider)
            .requireValue
            ?.schedule
            .singleWhere((entry) => entry.itemKind == ScheduleEntryKind.arrival)
            .plannedAt,
        now.add(const Duration(minutes: 25)),
      );
      expect(source.requests, hasLength(1));

      source.holdRequests = true;
      trips.add(_trip(now: now, id: 'second'));
      await _flushNavigation(tester);

      expect(source.requests, hasLength(2));
      expect(source.requests.last.tripId, 'service-second');
      expect(source.requests.last.forceRefresh, isTrue);
      expect(source.requests.last.vehicleId, isNull);
      expect(
        container.read(memberNavProgressProvider.notifier),
        isNot(same(firstNotifier)),
      );
      expect(
        container.read(memberModeControllerProvider.notifier),
        isNot(same(firstController)),
      );
      final freshProgress = container.read(memberNavProgressProvider);
      expect(freshProgress.currentStepId, isNull);
      expect(freshProgress.busProgress, isNull);
      expect(freshProgress.rideRealtimeUnavailable, isFalse);

      source.completePending();
      await _flushNavigation(tester);
      expect(
        container.read(memberNavProgressProvider).currentStepId,
        'bus-second',
      );
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
    },
  );

  testWidgets(
    'parent and child navigation scopes poll and retain progress independently',
    (tester) async {
      final now = appClock.now();
      final parentSource = _RecordingBusLocationSource();
      final childSource = _RecordingBusLocationSource();
      final parent = _container(
        trips: Stream.value(_trip(now: now, id: 'parent')),
        now: now,
        source: parentSource,
      );
      final child = ProviderContainer(
        parent: parent,
        overrides: [
          tripStreamProvider.overrideWith(
            (ref) => Stream.value(
              _trip(now: now, id: 'child', tripType: TripType.solo),
            ),
          ),
          busLocationSourceProvider.overrideWithValue(childSource),
        ],
      );
      addTearDown(() {
        child.dispose();
        parent.dispose();
      });

      Widget navigationScopes({
        bool showParentNavigation = true,
        bool showChildNavigation = true,
      }) => UncontrolledProviderScope(
        container: parent,
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Column(
            children: [
              showParentNavigation
                  ? const _NavigationConsumer()
                  : const SizedBox.shrink(),
              UncontrolledProviderScope(
                container: child,
                child: showChildNavigation
                    ? const _NavigationConsumer()
                    : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      );

      await tester.pumpWidget(navigationScopes());
      await _flushNavigation(tester);

      expect(parentSource.requests, hasLength(1));
      expect(childSource.requests, hasLength(1));
      expect(parentSource.requests.single.tripId, 'service-parent');
      expect(childSource.requests.single.tripId, 'service-child');
      expect(
        parent.read(memberNavProgressProvider).currentStepId,
        'bus-parent',
      );
      expect(child.read(memberNavProgressProvider).currentStepId, 'bus-child');
      expect(
        child.read(memberNavProgressProvider.notifier),
        isNot(same(parent.read(memberNavProgressProvider.notifier))),
      );
      // Child-container exists() can fall back to the active root provider.
      // Retain each instance to verify which session actually gets disposed.
      final parentController = parent.read(
        memberModeControllerProvider.notifier,
      );
      final childController = child.read(memberModeControllerProvider.notifier);
      expect(childController, isNot(same(parentController)));

      await tester.pumpWidget(navigationScopes(showChildNavigation: false));
      await _flushNavigation(tester);
      expect(childController.mounted, isFalse);
      expect(parentController.mounted, isTrue);
      await tester.pump(kRealtimePollInterval);
      await _flushNavigation(tester);

      expect(parentSource.requests, hasLength(2));
      expect(childSource.requests, hasLength(1));
      expect(
        parent.read(memberNavProgressProvider).currentStepId,
        'bus-parent',
      );
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(
        navigationScopes(
          showParentNavigation: false,
          showChildNavigation: false,
        ),
      );
      await _flushNavigation(tester);
      expect(parentController.mounted, isFalse);
    },
  );

  testWidgets(
    'an in-flight result is ignored after the final consumer is removed',
    (tester) async {
      final now = appClock.now();
      final source = _RecordingBusLocationSource()..holdRequests = true;
      final container = _container(
        trips: Stream.value(_trip(now: now, id: 'in-flight')),
        now: now,
        source: source,
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_host(container));
      await _flushNavigation(tester);
      expect(source.requests, hasLength(1));
      expect(source.pending, hasLength(1));

      await tester.pumpWidget(_host(container, showNavigation: false));
      await _flushNavigation(tester);
      expect(container.exists(memberModeControllerProvider), isFalse);
      expect(container.exists(memberNavProgressProvider), isFalse);

      source.completePending();
      await _flushNavigation(tester);
      await tester.pump(kRealtimePollInterval * 2);

      expect(source.requests, hasLength(1));
      expect(container.exists(memberModeControllerProvider), isFalse);
      expect(container.exists(memberNavProgressProvider), isFalse);
      expect(tester.takeException(), isNull);
    },
  );
}

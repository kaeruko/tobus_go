import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/logic/replan_anchor_context.dart';
import 'package:toeigo/logic/replan_transit_memory.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/providers/replan_anchor_provider.dart';

void main() {
  final now = DateTime(2026, 8, 15, 18, 4);

  ReplanTransitPlace place(String name, double lat, double lon) {
    return ReplanTransitPlace(name: name, point: LatLng(lat, lon));
  }

  StepSeg walk(String id, String from, String to) {
    return StepSeg(
      stepId: id,
      kind: 'walk',
      title: '徒歩',
      fromName: from,
      toName: to,
      minutes: 4,
    );
  }

  StepSeg rail(String id, String from, String to) {
    return StepSeg(
      stepId: id,
      kind: 'rail',
      title: '浅草線',
      fromName: from,
      toName: to,
      minutes: 8,
      stops: [
        StopPoint(name: from, point: const LatLng(35.697, 139.785)),
        StopPoint(name: to, point: const LatLng(35.692, 139.785)),
      ],
    );
  }

  Candidate candidate({
    required String id,
    required String originName,
    required List<StepSeg> steps,
    LatLng? originCoords = const LatLng(35.710, 139.840),
  }) {
    return Candidate(
      id: id,
      lines: const [],
      rides: steps.where((step) => step.isRide).length,
      boards: steps.where((step) => step.isRide).length,
      transfers: 0,
      total: 0,
      totalTime: 20,
      steps: steps,
      points: const [],
      originName: originName,
      destinationName: '目的地',
      originCoords: originCoords,
      destinationCoords: const LatLng(35.680, 139.770),
    );
  }

  Leg leg({required LegDirection direction, required Candidate candidate}) {
    return Leg(
      direction: direction,
      status: LegStatus.confirmed,
      candidate: candidate,
    );
  }

  Trip trip(List<Leg> legs) {
    return Trip(
      id: 'trip-replan-context',
      joinCode: '',
      leaderId: 'user-1',
      title: '再探索テスト',
      travelPhase: TravelPhase.active,
      date: DateTime(2026, 8, 15),
      plannedDepartureAt: now,
      actualDepartureAt: now,
      legs: legs,
      schedule: const [],
      participants: const [],
      memberIds: const ['user-1'],
    );
  }

  final outbound = candidate(
    id: 'outbound',
    originName: '自宅',
    steps: [
      walk('out-walk', '自宅', '本所吾妻橋'),
      rail('out-rail', '本所吾妻橋', '東日本橋'),
      walk('out-final-walk', '東日本橋', '目的地'),
    ],
  );

  test('initial preboarding walk uses the active leg origin instead of old memory', () {
    final context = ReplanAnchorContextBuilder.build(
      trip: trip([
        leg(direction: LegDirection.outbound, candidate: outbound),
      ]),
      activeStepId: 'out-walk',
      memory: ReplanTransitMemory(
        lastConfirmedTransitPlace: place('前の旅の駅', 35.0, 139.0),
      ),
    );

    final anchor = ReplanAnchorResolver.resolve(context: context, now: now);

    expect(anchor.placeName, '自宅');
    expect(anchor.point, const LatLng(35.710, 139.840));
    expect(anchor.availableAt, now);
    expect(anchor.source, ReplanAnchorSource.tripOrigin);
  });

  test('moving ride resolves to the predicted next station and predicted time', () {
    final predicted = DateTime(2026, 8, 15, 18, 6);
    final observation = RidingTransitObservation(
      stepId: 'out-rail',
      motion: RidingTransitMotion.inTransit,
      currentPlace: place('浅草橋', 35.697, 139.785),
      nextPlace: place('蔵前', 35.703, 139.790),
      predictedNextAvailableAt: predicted,
    );
    final context = ReplanAnchorContextBuilder.build(
      trip: trip([
        leg(direction: LegDirection.outbound, candidate: outbound),
      ]),
      activeStepId: 'out-rail',
      memory: const ReplanTransitMemory().observeRide(observation),
    );

    final anchor = ReplanAnchorResolver.resolve(context: context, now: now);

    expect(anchor.placeName, '蔵前');
    expect(anchor.availableAt, predicted);
    expect(anchor.source, ReplanAnchorSource.predictedNextTransitPlace);
    expect(anchor.routeStepId, 'out-rail');
  });

  test('stopped ride resolves to the current station at current time', () {
    final observation = RidingTransitObservation(
      stepId: 'out-rail',
      motion: RidingTransitMotion.stopped,
      currentPlace: place('浅草橋', 35.697, 139.785),
    );
    final context = ReplanAnchorContextBuilder.build(
      trip: trip([
        leg(direction: LegDirection.outbound, candidate: outbound),
      ]),
      activeStepId: 'out-rail',
      memory: const ReplanTransitMemory().observeRide(observation),
    );

    final anchor = ReplanAnchorResolver.resolve(context: context, now: now);

    expect(anchor.placeName, '浅草橋');
    expect(anchor.availableAt, now);
    expect(anchor.source, ReplanAnchorSource.currentTransitPlace);
  });

  test('transfer/final walk resolves from the last confirmed transit place', () {
    final confirmed = place('東日本橋', 35.692, 139.785);
    final memory = ReplanTransitMemory(lastConfirmedTransitPlace: confirmed);
    final context = ReplanAnchorContextBuilder.build(
      trip: trip([
        leg(direction: LegDirection.outbound, candidate: outbound),
      ]),
      activeStepId: 'out-final-walk',
      memory: memory,
    );

    final anchor = ReplanAnchorResolver.resolve(context: context, now: now);

    expect(anchor.placeName, '東日本橋');
    expect(anchor.availableAt, now);
    expect(anchor.source, ReplanAnchorSource.lastConfirmedTransitPlace);
  });

  test('new leg initial walk does not reuse the previous leg transit place', () {
    final inbound = candidate(
      id: 'inbound',
      originName: '博物館',
      originCoords: const LatLng(35.718, 139.776),
      steps: [
        walk('in-walk', '博物館', '上野御徒町'),
        rail('in-rail', '上野御徒町', '東日本橋'),
      ],
    );
    final context = ReplanAnchorContextBuilder.build(
      trip: trip([
        leg(direction: LegDirection.outbound, candidate: outbound),
        leg(direction: LegDirection.inbound, candidate: inbound),
      ]),
      activeStepId: 'in-walk',
      memory: ReplanTransitMemory(
        lastConfirmedTransitPlace: place('押上', 35.710, 139.813),
      ),
    );

    final anchor = ReplanAnchorResolver.resolve(context: context, now: now);

    expect(anchor.placeName, '博物館');
    expect(anchor.point, const LatLng(35.718, 139.776));
    expect(anchor.source, ReplanAnchorSource.tripOrigin);
  });

  test('active ride rejects a realtime observation from another step', () {
    final observation = RidingTransitObservation(
      stepId: 'other-rail',
      motion: RidingTransitMotion.stopped,
      currentPlace: place('浅草橋', 35.697, 139.785),
    );

    expect(
      () => ReplanAnchorContextBuilder.build(
        trip: trip([
          leg(direction: LegDirection.outbound, candidate: outbound),
        ]),
        activeStepId: 'out-rail',
        memory: const ReplanTransitMemory().observeRide(observation),
      ),
      throwsStateError,
    );
  });

  test('initial phase fails fast when the saved route origin has no coordinates', () {
    final invalid = candidate(
      id: 'missing-origin',
      originName: '自宅',
      originCoords: null,
      steps: [
        walk('invalid-walk', '自宅', '本所吾妻橋'),
        rail('invalid-rail', '本所吾妻橋', '東日本橋'),
      ],
    );

    expect(
      () => ReplanAnchorContextBuilder.build(
        trip: trip([
          leg(direction: LegDirection.outbound, candidate: invalid),
        ]),
        activeStepId: 'invalid-walk',
        memory: const ReplanTransitMemory(),
      ),
      throwsStateError,
    );
  });

  test('unknown active step fails instead of selecting another leg', () {
    expect(
      () => ReplanAnchorContextBuilder.build(
        trip: trip([
          leg(direction: LegDirection.outbound, candidate: outbound),
        ]),
        activeStepId: 'missing-step',
        memory: const ReplanTransitMemory(),
      ),
      throwsStateError,
    );
  });

  test('replanAnchorProvider is exposed for the navigation UI layer', () {
    expect(replanAnchorProvider, isNotNull);
  });
}

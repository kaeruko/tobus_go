import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';

void main() {
  final now = DateTime(2026, 8, 15, 18, 4);

  ReplanTransitPlace place(
    String name,
    double lat,
    double lon, {
    String? stopId,
  }) => ReplanTransitPlace(
    name: name,
    stopId: stopId,
    point: LatLng(lat, lon),
  );

  test('train in transit uses next station and predicted arrival time', () {
    final predicted = DateTime(2026, 8, 15, 18, 6);
    final anchor = ReplanAnchorResolver.resolve(
      context: ReplanAnchorContext(
        ridingTransit: RidingTransitObservation(
          stepId: 'rail-1',
          motion: RidingTransitMotion.inTransit,
          currentPlace: place('浅草橋', 35.697, 139.785),
          nextPlace: place('蔵前', 35.703, 139.790),
          predictedNextAvailableAt: predicted,
        ),
      ),
      now: now,
    );

    expect(anchor.placeName, '蔵前');
    expect(anchor.availableAt, predicted);
    expect(anchor.source, ReplanAnchorSource.predictedNextTransitPlace);
    expect(anchor.routeStepId, 'rail-1');
  });

  test('train stopped uses current station and current time', () {
    final anchor = ReplanAnchorResolver.resolve(
      context: ReplanAnchorContext(
        ridingTransit: RidingTransitObservation(
          stepId: 'rail-1',
          motion: RidingTransitMotion.stopped,
          currentPlace: place('浅草橋', 35.697, 139.785),
        ),
      ),
      now: now,
    );

    expect(anchor.placeName, '浅草橋');
    expect(anchor.availableAt, now);
    expect(anchor.source, ReplanAnchorSource.currentTransitPlace);
  });

  test('bus in transit uses next bus stop and predicted arrival time', () {
    final predicted = DateTime(2026, 8, 15, 18, 8);
    final anchor = ReplanAnchorResolver.resolve(
      context: ReplanAnchorContext(
        ridingTransit: RidingTransitObservation(
          stepId: 'bus-1',
          motion: RidingTransitMotion.inTransit,
          currentPlace: place(
            '平井七丁目',
            35.706,
            139.842,
            stopId: 'bus-stop-1',
          ),
          nextPlace: place(
            '平井七丁目北公園前',
            35.708,
            139.840,
            stopId: 'bus-stop-2',
          ),
          predictedNextAvailableAt: predicted,
        ),
      ),
      now: now,
    );

    expect(anchor.placeName, '平井七丁目北公園前');
    expect(anchor.stopId, 'bus-stop-2');
    expect(anchor.availableAt, predicted);
    expect(anchor.source, ReplanAnchorSource.predictedNextTransitPlace);
  });

  test('moving observation is blocked after its next-stop prediction expires', () {
    final predicted = DateTime(2026, 8, 15, 18, 6);
    final observation = RidingTransitObservation(
      stepId: 'bus-1',
      motion: RidingTransitMotion.inTransit,
      nextPlace: place(
        '平井七丁目北公園前',
        35.708,
        139.840,
        stopId: 'bus-stop-2',
      ),
      predictedNextAvailableAt: predicted,
    );

    expect(
      observation.canResolveAnchorAt(DateTime(2026, 8, 15, 18, 5, 59)),
      isTrue,
    );
    expect(observation.canResolveAnchorAt(predicted), isTrue);
    expect(
      observation.canResolveAnchorAt(DateTime(2026, 8, 15, 18, 6, 1)),
      isFalse,
    );
  });

  test('stopped observation remains actionable as time advances', () {
    final observation = RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.stopped,
      currentPlace: place('浅草橋', 35.697, 139.785),
    );

    expect(observation.canResolveAnchorAt(now.add(const Duration(hours: 1))), isTrue);
  });

  test('transfer walk uses the last confirmed station instead of GPS', () {
    final anchor = ReplanAnchorResolver.resolve(
      context: ReplanAnchorContext(
        lastConfirmedTransitPlace: place('東日本橋', 35.692, 139.785),
      ),
      now: now,
    );

    expect(anchor.placeName, '東日本橋');
    expect(anchor.availableAt, now);
    expect(anchor.source, ReplanAnchorSource.lastConfirmedTransitPlace);
  });

  test('initial preboarding walk uses original trip origin', () {
    final anchor = ReplanAnchorResolver.resolve(
      context: ReplanAnchorContext(
        tripOrigin: place('自宅', 35.710, 139.840),
        isInitialPreboardingWalk: true,
      ),
      now: now,
    );

    expect(anchor.placeName, '自宅');
    expect(anchor.availableAt, now);
    expect(anchor.source, ReplanAnchorSource.tripOrigin);
  });

  test('in-transit anchor fails fast without predicted arrival', () {
    expect(
      () => RidingTransitObservation(
        stepId: 'rail-1',
        motion: RidingTransitMotion.inTransit,
        nextPlace: place('蔵前', 35.703, 139.790),
      ),
      throwsArgumentError,
    );
  });

  test('resolver never falls back when no transit place is known', () {
    expect(
      () => ReplanAnchorResolver.resolve(
        context: const ReplanAnchorContext(),
        now: now,
      ),
      throwsStateError,
    );
  });

  test('stale predicted arrival fails instead of being coerced to now', () {
    final stalePrediction = DateTime(2026, 8, 15, 18, 3);
    expect(
      () => ReplanAnchorResolver.resolve(
        context: ReplanAnchorContext(
          ridingTransit: RidingTransitObservation(
            stepId: 'rail-1',
            motion: RidingTransitMotion.inTransit,
            nextPlace: place('蔵前', 35.703, 139.790),
            predictedNextAvailableAt: stalePrediction,
          ),
        ),
        now: now,
      ),
      throwsStateError,
    );
  });
}

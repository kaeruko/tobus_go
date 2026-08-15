import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/logic/replan_transit_memory.dart';

void main() {
  ReplanTransitPlace place(String name, double lat, double lon) {
    return ReplanTransitPlace(name: name, point: LatLng(lat, lon));
  }

  test('ride observation updates the last confirmed transit place', () {
    final current = place('浅草橋', 35.697, 139.785);
    final next = place('蔵前', 35.703, 139.790);
    final observation = RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.inTransit,
      currentPlace: current,
      nextPlace: next,
      predictedNextAvailableAt: DateTime(2026, 8, 15, 18, 6),
    );

    final memory = const ReplanTransitMemory().observeRide(observation);

    expect(memory.ridingTransit, same(observation));
    expect(memory.lastConfirmedTransitPlace, same(current));
  });

  test('clearing active ride keeps the last confirmed station for walking', () {
    final current = place('東日本橋', 35.692, 139.785);
    final observation = RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.stopped,
      currentPlace: current,
    );
    final riding = const ReplanTransitMemory().observeRide(observation);

    final walking = riding.clearActiveRide();

    expect(walking.ridingTransit, isNull);
    expect(walking.lastConfirmedTransitPlace, same(current));
  });

  test('arrival replaces the confirmed place with the alighting stop', () {
    final previous = place('浅草橋', 35.697, 139.785);
    final destination = place('東日本橋', 35.692, 139.785);
    final observation = RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.stopped,
      currentPlace: previous,
    );
    final riding = const ReplanTransitMemory().observeRide(observation);

    final arrived = riding.markArrived(destination);

    expect(arrived.ridingTransit, isNull);
    expect(arrived.lastConfirmedTransitPlace, same(destination));
  });

  test('memory fails fast when a ride observation has no confirmed current place', () {
    final next = place('蔵前', 35.703, 139.790);
    final observation = RidingTransitObservation(
      stepId: 'rail-1',
      motion: RidingTransitMotion.inTransit,
      nextPlace: next,
      predictedNextAvailableAt: DateTime(2026, 8, 15, 18, 6),
    );

    expect(
      () => const ReplanTransitMemory().observeRide(observation),
      throwsStateError,
    );
  });
}

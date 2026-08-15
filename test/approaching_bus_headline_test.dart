import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/trip_navigator.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  group('approaching bus headline', () {
    test('shows route name and number of stops before boarding', () {
      final step = StepSeg(
        stepId: 'bus-1',
        kind: 'bus',
        title: '上23 上野松坂屋前行',
        fromName: '十間橋',
        toName: '本所吾妻橋',
        stops: [
          StopPoint(
            name: '十間橋',
            point: const LatLng(35.0, 139.0),
            stopId: 'boarding-stop',
            isOrigin: true,
          ),
          StopPoint(
            name: '本所吾妻橋',
            point: const LatLng(35.1, 139.1),
            stopId: 'destination-stop',
            isDestination: true,
          ),
        ],
      );
      const progress = BusProgress(
        stepId: 'bus-1',
        fromStopId: 'previous-stop',
        fromStopIndex: null,
        nextStopId: 'boarding-stop',
        nextStopIndex: 0,
        stopsUntilBoarding: 1,
        phase: BusProgressPhase.approaching,
      );

      final navigation = NavigationState.navigating(
        step: step,
        busProgress: progress,
      );

      expect(navigation.mainText, '上23 1停留所前');
      expect(navigation.subText, 'いま:十間橋');
      expect(navigation.statusLabel, '乗車待ち');
    });

    test('fails fast when approaching progress has no stop count', () {
      final step = StepSeg(
        stepId: 'bus-1',
        kind: 'bus',
        title: '上23 上野松坂屋前行',
        fromName: '十間橋',
        toName: '本所吾妻橋',
        stops: [
          StopPoint(
            name: '十間橋',
            point: const LatLng(35.0, 139.0),
            stopId: 'boarding-stop',
            isOrigin: true,
          ),
          StopPoint(
            name: '本所吾妻橋',
            point: const LatLng(35.1, 139.1),
            stopId: 'destination-stop',
            isDestination: true,
          ),
        ],
      );
      const progress = BusProgress(
        stepId: 'bus-1',
        fromStopId: 'previous-stop',
        fromStopIndex: null,
        nextStopId: 'boarding-stop',
        nextStopIndex: 0,
        phase: BusProgressPhase.approaching,
      );

      expect(
        () => NavigationState.navigating(
          step: step,
          busProgress: progress,
        ),
        throwsStateError,
      );
    });
  });
}

import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/ride_navigation_progress.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/rail_progress.dart';
import 'package:toeigo/models/route_models.dart';

void main() {
  test('bus and rail riding progress normalize to the same display fields', () {
    final busStep = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '上23 上野松坂屋前行',
      fromName: '平井七丁目',
      toName: '押上',
      arrivalTime: '15:54',
      stops: [
        StopPoint(
          name: '平井七丁目',
          point: const LatLng(35, 139),
          stopId: 'b0',
        ),
        StopPoint(
          name: '平井七丁目北公園前',
          point: const LatLng(35.01, 139.01),
          stopId: 'b1',
        ),
        StopPoint(
          name: '押上',
          point: const LatLng(35.02, 139.02),
          stopId: 'b2',
        ),
      ],
    );
    final bus = RideNavigationProgress.fromBus(
      step: busStep,
      progress: const BusProgress(
        stepId: 'bus-1',
        fromStopId: 'b1',
        fromStopIndex: 1,
        nextStopId: 'b2',
        nextStopIndex: 2,
        phase: BusProgressPhase.riding,
      ),
    );

    const rail = RideNavigationProgress(
      stepId: 'rail-1',
      phase: RideNavigationPhase.riding,
      rideTitle: '浅草線 青砥行',
      currentPlaceName: '浅草橋',
      nextPlaceName: '東日本橋',
      remainingStops: 1,
    );

    expect(bus.phase, rail.phase);
    expect(bus.remainingStops, rail.remainingStops);
    expect(bus.rideTitle, '上23 上野松坂屋前行');
    expect(bus.currentPlaceName, '平井七丁目北公園前');
    expect(bus.nextPlaceName, '押上');
  });

  test('rail adapter adds 行 to GTFS trip headsign', () {
    const progress = RailProgress(
      stepId: 'rail-1',
      tripId: '121603T0',
      tripHeadsign: '青砥',
      phase: RailProgressPhase.riding,
      boardingSequence: 9,
      destinationSequence: 11,
      lastReachedSequence: 9,
      remainingStops: 2,
      currentStopName: '東日本橋',
      nextStopName: '浅草橋',
      currentStatus: 'IN_TRANSIT_TO',
    );
    final step = StepSeg(
      stepId: 'rail-1',
      kind: 'rail',
      title: '浅草線',
      fromName: '東日本橋',
      toName: '蔵前',
      arrivalTime: '16:24',
    );

    final normalized = RideNavigationProgress.fromRail(
      step: step,
      progress: progress,
    );

    expect(normalized.phase, RideNavigationPhase.riding);
    expect(normalized.rideTitle, '浅草線 青砥行');
    expect(normalized.currentPlaceName, '東日本橋');
    expect(normalized.nextPlaceName, '浅草橋');
    expect(normalized.remainingStops, 2);
  });

  test('rail adapter does not duplicate 行 already present in headsign', () {
    const progress = RailProgress(
      stepId: 'rail-1',
      tripId: '121603T0',
      tripHeadsign: '青砥行',
      phase: RailProgressPhase.riding,
      boardingSequence: 9,
      destinationSequence: 11,
      lastReachedSequence: 9,
      remainingStops: 2,
      currentStopName: '東日本橋',
      nextStopName: '浅草橋',
      currentStatus: 'IN_TRANSIT_TO',
    );
    final step = StepSeg(
      stepId: 'rail-1',
      kind: 'rail',
      title: '浅草線',
      fromName: '東日本橋',
      toName: '蔵前',
      arrivalTime: '16:24',
    );

    final normalized = RideNavigationProgress.fromRail(
      step: step,
      progress: progress,
    );

    expect(normalized.rideTitle, '浅草線 青砥行');
  });
}

import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/logic/replan_transit_observation.dart';
import 'package:toeigo/models/bus_progress.dart';
import 'package:toeigo/models/rail_progress.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/services/bus_location_source.dart';
import 'package:toeigo/services/train_location_source.dart';

void main() {
  int epochSeconds(DateTime value) => value.millisecondsSinceEpoch ~/ 1000;

  group('bus realtime observation', () {
    final step = StepSeg(
      stepId: 'bus-1',
      kind: 'bus',
      title: '上23 上野松坂屋前行',
      routeId: '070',
      tripId: 'trip-bus',
      stops: [
        StopPoint(
          name: '平井七丁目',
          point: const LatLng(35.706, 139.842),
          stopId: '1350-02',
        ),
        StopPoint(
          name: '平井七丁目北公園前',
          point: const LatLng(35.708, 139.840),
          stopId: '1349-01',
        ),
        StopPoint(
          name: '社会福祉会館前',
          point: const LatLng(35.710, 139.838),
          stopId: '0665-01',
        ),
      ],
    );

    BusLocation movingLocation({required DateTime vehicleAt}) => BusLocation(
      vehicleId: 'bus-v1',
      fromStopId: '1350-02',
      routeId: '070',
      tripId: 'trip-bus',
      tripStopIds: const ['1350-02', '1349-01', '0665-01'],
      rawStopId: '1349-01',
      rawStopName: '平井七丁目北公園前',
      fromStopSequence: 1,
      observedStopSequence: 2,
      currentStatus: 'IN_TRANSIT_TO',
      vehicleTimestamp: epochSeconds(vehicleAt),
      tripStopSchedule: const [
        BusStopSchedule(
          sequence: 1,
          stopId: '1350-02',
          stopName: '平井七丁目',
          arrivalMinute: 18 * 60 + 4,
          departureMinute: 18 * 60 + 4,
          arrivalTime: '18:04',
          departureTime: '18:04',
        ),
        BusStopSchedule(
          sequence: 2,
          stopId: '1349-01',
          stopName: '平井七丁目北公園前',
          arrivalMinute: 18 * 60 + 7,
          departureMinute: 18 * 60 + 7,
          arrivalTime: '18:07',
          departureTime: '18:07',
        ),
        BusStopSchedule(
          sequence: 3,
          stopId: '0665-01',
          stopName: '社会福祉会館前',
          arrivalMinute: 18 * 60 + 11,
          departureMinute: 18 * 60 + 11,
          arrivalTime: '18:11',
          departureTime: '18:11',
        ),
      ],
    );

    test('moving bus uses next stop and sample + scheduled segment duration', () {
      final vehicleAt = DateTime.utc(2026, 8, 15, 9, 4);
      final now = DateTime.utc(2026, 8, 15, 9, 4, 30);
      final location = movingLocation(vehicleAt: vehicleAt);
      final progress = BusProgress.forStep(
        step: step,
        fromStopId: location.fromStopId,
        tripStopIds: location.tripStopIds,
        observedStopId: location.rawStopId,
        observedStopName: location.rawStopName,
        currentStatus: location.currentStatus,
      );

      final observation = ReplanTransitObservationAdapter.fromBus(
        step: step,
        progress: progress,
        location: location,
        now: now,
      );

      expect(observation.motion, RidingTransitMotion.inTransit);
      expect(observation.currentPlace?.name, '平井七丁目');
      expect(observation.nextPlace?.name, '平井七丁目北公園前');
      expect(observation.nextPlace?.stopId, '1349-01');
      expect(
        observation.predictedNextAvailableAt,
        vehicleAt.add(const Duration(minutes: 3)),
      );
      expect(
        observation.predictedDestinationAvailableAt,
        vehicleAt.add(const Duration(minutes: 7)),
      );
    });

    test('stopped bus uses the current stop without an arrival prediction', () {
      final location = BusLocation(
        vehicleId: 'bus-v1',
        fromStopId: '1349-01',
        routeId: '070',
        tripId: 'trip-bus',
        tripStopIds: const ['1350-02', '1349-01', '0665-01'],
        rawStopId: '1349-01',
        rawStopName: '平井七丁目北公園前',
        fromStopSequence: 2,
        observedStopSequence: 2,
        currentStatus: 'STOPPED_AT',
        tripStopSchedule: movingLocation(
          vehicleAt: DateTime.utc(2026, 8, 15, 9, 4),
        ).tripStopSchedule,
      );
      final progress = BusProgress.forStep(
        step: step,
        fromStopId: location.fromStopId,
        tripStopIds: location.tripStopIds,
        observedStopId: location.rawStopId,
        observedStopName: location.rawStopName,
        currentStatus: location.currentStatus,
      );

      final observation = ReplanTransitObservationAdapter.fromBus(
        step: step,
        progress: progress,
        location: location,
        now: DateTime.utc(2026, 8, 15, 9, 7),
      );

      expect(observation.motion, RidingTransitMotion.stopped);
      expect(observation.currentPlace?.name, '平井七丁目北公園前');
      expect(observation.predictedNextAvailableAt, isNull);
      expect(observation.predictedDestinationAvailableAt, isNull);
    });

    test('expired moving bus forecast is treated as realtime unavailable', () {
      final now = DateTime.utc(2026, 8, 15, 9, 10);
      final location = movingLocation(
        vehicleAt: DateTime.utc(2026, 8, 15, 9, 4),
      );
      final progress = BusProgress.forStep(
        step: step,
        fromStopId: location.fromStopId,
        tripStopIds: location.tripStopIds,
        observedStopId: location.rawStopId,
        observedStopName: location.rawStopName,
        currentStatus: location.currentStatus,
      );

      expect(
        () => ReplanTransitObservationAdapter.fromBus(
          step: step,
          progress: progress,
          location: location,
          now: now,
        ),
        throwsA(
          isA<BusLocationNotAvailableException>().having(
            (error) => error.code,
            'code',
            'bus_realtime_prediction_expired',
          ),
        ),
      );
    });
  });

  group('rail realtime observation', () {
    final step = StepSeg(
      stepId: 'rail-1',
      kind: 'rail',
      title: '浅草線',
      fromName: '東日本橋',
      toName: '蔵前',
      stops: [
        StopPoint(
          name: '東日本橋',
          point: const LatLng(35.692, 139.785),
          stopId: 'odpt.Station:Toei.Asakusa.HigashiNihombashi',
        ),
        StopPoint(
          name: '浅草橋',
          point: const LatLng(35.697, 139.785),
          stopId: 'odpt.Station:Toei.Asakusa.Asakusabashi',
        ),
        StopPoint(
          name: '蔵前',
          point: const LatLng(35.703, 139.790),
          stopId: 'odpt.Station:Toei.Asakusa.Kuramae',
        ),
      ],
    );

    const tripStops = <TrainTripStop>[
      TrainTripStop(
        sequence: 9,
        stopId: '115',
        stopName: '東日本橋',
        arrivalTime: '18:02:00',
        departureTime: '18:02:30',
      ),
      TrainTripStop(
        sequence: 10,
        stopId: '116',
        stopName: '浅草橋',
        arrivalTime: '18:04:00',
        departureTime: '18:04:30',
      ),
      TrainTripStop(
        sequence: 11,
        stopId: '117',
        stopName: '蔵前',
        arrivalTime: '18:06:00',
        departureTime: '18:06:30',
      ),
    ];

    TrainLocation movingTrain({required DateTime vehicleAt}) => TrainLocation(
      tripId: '121603T0',
      routeId: '1',
      tripHeadsign: '成田空港',
      vehicleId: '121603T0',
      currentStopSequence: 11,
      currentStatus: 'IN_TRANSIT_TO',
      currentStopId: '117',
      currentStopName: '蔵前',
      boardingSequence: 9,
      destinationSequence: 11,
      vehicleTimestamp: epochSeconds(vehicleAt),
      tripStops: tripStops,
    );

    test('moving train uses target station and exact scheduled segment seconds', () {
      final vehicleAt = DateTime.utc(2026, 8, 15, 9, 4, 45);
      final location = movingTrain(vehicleAt: vehicleAt);
      final progress = RailProgress.forLocation(
        stepId: step.stepId,
        location: location,
      );

      final observation = ReplanTransitObservationAdapter.fromRail(
        step: step,
        progress: progress,
        location: location,
        now: DateTime.utc(2026, 8, 15, 9, 5),
      );

      expect(observation.motion, RidingTransitMotion.inTransit);
      expect(observation.currentPlace?.name, '浅草橋');
      expect(observation.nextPlace?.name, '蔵前');
      expect(
        observation.predictedNextAvailableAt,
        vehicleAt.add(const Duration(seconds: 90)),
      );
      expect(
        observation.predictedDestinationAvailableAt,
        vehicleAt.add(const Duration(seconds: 90)),
      );
    });

    test('stopped train uses current station', () {
      final location = TrainLocation(
        tripId: '121603T0',
        routeId: '1',
        tripHeadsign: '成田空港',
        vehicleId: '121603T0',
        currentStopSequence: 10,
        currentStatus: 'STOPPED_AT',
        currentStopId: '116',
        currentStopName: '浅草橋',
        boardingSequence: 9,
        destinationSequence: 11,
        tripStops: tripStops,
      );
      final progress = RailProgress.forLocation(
        stepId: step.stepId,
        location: location,
      );

      final observation = ReplanTransitObservationAdapter.fromRail(
        step: step,
        progress: progress,
        location: location,
        now: DateTime.utc(2026, 8, 15, 9, 4),
      );

      expect(observation.motion, RidingTransitMotion.stopped);
      expect(observation.currentPlace?.name, '浅草橋');
      expect(observation.currentPlace?.point.latitude, 35.697);
      expect(observation.predictedNextAvailableAt, isNull);
      expect(observation.predictedDestinationAvailableAt, isNull);
    });

    test('expired moving train forecast is treated as realtime unavailable', () {
      final location = movingTrain(
        vehicleAt: DateTime.utc(2026, 8, 15, 9, 4, 45),
      );
      final progress = RailProgress.forLocation(
        stepId: step.stepId,
        location: location,
      );

      expect(
        () => ReplanTransitObservationAdapter.fromRail(
          step: step,
          progress: progress,
          location: location,
          now: DateTime.utc(2026, 8, 15, 9, 7),
        ),
        throwsA(
          isA<TrainLocationNotAvailableException>().having(
            (error) => error.code,
            'code',
            'rail_realtime_prediction_expired',
          ),
        ),
      );
    });
  });
}

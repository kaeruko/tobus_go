import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';

Candidate navigationV2Candidate() {
  return Candidate(
    id: 'navigation-v2-fixture',
    lines: const ['上23'],
    rides: 1,
    walks: 2,
    boards: 1,
    transfers: 0,
    total: 51,
    totalTime: 51,
    points: const [],
    originName: '自宅',
    destinationName: '目的地',
    departureDate: DateTime(2025, 1, 1, 10),
    steps: [
      StepSeg(
        stepId: 'walk-A',
        kind: 'walk',
        title: '徒歩',
        fromName: '自宅',
        toName: '平井七丁目',
        minutes: 4,
        departureTime: '10:00',
        arrivalTime: '10:04',
      ),
      StepSeg(
        stepId: 'wait-B',
        kind: 'wait',
        title: '待ち時間',
        fromName: '平井七丁目',
        toName: '平井七丁目',
        minutes: 0,
        departureTime: '10:04',
        arrivalTime: '10:04',
      ),
      StepSeg(
        stepId: 'bus-C',
        kind: 'bus',
        title: '上23',
        fromName: '平井七丁目',
        toName: '押上',
        minutes: 42,
        departureTime: '10:04',
        arrivalTime: '10:46',
        routeId: 'route-kami23',
        tripId: 'trip-kami23-1004',
        stops: [
          StopPoint(
            name: '平井七丁目',
            point: const LatLng(35.1, 139.1),
            stopId: 'stop-0',
            isOrigin: true,
          ),
          StopPoint(
            name: '中間一',
            point: const LatLng(35.2, 139.2),
            stopId: 'stop-1',
          ),
          StopPoint(
            name: '中間二',
            point: const LatLng(35.3, 139.3),
            stopId: 'stop-2',
          ),
          StopPoint(
            name: '押上',
            point: const LatLng(35.4, 139.4),
            stopId: 'stop-3',
            isDestination: true,
          ),
        ],
      ),
      StepSeg(
        stepId: 'walk-D',
        kind: 'walk',
        title: '徒歩',
        fromName: '押上',
        toName: '目的地',
        minutes: 5,
        departureTime: '10:46',
        arrivalTime: '10:51',
      ),
    ],
  );
}

Trip navigationV2Trip() {
  final candidate = navigationV2Candidate();
  return Trip(
    id: 'trip-v2',
    joinCode: '123456',
    leaderId: 'leader',
    title: 'Navigation v2 fixture',
    travelPhase: TravelPhase.active,
    date: DateTime(2025, 1, 1),
    plannedDepartureAt: DateTime(2025, 1, 1, 10),
    actualDepartureAt: null,
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: candidate,
      ),
    ],
    schedule: const [],
    participants: const [],
    memberIds: const [],
  );
}

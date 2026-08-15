import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:toeigo/logic/replan_anchor.dart';
import 'package:toeigo/logic/route_replan_patcher.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/services/route_replanner.dart';

void main() {
  final date = DateTime(2026, 8, 15);

  StepSeg walk({
    required String id,
    required String from,
    required String to,
    required String departure,
    required String arrival,
    int minutes = 5,
  }) {
    return StepSeg(
      stepId: id,
      kind: 'walk',
      title: '徒歩',
      fromName: from,
      toName: to,
      departureTime: departure,
      arrivalTime: arrival,
      minutes: minutes,
    );
  }

  StepSeg rail({
    required String id,
    required String from,
    required String to,
    required String departure,
    required String arrival,
    required List<StopPoint> stops,
  }) {
    return StepSeg(
      stepId: id,
      kind: 'rail',
      title: '浅草線 青砥行',
      fromName: from,
      toName: to,
      departureTime: departure,
      arrivalTime: arrival,
      minutes: 15,
      routeId: 'asakusa',
      tripId: 'train-1',
      stops: stops,
    );
  }

  final originalStops = [
    StopPoint(
      name: '本所吾妻橋',
      point: const LatLng(35.708, 139.804),
      stopId: 's0',
      isOrigin: true,
    ),
    StopPoint(
      name: '浅草橋',
      point: const LatLng(35.697, 139.785),
      stopId: 's1',
    ),
    StopPoint(
      name: '東日本橋',
      point: const LatLng(35.692, 139.785),
      stopId: 's2',
      isDestination: true,
    ),
  ];

  Candidate originalCandidate() {
    return Candidate(
      id: 'original',
      lines: const ['浅草線'],
      rides: 1,
      walks: 2,
      boards: 1,
      transfers: 0,
      total: 25,
      totalTime: 25,
      steps: [
        walk(
          id: 'old-walk-in',
          from: '自宅',
          to: '本所吾妻橋',
          departure: '10:00',
          arrival: '10:05',
        ),
        rail(
          id: 'old-rail',
          from: '本所吾妻橋',
          to: '東日本橋',
          departure: '10:05',
          arrival: '10:20',
          stops: originalStops,
        ),
        walk(
          id: 'old-walk-out',
          from: '東日本橋',
          to: '目的地',
          departure: '10:20',
          arrival: '10:25',
        ),
      ],
      points: const [],
      originName: '自宅',
      destinationName: '目的地',
      originCoords: const LatLng(35.710, 139.840),
      destinationCoords: const LatLng(35.680, 139.770),
      departureDate: DateTime(2026, 8, 15, 10),
      arrivalTime: '10:25',
      preference: 'shortTime',
    );
  }

  Candidate selectedCandidate({String firstStepId = 'new-walk'}) {
    return Candidate(
      id: 'selected',
      lines: const ['新宿線'],
      rides: 1,
      walks: 1,
      boards: 1,
      transfers: 0,
      total: 18,
      totalTime: 18,
      steps: [
        walk(
          id: firstStepId,
          from: '浅草橋',
          to: '馬喰横山',
          departure: '10:12',
          arrival: '10:14',
          minutes: 2,
        ),
        StepSeg(
          stepId: 'new-rail',
          kind: 'rail',
          title: '新宿線 本八幡行',
          fromName: '馬喰横山',
          toName: '目的地最寄り',
          departureTime: '10:16',
          arrivalTime: '10:30',
          minutes: 14,
          routeId: 'shinjuku',
          tripId: 'train-2',
          stops: [
            StopPoint(
              name: '馬喰横山',
              point: const LatLng(35.692, 139.783),
              stopId: 'n0',
              isOrigin: true,
            ),
            StopPoint(
              name: '目的地最寄り',
              point: const LatLng(35.681, 139.771),
              stopId: 'n1',
              isDestination: true,
            ),
          ],
        ),
      ],
      points: const [],
      originName: '浅草橋',
      destinationName: '目的地',
      originCoords: const LatLng(35.697, 139.785),
      destinationCoords: const LatLng(35.680, 139.770),
      departureDate: DateTime(2026, 8, 15, 10, 12),
      arrivalTime: '10:30',
      preference: 'shortTime',
    );
  }

  Trip trip({List<ScheduleEntry>? extraSchedule}) {
    final candidate = originalCandidate();
    final schedule = createScheduleFromRoute(
      candidate,
      startDateTime: DateTime(2026, 8, 15, 10),
      legIndex: 0,
    );
    if (extraSchedule != null) schedule.addAll(extraSchedule);
    sortScheduleEntries(schedule);
    return Trip(
      tripType: TripType.solo,
      id: 'solo-1',
      joinCode: '',
      leaderId: 'user-1',
      title: '自宅 → 目的地',
      travelPhase: TravelPhase.active,
      date: date,
      plannedDepartureAt: null,
      actualDepartureAt: DateTime(2026, 8, 15, 10),
      legs: [
        Leg(
          direction: LegDirection.outbound,
          status: LegStatus.confirmed,
          candidate: candidate,
        ),
      ],
      schedule: schedule,
      participants: const [],
      memberIds: const ['user-1'],
    );
  }

  RouteReplanRequest movingRequest() {
    return RouteReplanRequest(
      anchor: ReplanAnchor(
        placeName: '浅草橋',
        stopId: 's1',
        point: const LatLng(35.697, 139.785),
        availableAt: DateTime(2026, 8, 15, 10, 12),
        source: ReplanAnchorSource.predictedNextTransitPlace,
        routeStepId: 'old-rail',
      ),
      activeStepId: 'old-rail',
      originalCandidateId: 'original',
      destination: const LatLng(35.680, 139.770),
      destinationName: '目的地',
      preference: 'shortTime',
    );
  }

  test('moving ride is split at predicted anchor and future route is replaced', () {
    final patch = RouteReplanPatcher.build(
      trip: trip(),
      request: movingRequest(),
      selectedCandidate: selectedCandidate(),
    );

    final combined = patch.legs.single.candidate;
    expect(
      combined.steps.map((step) => step.stepId),
      ['old-walk-in', 'old-rail', 'new-walk', 'new-rail'],
    );
    final oldRail = combined.steps[1];
    expect(oldRail.toName, '浅草橋');
    expect(oldRail.arrivalTime, '10:12');
    expect(oldRail.minutes, 7);
    expect(oldRail.stops.map((stop) => stop.name), ['本所吾妻橋', '浅草橋']);
    expect(oldRail.stops.last.isDestination, isTrue);
    expect(combined.arrivalTime, '10:30');

    expect(
      patch.schedule.any((entry) => entry.routeStepId == 'old-walk-out'),
      isFalse,
    );
    expect(
      patch.schedule.any((entry) => entry.routeStepId == 'new-walk'),
      isTrue,
    );
    final splitArrival = patch.schedule.singleWhere(
      (entry) =>
          entry.routeStepId == 'old-rail' && entry.routeRole == 'arrival',
    );
    expect(splitArrival.plannedAt, DateTime(2026, 8, 15, 10, 12));
    expect(splitArrival.label, contains('浅草橋に着く'));
  });

  test('manual entries are preserved without shifting', () {
    final manualAt = DateTime(2026, 8, 15, 10, 22);
    final manual = ScheduleEntry(
      id: 'manual-break',
      plannedAt: manualAt,
      label: '休憩開始',
      itemKind: ScheduleEntryKind.event,
      legIndex: 0,
      generatedBy: ScheduleEntrySource.manual,
    );

    final patch = RouteReplanPatcher.build(
      trip: trip(extraSchedule: [manual]),
      request: movingRequest(),
      selectedCandidate: selectedCandidate(),
    );

    final retained = patch.schedule.singleWhere(
      (entry) => entry.id == 'manual-break',
    );
    expect(retained.plannedAt, manualAt);
    expect(retained.label, '休憩開始');
  });

  test('walking after alighting keeps prior transit and drops active old walk', () {
    final request = RouteReplanRequest(
      anchor: ReplanAnchor(
        placeName: '東日本橋',
        stopId: 's2',
        point: const LatLng(35.692, 139.785),
        availableAt: DateTime(2026, 8, 15, 10, 23),
        source: ReplanAnchorSource.lastConfirmedTransitPlace,
      ),
      activeStepId: 'old-walk-out',
      originalCandidateId: 'original',
      destination: const LatLng(35.680, 139.770),
      destinationName: '目的地',
      preference: 'shortTime',
    );

    final patch = RouteReplanPatcher.build(
      trip: trip(),
      request: request,
      selectedCandidate: selectedCandidate(),
    );

    expect(
      patch.legs.single.candidate.steps.map((step) => step.stepId),
      ['old-walk-in', 'old-rail', 'new-walk', 'new-rail'],
    );
    expect(
      patch.schedule.any((entry) => entry.routeStepId == 'old-walk-out'),
      isFalse,
    );
  });

  test('trip-origin replan replaces all route-generated steps', () {
    final request = RouteReplanRequest(
      anchor: ReplanAnchor(
        placeName: '自宅',
        stopId: null,
        point: const LatLng(35.710, 139.840),
        availableAt: DateTime(2026, 8, 15, 10, 1),
        source: ReplanAnchorSource.tripOrigin,
      ),
      activeStepId: 'old-walk-in',
      originalCandidateId: 'original',
      destination: const LatLng(35.680, 139.770),
      destinationName: '目的地',
      preference: 'shortTime',
    );

    final patch = RouteReplanPatcher.build(
      trip: trip(),
      request: request,
      selectedCandidate: selectedCandidate(),
    );

    expect(
      patch.legs.single.candidate.steps.map((step) => step.stepId),
      ['new-walk', 'new-rail'],
    );
    expect(
      patch.schedule.any((entry) => entry.routeStepId == 'old-walk-in'),
      isFalse,
    );
  });

  test('duplicate selected step ID fails before persistence', () {
    expect(
      () => RouteReplanPatcher.build(
        trip: trip(),
        request: movingRequest(),
        selectedCandidate: selectedCandidate(firstStepId: 'old-rail'),
      ),
      throwsStateError,
    );
  });
}

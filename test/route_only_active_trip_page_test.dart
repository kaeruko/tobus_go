import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toei_go/models/route_models.dart';
import 'package:toei_go/pages/route_only_active_trip_page.dart';
import 'package:toei_go/services/bus_location_source.dart';

class _BeforeFirstStopSource implements BusLocationSource {
  @override
  Future<BusLocation> fetch({
    required String routeId,
    required String tripId,
    String? vehicleId,
    bool forceRefresh = false,
  }) async {
    return BusLocation(
      vehicleId: '1772',
      fromStopId: null,
      routeId: routeId,
      tripId: tripId,
      vehicleLat: 35.466,
      vehicleLon: 139.622,
      beforeFirstStop: true,
      rawStopId: 'A',
      rawStopName: '横浜駅前',
      fromStopSequence: null,
      observedStopSequence: 1,
      currentStatus: 'IN_TRANSIT_TO',
      serverNow: '2026-08-30T05:00:00Z',
    );
  }
}

void main() {
  testWidgets('route-only trip uses shared source for before-first-stop state', (
    tester,
  ) async {
    final candidate = Candidate(
      id: 'route-1',
      lines: const ['008'],
      rides: 1,
      walks: 0,
      boards: 1,
      transfers: 0,
      total: 20,
      totalTime: 20,
      points: const [],
      steps: [
        StepSeg(
          stepId: 'bus-1',
          kind: 'bus',
          title: '008系統',
          fromName: '横浜駅前',
          toName: '山下公園前',
          routeId: 'yokohama_bus:008',
          tripId: 'yokohama_bus:T1',
        ),
      ],
    );

    await tester.pumpWidget(
      CupertinoApp(
        home: RouteOnlyActiveTripPage(
          candidate: candidate,
          busLocationSource: _BeforeFirstStopSource(),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('車両 1772'), findsOneWidget);
    expect(find.text('バスは始発停留所へ向かっています'), findsOneWidget);
    expect(find.text('始発停留所: 横浜駅前'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}

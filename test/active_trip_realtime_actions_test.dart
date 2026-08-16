import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:toeigo/providers/member_mode_provider.dart';
import 'package:toeigo/services/bus_location_source.dart';
import 'package:toeigo/widgets/active_trip_realtime_actions.dart';

void main() {
  testWidgets('通常Realtimeでは更新ボタンだけを表示する', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          busLocationSourceProvider.overrideWithValue(
            const RealtimeBusLocationSource(),
          ),
        ],
        child: const MaterialApp(
          home: Scaffold(
            body: ActiveTripRealtimeActions(),
          ),
        ),
      ),
    );

    expect(find.byTooltip('現在地を更新'), findsOneWidget);
    expect(find.byTooltip('Fakeバスを次の停留所へ'), findsNothing);
  });

  testWidgets('FakeBusでは共通デバッグ操作も表示する', (tester) async {
    final fake = FakeBusLocationSource([
      const BusLocation(
        vehicleId: 'vehicle-1',
        fromStopId: 'stop-1',
        routeId: 'route-1',
        tripId: 'trip-1',
      ),
    ]);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [busLocationSourceProvider.overrideWithValue(fake)],
        child: const MaterialApp(
          home: Scaffold(
            body: ActiveTripRealtimeActions(),
          ),
        ),
      ),
    );

    expect(find.byTooltip('現在地を更新'), findsOneWidget);
    expect(find.byTooltip('Fakeバスを次の停留所へ'), findsOneWidget);
  });
}

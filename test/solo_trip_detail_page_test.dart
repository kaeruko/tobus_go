import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart'
    as maps;

import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/group_models.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/pages/solo_trip_detail_page.dart';
import 'package:toeigo/providers/navigation_provider.dart';
import 'package:toeigo/providers/route_search_provider.dart';

class TestMaps extends maps.GoogleMapsFlutterPlatform {
  @override
  Widget buildViewWithConfiguration(
    int creationId,
    void Function(int) onPlatformViewCreated, {
    required maps.MapWidgetConfiguration widgetConfiguration,
    maps.MapConfiguration mapConfiguration = const maps.MapConfiguration(),
    maps.MapObjects mapObjects = const maps.MapObjects(),
  }) => const SizedBox();
}

void main() {
  setUp(() {
    final previous = maps.GoogleMapsFlutterPlatform.instance;
    maps.GoogleMapsFlutterPlatform.instance = TestMaps();
    addTearDown(() => maps.GoogleMapsFlutterPlatform.instance = previous);
  });

  final candidate = Candidate(
    id: 'detail-en',
    lines: const ['浅草線'],
    linesEn: const ['Asakusa Line'],
    rides: 1,
    boards: 1,
    transfers: 0,
    total: 16,
    totalTime: 16,
    points: const [
      LatLng(35.7100, 139.8130),
      LatLng(35.7138, 139.7773),
    ],
    originName: '押上',
    originNameEn: 'Oshiage',
    destinationName: '上野駅',
    destinationNameEn: 'Ueno Station',
    originCoords: const LatLng(35.7100, 139.8130),
    destinationCoords: const LatLng(35.7138, 139.7773),
    preference: 'fewTransfers',
    steps: [
      StepSeg(
        stepId: 'walk-1',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '押上',
        toName: '押上',
        toNameEn: 'Oshiage',
        minutes: 5,
      ),
      StepSeg(
        stepId: 'rail-1',
        kind: 'rail',
        title: '浅草線',
        titleEn: 'Asakusa Line',
        fromName: '押上',
        fromNameEn: 'Oshiage',
        toName: '蔵前',
        toNameEn: 'Kuramae',
        minutes: 5,
      ),
      StepSeg(
        stepId: 'walk-2',
        kind: 'walk',
        title: '徒歩',
        titleEn: 'Walk',
        fromName: '蔵前',
        fromNameEn: 'Kuramae',
        toName: '上野駅',
        minutes: 6,
      ),
    ],
  );

  final schedule = [
    ScheduleEntry(
      id: 'walk',
      plannedAt: DateTime(2026, 9, 27, 22, 3),
      label: '押上まで歩く (5分)',
      itemKind: ScheduleEntryKind.walk,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'walk-1',
      routeRole: 'walk',
    ),
    ScheduleEntry(
      id: 'ride',
      plannedAt: DateTime(2026, 9, 27, 22, 8),
      label: '🚇浅草線 押上に乗る',
      itemKind: ScheduleEntryKind.ride,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'rail-1',
      routeRole: 'ride',
    ),
    ScheduleEntry(
      id: 'arrival',
      plannedAt: DateTime(2026, 9, 27, 22, 13),
      label: '🚇浅草線 蔵前に着く',
      itemKind: ScheduleEntryKind.arrival,
      generatedBy: ScheduleEntrySource.route,
      routeStepId: 'rail-1',
      routeRole: 'arrival',
    ),
    ScheduleEntry(
      id: 'goal',
      plannedAt: DateTime(2026, 9, 27, 22, 19),
      label: '上野駅 到着',
      description: 'お疲れ様でした!',
      itemKind: ScheduleEntryKind.goal,
      legIndex: 0,
      generatedBy: ScheduleEntrySource.route,
    ),
  ];

  final trip = Trip(
    tripType: TripType.solo,
    id: 'detail-trip-en',
    joinCode: '',
    leaderId: 'user',
    title: '',
    travelPhase: TravelPhase.completed,
    date: DateTime(2026, 9, 27),
    plannedDepartureAt: DateTime(2026, 9, 27, 22, 3),
    actualDepartureAt: DateTime(2026, 9, 27, 22, 3),
    legs: [
      Leg(
        direction: LegDirection.outbound,
        status: LegStatus.confirmed,
        candidate: candidate,
      ),
    ],
    schedule: schedule,
    participants: const [],
    memberIds: const ['user'],
  );

  testWidgets('English solo trip detail localizes the full route history', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(900, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          locale: const Locale('en'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: SoloTripDetailPage(trip: trip),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Trip details'), findsOneWidget);
    expect(
      find.text('Oshiage (押上) → Ueno Station (上野駅)'),
      findsOneWidget,
    );
    expect(find.text('2026/9/27 · Completed'), findsOneWidget);
    expect(find.text('Route & schedule'), findsOneWidget);
    expect(find.byType(GoogleMap), findsOneWidget);
    expect(find.text('Walk to Oshiage (押上) (5 min)'), findsOneWidget);
    expect(
      find.text('Asakusa Line · Board at Oshiage (押上)'),
      findsOneWidget,
    );
    expect(
      find.text('Asakusa Line · Arrive at Kuramae (蔵前)'),
      findsOneWidget,
    );
    expect(
      find.text('Arrive at Ueno Station (上野駅)'),
      findsOneWidget,
    );
    expect(find.text('Thanks for traveling with us'), findsOneWidget);

    final planButton = find.byKey(
      const ValueKey('history-plan-route-button'),
    );
    await tester.scrollUntilVisible(
      planButton,
      300,
      scrollable: find.byType(Scrollable),
    );
    await tester.pumpAndSettle();
    expect(find.text('Plan a trip with this route'), findsOneWidget);

    final context = tester.element(find.byType(SoloTripDetailPage));
    final container = ProviderScope.containerOf(context);
    await tester.tap(planButton);
    await tester.pump();

    final search = container.read(routeSearchProvider);
    expect(search.from, '35.71,139.813');
    expect(search.to, '35.7138,139.7773');
    expect(search.fromName, 'Oshiage');
    expect(search.toName, 'Ueno Station');
    expect(search.fromNameJa, '押上');
    expect(search.toNameJa, '上野駅');
    expect(search.fromNameEn, 'Oshiage');
    expect(search.toNameEn, 'Ueno Station');
    expect(search.pref, 'fewTransfers');
    expect(search.startTime, isNotNull);
    expect(search.hasSearched, isFalse);
    expect(container.read(tabIndexProvider), 0);

    expect(find.text('移動の詳細'), findsNothing);
    expect(find.text('経路と予定'), findsNothing);
    expect(find.text('上野駅 到着'), findsNothing);
    expect(find.text('お疲れ様でした!'), findsNothing);
  });
}

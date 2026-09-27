import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart'
    as maps;
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/logic/solo_trip_factory.dart';
import 'package:toeigo/models/leg_models.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/models/trip_models.dart';
import 'package:toeigo/pages/solo_trip_route_page.dart';
import 'package:toeigo/providers/trip_provider.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';
import 'package:toeigo/widgets/route_map_preview.dart';

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

Candidate route({
  String id = 'original',
  String arrival = '07:17',
  List<LatLng> points = const [
    LatLng(35.7, 139.8),
    LatLng(35.71, 139.81),
    LatLng(35.6, 139.7),
  ],
}) {
  StepSeg step(String id, String kind, String from, String fromEn,
      String to, String toEn, String departure, String arrival, int minutes) {
    return StepSeg(
      stepId: id,
      kind: kind,
      title: kind == 'bus' ? '上23 上野松坂屋前行' : kind == 'rail' ? '浅草線' : '',
      titleEn: kind == 'bus' ? 'Ueno-Matsuzakaya' : kind == 'rail' ? 'Asakusa Line' : '',
      fromName: from,
      fromNameEn: fromEn,
      toName: to,
      toNameEn: toEn,
      departureTime: departure,
      arrivalTime: arrival,
      minutes: minutes,
      meters: kind == 'walk' ? 178 : 0,
    );
  }

  return Candidate(
    id: id,
    lines: const ['上23 上野松坂屋前行', '浅草線'],
    linesEn: const ['Ueno-Matsuzakaya', 'Asakusa Line'],
    rides: 2,
    boards: 2,
    transfers: 1,
    total: 74,
    totalTime: 74,
    originName: '現在地',
    originNameEn: 'Current location',
    destinationName: '新橋駅',
    destinationNameEn: 'Shimbashi Station',
    departureDate: DateTime(2026, 9, 28, 6, 3),
    arrivalTime: arrival,
    points: points,
    steps: [
      step('wait', 'wait', '現在地', 'Current location', '現在地', 'Current location', '06:03', '06:28', 25),
      step('walk-in', 'walk', '現在地', 'Current location', '平井七丁目', 'Hirai-nanachome', '06:28', '06:31', 3),
      step('bus', 'bus', '平井七丁目', 'Hirai-nanachome', '本所吾妻橋', 'Honjo-azumabashi', '06:31', '06:54', 23),
      step('rail', 'rail', '本所吾妻橋', 'Honjo-azumabashi', '新橋', 'Shimbashi', '06:58', '07:14', 16),
      step('walk-out', 'walk', '新橋', 'Shimbashi', '新橋駅', 'Shimbashi Station', '07:14', arrival, 3),
    ],
  );
}

Trip trip(Candidate candidate) => buildSoloTrip(
  id: 'active-trip',
  userId: 'user',
  userName: 'User',
  candidate: candidate,
  now: DateTime(2026, 9, 28, 6, 5),
);

void main() {
  setUp(() {
    final previous = maps.GoogleMapsFlutterPlatform.instance;
    maps.GoogleMapsFlutterPlatform.instance = TestMaps();
    addTearDown(() => maps.GoogleMapsFlutterPlatform.instance = previous);
  });

  for (final language in ['ja', 'en']) {
    testWidgets('$language overview shows all route segments and live updates', (tester) async {
      tester.view.physicalSize = const Size(1000, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = StreamController<Trip>();
      addTearDown(controller.close);

      await tester.pumpWidget(ProviderScope(
        overrides: [tripRouteProvider('active-trip').overrideWith((ref) => controller.stream)],
        child: CupertinoApp(
          locale: Locale(language),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(builder: (context) => CupertinoPageScaffold(
            child: Center(child: CupertinoButton(
              onPressed: () => Navigator.of(context).push(CupertinoPageRoute<void>(
                builder: (_) => const SoloTripRoutePage(tripId: 'active-trip'),
              )),
              child: const Text('Open overview'),
            )),
          )),
        ),
      ));
      await tester.tap(find.text('Open overview'));
      await tester.pump();
      expect(find.byType(CupertinoActivityIndicator), findsOneWidget);
      final original = route();
      controller.add(trip(original));
      await tester.pumpAndSettle();

      expect(find.byType(RouteEndpointSummary), findsOneWidget);
      expect(find.byType(RouteSummary), findsOneWidget);
      expect(find.text('356m'), findsOneWidget);
      expect(find.text('07:17'), findsOneWidget);
      expect(tester.widget<RouteMapPreview>(find.byType(RouteMapPreview)).points, original.points);
      expect(tester.widgetList<RouteStepTile>(find.byType(RouteStepTile)).map((tile) => tile.segment.stepId),
        ['wait', 'walk-in', 'bus', 'rail', 'walk-out']);
      if (language == 'en') {
        expect(find.text('Ueno-Matsuzakaya → Asakusa Line'), findsOneWidget);
        expect(find.text('Hirai-nanachome (平井七丁目) → Honjo-azumabashi (本所吾妻橋)'), findsOneWidget);
      }

      final updated = route(
        id: 'replanned',
        arrival: '07:25',
        points: const [LatLng(35.7, 139.8), LatLng(35.65, 139.75)],
      );
      controller.add(trip(updated));
      await tester.pumpAndSettle();
      expect(tester.widget<RouteSummary>(find.byType(RouteSummary)).candidate.id, 'replanned');
      expect(find.text('07:25'), findsOneWidget);
      expect(find.text('07:17'), findsNothing);
      expect(tester.widget<RouteMapPreview>(find.byType(RouteMapPreview)).points, updated.points);

      controller.addError(StateError('route subscription failed'));
      await tester.pumpAndSettle();
      expect(find.textContaining('route subscription failed'), findsOneWidget);
      expect(find.byType(RouteSummary), findsNothing);

      controller.add(trip(updated));
      await tester.pumpAndSettle();
      final page = tester.element(find.byType(SoloTripRoutePage));
      Navigator.of(page).pop();
      await tester.pumpAndSettle();
      expect(find.text('Open overview'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('legacy schematic geometry is explicitly labeled', (tester) async {
    final original = route();
    final legacy = Leg.fromJson({
      'candidate': {...original.toJson(includePoints: false),
        'origin_coords': [35.7, 139.8], 'destination_coords': [35.6, 139.7]},
    });
    final savedTrip = trip(legacy.candidate);
    savedTrip.legs[0] = legacy;
    await tester.pumpWidget(ProviderScope(
      overrides: [tripRouteProvider('active-trip').overrideWith((ref) => Stream.value(savedTrip))],
      child: CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const SoloTripRoutePage(tripId: 'active-trip'),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('経路線は概略です'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

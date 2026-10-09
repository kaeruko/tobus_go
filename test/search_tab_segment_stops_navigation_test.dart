import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart' show BottomNavigationBarItem;
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart'
    as maps;
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/pages/segment_stops_page.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';

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

class _RootPopObserver extends NavigatorObserver {
  int popCount = 0;

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    popCount += 1;
    super.didPop(route, previousRoute);
  }
}

class _SearchResultsPage extends StatelessWidget {
  final StepSeg segment;

  const _SearchResultsPage({required this.segment});

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(middle: Text('検索結果')),
      child: SafeArea(
        child: Center(
          child: CupertinoButton(
            key: const ValueKey('open-route-detail'),
            onPressed: () {
              Navigator.of(context).push(
                CupertinoPageRoute<void>(
                  builder: (_) => _RouteDetailHarness(segment: segment),
                ),
              );
            },
            child: const Text('路線詳細を開く'),
          ),
        ),
      ),
    );
  }
}

class _RouteDetailHarness extends StatelessWidget {
  final StepSeg segment;

  const _RouteDetailHarness({required this.segment});

  @override
  Widget build(BuildContext context) {
    return CupertinoPageScaffold(
      navigationBar: const CupertinoNavigationBar(middle: Text('路線詳細')),
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [RouteStepTile(segment: segment)],
        ),
      ),
    );
  }
}

void main() {
  setUp(() {
    final previous = maps.GoogleMapsFlutterPlatform.instance;
    maps.GoogleMapsFlutterPlatform.instance = TestMaps();
    addTearDown(() => maps.GoogleMapsFlutterPlatform.instance = previous);
  });

  StepSeg busSegment() => StepSeg(
    stepId: 'search-route-bus-1',
    kind: 'bus',
    title: '里22 日暮里駅前行',
    titleEn: 'Route Sato22 · Nippori Sta.',
    routeId: 'odpt.Busroute:Toei.Sato22',
    tripId: 'trip-sato22-nippori',
    arrivalPoleId: 'stop-nippori',
    fromName: '亀戸駅前',
    fromNameEn: 'Kameido Sta.',
    toName: '日暮里駅前',
    toNameEn: 'Nippori Sta.',
    minutes: 24,
    departureTime: '11:03',
    arrivalTime: '11:27',
    edges: 2,
    stops: [
      StopPoint(
        name: '亀戸駅前',
        nameEn: 'Kameido Sta.',
        point: const LatLng(35.6973, 139.8262),
        isOrigin: true,
        stopId: 'stop-kameido',
      ),
      StopPoint(
        name: '日暮里駅前',
        nameEn: 'Nippori Sta.',
        point: const LatLng(35.7278, 139.7709),
        isDestination: true,
        stopId: 'stop-nippori',
      ),
    ],
  );

  testWidgets(
    'search tab keeps route detail and stops on nested Navigator and back never pops root',
    (tester) async {
      final rootObserver = _RootPopObserver();
      final searchNavigatorKey = GlobalKey<NavigatorState>();
      final segment = busSegment();

      await tester.pumpWidget(
        CupertinoApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          navigatorObservers: [rootObserver],
          home: CupertinoTabScaffold(
            tabBar: CupertinoTabBar(
              items: const [
                BottomNavigationBarItem(
                  icon: Icon(CupertinoIcons.search),
                  label: '検索',
                ),
                BottomNavigationBarItem(
                  icon: Icon(CupertinoIcons.settings),
                  label: '設定',
                ),
              ],
            ),
            tabBuilder: (context, index) {
              if (index == 0) {
                return CupertinoTabView(
                  navigatorKey: searchNavigatorKey,
                  builder: (_) => _SearchResultsPage(segment: segment),
                );
              }
              return CupertinoTabView(
                builder: (_) => const CupertinoPageScaffold(
                  child: Center(child: Text('設定')),
                ),
              );
            },
          ),
        ),
      );

      expect(searchNavigatorKey.currentState, isNotNull);
      expect(searchNavigatorKey.currentState!.canPop(), isFalse);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.byKey(const ValueKey('open-route-detail')));
      await tester.pumpAndSettle();

      expect(find.text('路線詳細'), findsOneWidget);
      expect(searchNavigatorKey.currentState!.canPop(), isTrue);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.text('里22 日暮里駅前行'));
      await tester.pumpAndSettle();

      expect(find.text('亀戸駅前'), findsOneWidget);
      expect(find.text('日暮里駅前'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('segment-stops-back')),
        findsOneWidget,
      );
      expect(searchNavigatorKey.currentState!.canPop(), isTrue);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.byKey(const ValueKey('segment-stops-back')));
      await tester.pumpAndSettle();

      expect(find.text('路線詳細'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('segment-stops-back')),
        findsNothing,
      );
      expect(searchNavigatorKey.currentState!.canPop(), isTrue);
      expect(rootObserver.popCount, 0);

      await tester.tap(find.byType(CupertinoNavigationBarBackButton));
      await tester.pumpAndSettle();

      expect(find.text('検索結果'), findsOneWidget);
      expect(searchNavigatorKey.currentState!.canPop(), isFalse);
      expect(rootObserver.popCount, 0);
    },
  );

  testWidgets(
    'route step timetable uses stop IDs from the canonical stops list',
    (tester) async {
      final originalClient = ApiClient.httpClient;
      configureApiBase(Uri.parse('https://api.example.test'));
      ApiClient.httpClient = MockClient((request) async {
        expect(request.url.path, '/bus/next');
        expect(request.url.queryParameters['pole_id'], 'stop-kameido');
        expect(request.url.queryParameters['date'], '2026-10-09');
        expect(request.url.queryParameters['time'], '18:21');
        expect(
          request.url.queryParameters['target_pole_id'],
          'stop-nippori',
        );
        expect(
          request.url.queryParameters['pattern_trip_id'],
          'trip-sato22-nippori',
        );
        return http.Response(
          '{"destinations":[]}',
          200,
          headers: const {'content-type': 'application/json; charset=utf-8'},
        );
      });
      addTearDown(() => ApiClient.httpClient = originalClient);

      await tester.pumpWidget(
        CupertinoApp(
          locale: const Locale('ja'),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: CupertinoPageScaffold(
            child: SafeArea(
              child: RouteStepTile(
                segment: busSegment(),
                showTimetable: true,
                timetableReferenceTime: DateTime(2026, 10, 9, 18, 21),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('segment stops shows a route guide from existing segment data', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: SegmentStopsPage(segment: busSegment()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('経路案内'), findsOneWidget);
    expect(find.text('里22 日暮里駅前行'), findsOneWidget);
    expect(find.byKey(const ValueKey('segment-route-map')), findsOneWidget);
    expect(find.byType(GoogleMap), findsOneWidget);
    final routeMap = tester.widget<GoogleMap>(find.byType(GoogleMap));
    expect(routeMap.myLocationEnabled, isTrue);
    expect(routeMap.myLocationButtonEnabled, isTrue);
    expect(find.text('11:03発'), findsWidgets);
    expect(find.text('11:27着'), findsWidgets);
    expect(find.text('乗車24分 / 2停留所'), findsOneWidget);
    expect(find.text('Google Mapsで開く'), findsNothing);
    expect(find.text('亀戸駅前'), findsOneWidget);
    expect(find.text('日暮里駅前'), findsOneWidget);
  });

  testWidgets('route guide collapses without requesting more route data', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: SegmentStopsPage(segment: busSegment()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('segment-route-map')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('segment-guide-toggle')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('segment-route-map')), findsNothing);
    expect(find.text('乗車24分 / 2停留所'), findsNothing);
    expect(find.text('里22 日暮里駅前行'), findsOneWidget);
  });

  testWidgets('stops back fails fast when no previous app route exists', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: SegmentStopsPage(segment: busSegment()),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('segment-stops-back')));
    await tester.pump();

    expect(tester.takeException(), isA<StateError>());
  });
  testWidgets('stop timetable opens as an hour grid and switches day type', (
    tester,
  ) async {
    final originalClient = ApiClient.httpClient;
    final requestedDayTypes = <String>[];
    configureApiBase(Uri.parse('https://api.example.test'));
    ApiClient.httpClient = MockClient((request) async {
      expect(request.url.path, '/bus/next');
      expect(request.url.queryParameters['pole_id'], 'stop-kameido');
      expect(
        request.url.queryParameters['route_id'],
        'odpt.Busroute:Toei.Sato22',
      );
      expect(request.url.queryParameters.containsKey('target_pole_id'), isFalse);
      expect(request.url.queryParameters.containsKey('pattern_trip_id'), isFalse);
      expect(
        request.url.queryParameters['preferred_pattern_trip_id'],
        'trip-sato22-nippori',
      );
      expect(request.url.queryParameters['limit'], '3');
      expect(request.url.queryParameters['include_all'], 'true');
      final dayType = request.url.queryParameters['day_type'];
      expect(dayType, isIn(['weekday', 'saturday', 'holiday']));
      requestedDayTypes.add(dayType!);
      return http.Response(
        '{"destinations":['
        '{"destination_pole_id":"stop-nippori",'
        '"destination_name":"日暮里駅前",'
        '"destination_name_en":"Nippori Sta.",'
        '"times":["15:10","15:25","15:40"],'
        '"all_times":["14:10","14:25","14:40","15:10","15:25","15:40","16:05","16:20"]},'
        '{"destination_pole_id":"stop-minowa",'
        '"destination_name":"三ノ輪二丁目",'
        '"destination_name_en":"Minowa 2-chome",'
        '"times":["15:12","15:42"],'
        '"all_times":["14:12","15:12","15:42","16:12"]}'
        ']}',
        200,
        headers: const {'content-type': 'application/json; charset=utf-8'},
      );
    });
    addTearDown(() => ApiClient.httpClient = originalClient);

    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: SegmentStopsPage(segment: busSegment()),
      ),
    );

    expect(find.byIcon(CupertinoIcons.clock), findsNWidgets(2));
    await tester.tap(
      find.byKey(const ValueKey('stop-timetable-stop-kameido')),
    );
    await tester.pumpAndSettle();

    expect(find.text('亀戸駅前 発の時刻表'), findsOneWidget);
    expect(find.text('平日'), findsOneWidget);
    expect(find.text('土曜'), findsOneWidget);
    expect(find.text('日・祝'), findsOneWidget);
    expect(find.text('日暮里駅前行'), findsOneWidget);
    expect(find.text('三ノ輪二丁目行'), findsOneWidget);
    expect(find.text('14'), findsOneWidget);
    expect(find.text('15'), findsOneWidget);
    expect(find.text('16'), findsOneWidget);
    expect(find.text('15:10'), findsNothing);

    await tester.tap(find.text('三ノ輪二丁目行'));
    await tester.pumpAndSettle();
    expect(find.text('14'), findsOneWidget);
    expect(find.text('15'), findsOneWidget);
    expect(find.text('16'), findsOneWidget);

    final initialDayType = requestedDayTypes.single;
    final targetDayType = initialDayType == 'weekday'
        ? 'Saturday'
        : 'Weekday';
    await tester.tap(
      find.byKey(ValueKey('timetable-day-$targetDayType')),
    );
    await tester.pumpAndSettle();

    expect(requestedDayTypes.last, targetDayType.toLowerCase());
  });

  testWidgets('stop timetable keeps bilingual destination in English', (
    tester,
  ) async {
    final originalClient = ApiClient.httpClient;
    configureApiBase(Uri.parse('https://api.example.test'));
    ApiClient.httpClient = MockClient((request) async {
      expect(request.url.queryParameters['limit'], '3');
      expect(request.url.queryParameters['include_all'], 'true');
      expect(
        request.url.queryParameters['day_type'],
        isIn(['weekday', 'saturday', 'holiday']),
      );
      return http.Response(
        '{"destinations":[{"destination_pole_id":"stop-nippori",'
        '"destination_name":"日暮里駅前",'
        '"destination_name_en":"Nippori Sta.",'
        '"times":["15:10","15:25","15:40"],'
        '"all_times":["14:10","14:25","14:40","15:10","15:25","15:40","16:05","16:20"]}]}',
        200,
        headers: const {'content-type': 'application/json; charset=utf-8'},
      );
    });
    addTearDown(() => ApiClient.httpClient = originalClient);

    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: SegmentStopsPage(segment: busSegment()),
      ),
    );

    await tester.tap(
      find.byKey(const ValueKey('stop-timetable-stop-kameido')),
    );
    await tester.pumpAndSettle();

    expect(
      find.text('Timetable from Kameido Sta. (亀戸駅前)'),
      findsOneWidget,
    );
    expect(find.text('Weekday'), findsOneWidget);
    expect(find.text('Saturday'), findsOneWidget);
    expect(find.text('Holiday'), findsOneWidget);
    expect(find.text('Nippori Sta. (日暮里駅前)'), findsWidgets);
    expect(find.text('14'), findsOneWidget);
    expect(find.text('15:10'), findsNothing);
  });

  testWidgets('stop list renders English boarding labels', (tester) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: SegmentStopsPage(segment: busSegment()),
      ),
    );

    expect(find.text('Kameido Sta. (亀戸駅前)'), findsOneWidget);
    expect(find.text('Nippori Sta. (日暮里駅前)'), findsOneWidget);
    expect(find.text('Board'), findsOneWidget);
    expect(find.text('Get off'), findsOneWidget);
  });

}

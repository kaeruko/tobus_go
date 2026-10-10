import 'package:flutter/cupertino.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:google_maps_flutter_platform_interface/google_maps_flutter_platform_interface.dart'
    as maps;
import 'package:url_launcher_platform_interface/link.dart' as launcher_link;
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart'
    as launcher;
import 'package:toeigo/l10n/app_localizations.dart';
import 'package:toeigo/models/route_map_segment.dart';
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

class TestLauncher extends launcher.UrlLauncherPlatform {
  @override
  launcher_link.LinkDelegate? get linkDelegate => null;

  final urls = <Uri>[];
  final modes = <launcher.PreferredLaunchMode>[];
  bool result = true;
  Object? error;

  @override
  Future<bool> launchUrl(String url, launcher.LaunchOptions options) async {
    urls.add(Uri.parse(url));
    modes.add(options.mode);
    if (error != null) throw error!;
    return result;
  }
}

void main() {
  late TestLauncher urlLauncher;
  setUp(() {
    final oldMaps = maps.GoogleMapsFlutterPlatform.instance;
    final oldLauncher = launcher.UrlLauncherPlatform.instance;
    maps.GoogleMapsFlutterPlatform.instance = TestMaps();
    urlLauncher = TestLauncher();
    launcher.UrlLauncherPlatform.instance = urlLauncher;
    addTearDown(() {
      maps.GoogleMapsFlutterPlatform.instance = oldMaps;
      launcher.UrlLauncherPlatform.instance = oldLauncher;
    });
  });

  Future<void> showMap(WidgetTester tester, {
    String language = 'ja',
    List<LatLng> points = const [LatLng(35, 139), LatLng(36, 140)],
  }) async {
    await tester.pumpWidget(CupertinoApp(
      locale: Locale(language),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: CupertinoPageScaffold(
        child: Center(child: RouteMapPreview(points: points)),
      ),
    ));
    await tester.pumpAndSettle();
  }

  for (final language in ['ja', 'en']) {
    testWidgets('$language button opens the visible map center externally',
        (tester) async {
      await showMap(tester, language: language);
      final label =
          language == 'ja' ? 'Google Mapsで開く' : 'Open in Google Maps';
      await tester.tap(find.text(label));
      await tester.pumpAndSettle();
      expect(urlLauncher.urls.single.host, 'www.google.com');
      expect(urlLauncher.urls.single.path, '/maps/search/');
      expect(urlLauncher.urls.single.queryParameters, {
        'api': '1',
        'query': '35.5,139.5',
      });
      expect(urlLauncher.modes.single,
          launcher.PreferredLaunchMode.externalApplication);

      final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
      map.onCameraMove!(
          const CameraPosition(target: LatLng(35.7, 139.8), zoom: 14));
      await tester.tap(find.text(label));
      await tester.pumpAndSettle();
      expect(urlLauncher.urls.last.queryParameters['query'], '35.7,139.8');
    });
  }

  testWidgets('map tap and endpoint pins open their exact locations',
      (tester) async {
    await showMap(tester);
    final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
    map.onTap!(const LatLng(35.123456, 139.654321));
    await tester.pumpAndSettle();
    expect(urlLauncher.urls.last.queryParameters['query'],
        '35.123456,139.654321');
    for (final marker in map.markers) {
      expect(marker.consumeTapEvents, isTrue);
      marker.onTap!();
      await tester.pumpAndSettle();
      expect(urlLauncher.urls.last.queryParameters['query'],
          '${marker.position.latitude},${marker.position.longitude}');
    }
    expect(urlLauncher.urls, hasLength(3));
  });

  testWidgets('compact map allows pan and zoom without external navigation', (
    tester,
  ) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const CupertinoPageScaffold(
          child: RouteMapPreview(
            points: [LatLng(35, 139), LatLng(36, 140)],
            showOpenButton: false,
            height: 150,
            margin: EdgeInsets.zero,
            interactive: true,
            openExternalOnTap: false,
            rotateGesturesEnabled: false,
            tiltGesturesEnabled: false,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.getSize(find.byType(RouteMapPreview)).height, 150);
    expect(find.text('Google Mapsで開く'), findsNothing);

    final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
    expect(map.onTap, isNull);
    expect(map.scrollGesturesEnabled, isTrue);
    expect(map.gestureRecognizers, hasLength(1));
    expect(map.zoomGesturesEnabled, isTrue);
    expect(map.rotateGesturesEnabled, isFalse);
    expect(map.tiltGesturesEnabled, isFalse);
    for (final marker in map.markers) {
      expect(marker.consumeTapEvents, isFalse);
      expect(marker.onTap, isNull);
    }
    expect(urlLauncher.urls, isEmpty);
  });

  testWidgets('current location layer is opt-in', (tester) async {
    await tester.pumpWidget(
      CupertinoApp(
        locale: const Locale('ja'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: const CupertinoPageScaffold(
          child: RouteMapPreview(
            points: [LatLng(35, 139), LatLng(36, 140)],
            showUserLocation: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
    expect(map.myLocationEnabled, isTrue);
    expect(map.myLocationButtonEnabled, isTrue);
  });

  testWidgets('no geometry means no external map action', (tester) async {
    await showMap(tester, points: const []);
    expect(find.byType(GoogleMap), findsNothing);
    expect(find.text('Google Mapsで開く'), findsNothing);
    expect(urlLauncher.urls, isEmpty);
  });

  for (final throwsException in [false, true]) {
    testWidgets(
        'launch failure is reported without another URL or mode ($throwsException)',
        (tester) async {
      final original =
          PlatformException(code: 'launch_failed', message: 'diagnostic');
      if (throwsException) {
        urlLauncher.error = original;
      } else {
        urlLauncher.result = false;
      }
      await showMap(tester);
      final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
      map.onTap!(const LatLng(35.7, 139.8));
      await tester.pumpAndSettle();
      expect(tester.takeException(),
          throwsException ? same(original) : isA<StateError>());
      expect(find.text('Google Mapsを開けませんでした'), findsOneWidget);
      expect(find.textContaining('https://www.google.com/maps/search/'),
          findsOneWidget);
      expect(urlLauncher.urls, hasLength(1));
      expect(urlLauncher.modes,
          [launcher.PreferredLaunchMode.externalApplication]);
    });
  }

  testWidgets('Tokyo mode geometry paints walk dashed and rides solid', (tester) async {
    final geometry = <RouteMapSegment>[
      RouteMapSegment(
        kind: 'walk',
        points: const [LatLng(35.0, 139.0), LatLng(35.001, 139.0)],
      ),
      RouteMapSegment(
        kind: 'bus',
        points: const [LatLng(35.001, 139.0), LatLng(35.005, 139.0)],
      ),
      RouteMapSegment(
        kind: 'rail',
        points: const [LatLng(35.005, 139.0), LatLng(35.01, 139.0)],
      ),
    ];
    await tester.pumpWidget(CupertinoApp(
      locale: const Locale('ja'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: CupertinoPageScaffold(
        child: RouteMapPreview(
          points: const [LatLng(35.0, 139.0), LatLng(35.01, 139.0)],
          routeGeometry: geometry,
        ),
      ),
    ));
    await tester.pumpAndSettle();

    final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
    expect(map.polylines, hasLength(3));
    final segments = {
      for (final line in map.polylines) line.polylineId.value: line,
    };
    final walking = segments['route_leg_0']!;
    final bus = segments['route_leg_1']!;
    final rail = segments['route_leg_2']!;
    expect(walking.points, geometry[0].points);
    expect(walking.patterns.map((pattern) => pattern.type).toList(),
        [PatternItemType.dash, PatternItemType.gap]);
    expect(bus.patterns, isEmpty);
    expect(rail.patterns, isEmpty);
    expect(bus.points, geometry[1].points);
    expect(rail.points, geometry[2].points);
    expect(map.markers, hasLength(2));
    expect(tester.takeException(), isNull);
  });

  testWidgets('legacy map still draws one solid polyline', (tester) async {
    await showMap(tester);
    final map = tester.widget<GoogleMap>(find.byType(GoogleMap));
    expect(map.polylines, hasLength(1));
    expect(map.polylines.single.polylineId.value, 'route');
    expect(map.polylines.single.patterns, isEmpty);
  });

  testWidgets('explicit empty route geometry cannot silently use old line',
      (tester) async {
    await tester.pumpWidget(CupertinoApp(
      locale: const Locale('ja'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: const CupertinoPageScaffold(
        child: RouteMapPreview(
          points: [LatLng(35, 139), LatLng(36, 140)],
          routeGeometry: [],
        ),
      ),
    ));
    final error = tester.takeException();
    expect(error, isA<StateError>());
    expect(error.toString(), contains('route_geometry'));
  });
}
